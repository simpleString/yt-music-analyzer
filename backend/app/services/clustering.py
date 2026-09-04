import json
import threading

import numpy as np
from sqlalchemy import text
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sqlmodel import Session, select

from app.db import engine
from app.models import AudioFeatures, Cluster, Track
from app.services import jobs
from app.services.recommend import _v2_matrix

MOOD_COLS = [
    "mood_happy",
    "mood_sad",
    "mood_relaxed",
    "mood_aggressive",
    "mood_electronic",
    "mood_acoustic",
    "mood_party",
    "mood_epic",
    "mood_dark",
    "mood_romantic",
    "mood_atmospheric",
]

CLUSTER_NAMES = {
    "mood_happy": "Happy",
    "mood_aggressive": "Energetic",
    "mood_relaxed": "Calm",
    "mood_sad": "Melancholic",
    "mood_electronic": "Electronic",
    "mood_acoustic": "Acoustic",
    "mood_party": "Party",
    "mood_epic": "Epic",
    "mood_dark": "Dark",
    "mood_romantic": "Romantic",
    "mood_atmospheric": "Atmospheric",
}
MOOD_KEYS = list(CLUSTER_NAMES)

GROUP_WEIGHTS = {
    "timbre": 0.35,
    "rhythm": 0.25,
    "harmony": 0.25,
    "macro": 0.15,
}


def _rankify(values: np.ndarray) -> np.ndarray:
    n = len(values)
    if n <= 1:
        return np.full(n, 0.5)
    order = np.argsort(values)
    ranks = np.empty(n)
    ranks[order] = np.arange(n)
    return ranks / (n - 1)


def compute_moods(session: Session, features: list[AudioFeatures]) -> None:
    """8 moods from Essentia tags (mtg_jamendo_moodtheme).

    Scores are already 0..1 with the dominant mood = 1 (normalized
    in essentia_tags). Tracks without tags keep the uniform default 0.125.
    """
    audio = [f for f in features if f.source == "audio"]
    if len(audio) < 2:
        return

    n = len(audio)
    stack = np.full((len(MOOD_COLS), n), 0.125)

    for i, f in enumerate(audio):
        if not f.tags:
            continue
        try:
            moods = json.loads(f.tags).get("moods") or {}
        except (ValueError, TypeError):
            continue
        vals = [
            float(moods[c]) for c in MOOD_COLS if moods.get(c) is not None
        ]
        if not vals:
            continue
        for j, c in enumerate(MOOD_COLS):
            stack[j, i] = round(float(moods.get(c, 0.0)), 3)

    for f, col in zip(audio, stack.T):
        for j, mood_col in enumerate(MOOD_COLS):
            setattr(f, mood_col, round(float(col[j]), 3))
        session.add(f)
    session.commit()


def auto_k(n: int) -> int:
    if n < 3:
        return 1
    return int(min(8, max(2, round(np.sqrt(n / 2)))))


def _weighted_matrix(groups: dict, ids: list[str]) -> np.ndarray:
    """Weighted matrix from groups: block × √weight (euclidean metric)."""
    blocks = []
    for g, w in GROUP_WEIGHTS.items():
        block = np.array([groups[g][i] for i in ids])
        blocks.append(np.sqrt(w) * block)
    return np.hstack(blocks)


def run_clustering(stop: threading.Event | None = None) -> None:
    try:
        if not jobs.start_job("clusters"):
            return
        stop = stop if stop is not None else threading.Event()
        from app.config import settings as cfg

        with Session(engine) as session:
            # only tracks actually analyzed; preliminary
            # metadata-based estimates are excluded and deleted
            session.execute(
                text("DELETE FROM audio_features WHERE source = 'meta'")
            )
            session.commit()
            features = session.exec(
                select(AudioFeatures).where(AudioFeatures.source == "audio")
            ).all()
            n = len(features)
            if n == 0:
                session.execute(text("UPDATE track SET cluster_id = NULL"))
                session.commit()
                jobs.finish_job(
                    "clusters",
                    "no tracks with audio analysis — run \"Audio analysis\"",
                )
                return

            compute_moods(session, features)
            session.expire_all()
            features = session.exec(
                select(AudioFeatures).where(AudioFeatures.source == "audio")
            ).all()

            # k-means on the weighted v2 vector (timbre/rhythm/harmony/macro)
            groups, usable = _v2_matrix(session, features, smooth=False)
            if len(usable) < 2:
                session.execute(text("UPDATE track SET cluster_id = NULL"))
                session.execute(text("DELETE FROM cluster"))
                session.commit()
                jobs.finish_job(
                    "clusters",
                    f"{n} tracks, but not enough v2 features for clustering",
                )
                return
            ids = list(groups["timbre"].keys())
            X = _weighted_matrix(groups, ids)
            feat_by_id = {f.track_id: f for f in features}

            n_usable = len(ids)
            k = cfg.cluster_k if cfg.cluster_k > 0 else auto_k(n_usable)
            k = max(1, min(k, n_usable))

            km = KMeans(n_clusters=k, n_init=10, random_state=42)
            labels = km.fit_predict(X)
            if jobs.should_stop("clusters", stop):
                session.execute(text("UPDATE track SET cluster_id = NULL"))
                session.execute(text("DELETE FROM cluster"))
                session.commit()
                jobs.stop_job("clusters", "stopped by user")
                return

            session.execute(text("UPDATE track SET cluster_id = NULL"))
            session.execute(text("DELETE FROM cluster"))
            session.commit()

            clusters_info: dict[int, dict] = {}
            for idx, tid in enumerate(ids):
                cidx = int(labels[idx])
                clusters_info.setdefault(cidx, {"rows": []})
                clusters_info[cidx]["rows"].append(feat_by_id[tid])

            names_used: set[str] = set()
            for cidx in sorted(clusters_info):
                rows = clusters_info[cidx]["rows"]
                moods = np.array(
                    [[getattr(r, c) for c in MOOD_COLS] for r in rows]
                )
                mean_mood = moods.mean(axis=0)
                dominant = MOOD_KEYS[int(np.argmax(mean_mood))]
                name = CLUSTER_NAMES[dominant]
                if name in names_used:
                    # Disambiguate without numbers: tempo word, then the
                    # next-dominant moods, e.g. "Calm · fast · Dark".
                    with_tempo = [r.tempo for r in rows if r.tempo > 0]
                    if with_tempo:
                        avg = sum(with_tempo) / len(with_tempo)
                        tword = "fast" if avg >= 120 else "slow"
                    else:
                        tword = "part"
                    name = f"{name} · {tword}"
                    if name in names_used:
                        order = np.argsort(-mean_mood)
                        for mi in order[1:]:
                            extra = CLUSTER_NAMES[MOOD_KEYS[int(mi)]]
                            cand = f"{name} · {extra}"
                            if cand not in names_used:
                                name = cand
                                break
                        else:
                            name = f"{name} · mix"
                names_used.add(name)

                cluster = Cluster(
                    name=name,
                    centroid=json.dumps(
                        {
                            "moods": {
                                c: round(float(m), 3)
                                for c, m in zip(MOOD_COLS, mean_mood)
                            }
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

        jobs.finish_job(
            "clusters",
            detail=(
                f"{n_usable} tracks with v2 features split into {k} clusters "
                f"by sound similarity (timbre/rhythm/harmony)"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        jobs.fail_job("clusters", f"{type(exc).__name__}: {exc}")
        raise
