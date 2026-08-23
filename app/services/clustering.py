import json

import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sqlmodel import Session, select

from app.db import engine
from app.models import AudioFeatures, Cluster, Track
from app.services import jobs
from app.services.meta_moods import ensure_meta_features

MOOD_COLS = ["mood_happy", "mood_sad", "mood_relaxed", "mood_aggressive"]

CLUSTER_NAMES = {
    "mood_happy": "Весёлое",
    "mood_aggressive": "Энергичное",
    "mood_relaxed": "Спокойное",
    "mood_sad": "Меланхоличное",
}
MOOD_KEYS = list(CLUSTER_NAMES)


def _rankify(values: np.ndarray) -> np.ndarray:
    n = len(values)
    if n <= 1:
        return np.full(n, 0.5)
    order = np.argsort(values)
    ranks = np.empty(n)
    ranks[order] = np.arange(n)
    return ranks / (n - 1)


def compute_moods(session: Session, features: list[AudioFeatures]) -> None:
    """Настроения для треков с реальным аудио-анализом (по librosa-фичам)."""
    audio = [f for f in features if f.source == "audio"]
    if len(audio) < 2:
        return
    tempo_r = _rankify(np.array([f.tempo for f in audio]))
    energy_r = _rankify(np.array([f.energy for f in audio]))
    dance_r = _rankify(np.array([f.danceability for f in audio]))
    acoustic_r = _rankify(np.array([f.acousticness for f in audio]))
    bright_r = _rankify(np.array([f.brightness for f in audio]))
    key_minor = np.array([1.0 if "minor" in (f.key or "") else 0.0 for f in audio])
    conf = np.array([f.mode_conf for f in audio])

    minor = key_minor * np.clip(conf, 0.3, 1.0)
    major = (1 - key_minor) * np.clip(conf, 0.3, 1.0)

    happy = major * (0.45 + 0.55 * tempo_r) * (0.35 + 0.65 * energy_r) * (0.75 + 0.25 * (1 - acoustic_r))
    sad = minor * (0.45 + 0.55 * (1 - tempo_r)) * (0.45 + 0.55 * (1 - energy_r)) * (0.6 + 0.4 * acoustic_r)
    relaxed = (1 - energy_r) * (0.4 + 0.6 * acoustic_r) * (0.55 + 0.45 * (1 - tempo_r)) * (0.85 + 0.15 * (1 - bright_r))
    aggressive = (energy_r**1.3) * (1 - acoustic_r) * (0.55 + 0.45 * tempo_r) * (0.5 + 0.5 * dance_r)

    stack = np.vstack([happy, sad, relaxed, aggressive])
    stack = np.clip(stack, 0.0, None)
    denom = stack.sum(axis=0)
    denom[denom <= 0] = 1.0
    stack = stack / denom

    for f, col in zip(audio, stack.T):
        f.mood_happy = round(float(col[0]), 3)
        f.mood_sad = round(float(col[1]), 3)
        f.mood_relaxed = round(float(col[2]), 3)
        f.mood_aggressive = round(float(col[3]), 3)
        session.add(f)
    session.commit()


def auto_k(n: int) -> int:
    if n < 3:
        return 1
    return int(min(6, max(2, round(np.sqrt(n / 2)))))


def run_clustering() -> None:
    try:
        if not jobs.start_job("clusters"):
            return
        from app.config import settings as cfg

        created, _total = ensure_meta_features()

        with Session(engine) as session:
            features = session.exec(select(AudioFeatures)).all()
            n = len(features)
            if n == 0:
                jobs.finish_job("clusters", "нет музыкальных треков для кластеризации")
                return

            compute_moods(session, features)
            session.expire_all()
            features = session.exec(select(AudioFeatures)).all()

            n_audio = sum(1 for f in features if f.source == "audio")

            X = np.array([[getattr(f, c) for c in MOOD_COLS] for f in features])
            X_scaled = StandardScaler().fit_transform(X)

            k = cfg.cluster_k if cfg.cluster_k > 0 else auto_k(n)
            k = max(1, min(k, n))

            km = KMeans(n_clusters=k, n_init=10, random_state=42)
            labels = km.fit_predict(X_scaled)

            from sqlalchemy import text as _text

            session.execute(_text("UPDATE track SET cluster_id = NULL"))
            session.execute(_text("DELETE FROM cluster"))
            session.commit()

            clusters_info: dict[int, dict] = {}
            for idx, f in enumerate(features):
                cidx = int(labels[idx])
                clusters_info.setdefault(cidx, {"rows": []})
                clusters_info[cidx]["rows"].append(f)

            names_used: set[str] = set()
            for cidx in sorted(clusters_info):
                rows = clusters_info[cidx]["rows"]
                moods = np.array([[getattr(r, c) for c in MOOD_COLS] for r in rows])
                mean_mood = moods.mean(axis=0)
                dominant = MOOD_KEYS[int(np.argmax(mean_mood))]
                name = CLUSTER_NAMES[dominant]
                if name in names_used:
                    with_tempo = [r.tempo for r in rows if r.tempo > 0]
                    if with_tempo:
                        avg = sum(with_tempo) / len(with_tempo)
                        base = f"{name} · {'быстрое' if avg >= 120 else 'медленное'}"
                    else:
                        base = f"{name} · часть"
                    name = base
                    suffix = 2
                    while name in names_used:
                        name = f"{base} {suffix}"
                        suffix += 1
                names_used.add(name)

                centroid = [round(float(v), 3) for v in km.cluster_centers_[cidx]]
                cluster = Cluster(
                    name=name,
                    centroid=json.dumps(
                        {
                            "moods": {
                                c: round(float(m), 3)
                                for c, m in zip(MOOD_COLS, mean_mood)
                            },
                            "centroid": dict(zip(MOOD_COLS, centroid)),
                        },
                        ensure_ascii=False,
                    ),
                    size=len(rows),
                )
                session.add(cluster)
                session.commit()
                session.refresh(cluster)
                for r in rows:
                    t = session.get(Track, r.track_id)
                    if t is not None:
                        t.cluster_id = cluster.id
                        session.add(t)
                session.commit()

        src_note = (
            f"аудио: {n_audio}, метаданные: {n - n_audio}"
            if n_audio
            else "оценка по метаданным (без аудио)"
        )
        jobs.finish_job(
            "clusters",
            detail=(
                f"{n} треков разбито на {k} кластеров; {src_note}"
                + (f"; добавлено предварительных оценок: {created}" if created else "")
            ),
        )
    except Exception as exc:  # noqa: BLE001
        jobs.fail_job("clusters", f"{type(exc).__name__}: {exc}")
        raise
