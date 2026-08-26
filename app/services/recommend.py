import json
import math
import time

import httpx
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.models import AudioFeatures, Cluster, Lyrics, Track

MB_API = "https://musicbrainz.org/ws/2/artist"
MIN_INTERVAL = 1.1

MOOD_TAGS = {
    "Весёлое": ["pop", "dance"],
    "Энергичное": ["electronic", "dance"],
    "Спокойное": ["ambient", "chillout"],
    "Меланхоличное": ["indie", "post-rock"],
    "Эпичное": ["orchestral", "post-rock"],
    "Тёмное": ["gothic", "industrial"],
    "Романтичное": ["acoustic", "chanson"],
    "Атмосферное": ["ambient", "downtempo"],
}

_last_call = 0.0
_cache: dict[str, tuple[float, list[dict]]] = {}
CACHE_TTL = 86400.0


MOOD_COLS = [
    "mood_happy",
    "mood_sad",
    "mood_relaxed",
    "mood_aggressive",
    "mood_epic",
    "mood_dark",
    "mood_romantic",
    "mood_atmospheric",
]

# веса групп фич для похожести v2
W_TIMBRE = 0.25
W_RHYTHM = 0.15
W_HARMONY = 0.15
W_MACRO = 0.10
W_INSTRUMENTS = 0.10
W_GENRE = 0.10
W_LYRICS = 0.075
W_TOPICS = 0.075
ARTIST_SHRINKAGE = 3.0
MIN_V2_TRACKS = 2


def _parse(v: str | None) -> np.ndarray | None:
    if not v:
        return None
    try:
        return np.array(json.loads(v), dtype=float)
    except (ValueError, TypeError):
        return None


def _v2_matrix(
    session: Session, features: list[AudioFeatures], smooth: bool = True
) -> tuple[dict[str, dict[str, np.ndarray]], list[AudioFeatures]]:
    """Строит стандартизованные группы: {группа: {track_id: вектор}}.

    При smooth=True вектор трека сглаживается центроидом его исполнителя
    (shrinkage α = n/(n+k)) — для рекомендаций; для кластеризации smooth=False.
    """
    usable = [
        f
        for f in features
        if f.feat_version >= 2
        and _parse(f.mfcc) is not None
        and _parse(f.chroma) is not None
        and _parse(f.contrast) is not None
    ]
    if len(usable) < 2:
        return {}, usable

    def raw_vec(f: AudioFeatures) -> np.ndarray:
        mfcc_v = _parse(f.mfcc)
        chroma_v = _parse(f.chroma)
        contrast_v = _parse(f.contrast)
        mfcc = mfcc_v if mfcc_v is not None else np.zeros(26)
        chroma = chroma_v if chroma_v is not None else np.zeros(12)
        contrast = contrast_v if contrast_v is not None else np.zeros(7)
        rhythm = np.array(
            [
                np.log1p(f.tempo),
                f.danceability,
                f.percussive if f.percussive is not None else 0.5,
            ]
        )
        macro = np.array(
            [
                f.energy,
                f.acousticness,
                f.brightness,
                f.dynamics if f.dynamics is not None else 0.0,
                (f.loudness if f.loudness is not None else -20.0) / 45.0,
            ]
        )
        return np.concatenate([mfcc, chroma, contrast, rhythm, macro])

    # центроиды исполнителей в raw-пространстве (для сглаживания)
    by_artist: dict[str, list[np.ndarray]] = {}
    track_artist: dict[str, str] = {}
    if smooth:
        for f in usable:
            row = session.get(Track, f.track_id)
            if row is not None and row.channel:
                by_artist.setdefault(row.channel, []).append(raw_vec(f))
                track_artist[f.track_id] = row.channel

    def smoothed(f: AudioFeatures) -> np.ndarray:
        v = raw_vec(f)
        ch = track_artist.get(f.track_id)
        vecs = by_artist.get(ch, []) if ch else []
        if len(vecs) < 2:
            return v
        centroid = np.mean(vecs, axis=0)
        n = len(vecs)
        alpha = n / (n + ARTIST_SHRINKAGE)
        return alpha * v + (1 - alpha) * centroid

    raw = np.vstack([smoothed(f) for f in usable])
    scaled = StandardScaler().fit_transform(raw)
    ids = [f.track_id for f in usable]
    groups: dict[str, dict[str, np.ndarray]] = {
        "timbre": dict(zip(ids, scaled[:, 0:26])),
        "harmony": dict(zip(ids, scaled[:, 26:38])),
        "rhythm": dict(zip(ids, scaled[:, 38:41])),
        "macro": dict(zip(ids, scaled[:, 41:46])),
    }
    return groups, usable


GROUP_LABELS = {
    "timbre": "по тембру",
    "rhythm": "по ритму",
    "harmony": "по гармонии",
    "macro": "по характеру",
    "instruments": "по инструментам",
    "genre": "по жанру",
    "lyrics": "по тексту",
    "topics": "по темам",
}

# размерности векторных групп (для нормализации масштаба L2-расстояний)
GROUP_DIMS = {"timbre": 26, "harmony": 12, "rhythm": 3, "macro": 5}


def _parse_tags(tags_json: str | None) -> tuple[dict[str, float], dict[str, float]]:
    """(вектор жанров, вектор инструментов) из Essentia tags json."""
    if not tags_json:
        return {}, {}
    try:
        data = json.loads(tags_json)
    except ValueError:
        return {}, {}
    genres = {g["name"]: float(g.get("score", 0.0)) for g in data.get("genres", [])}
    instruments = {
        g["name"]: float(g.get("score", 0.0)) for g in data.get("instruments", [])
    }
    return genres, instruments


def _cosine_dist(a: dict[str, float], b: dict[str, float]) -> float | None:
    """Косинусное расстояние между разреженными векторами-словарями."""
    if not a or not b:
        return None
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0.0 or nb == 0.0:
        return None
    return 1.0 - dot / (na * nb)


def _load_semantic(
    session: Session, ids: list[str]
) -> tuple[
    dict[str, dict[str, float]],
    dict[str, dict[str, float]],
    dict[str, dict[str, float]],
    dict[str, object],
]:
    """Теговые и текстовые данные треков.

    Возвращает (genres, instruments, topics, tfidf):
    genres/instruments/topics — {track_id: вектор-словарь};
    tfidf — {track_id: нормированный разреженный вектор текста}.
    """
    genres: dict[str, dict[str, float]] = {}
    instruments: dict[str, dict[str, float]] = {}
    topics: dict[str, dict[str, float]] = {}
    texts_by_lang: dict[str, dict[str, str]] = {}
    id_set = set(ids)
    for f in session.exec(
        select(AudioFeatures.track_id, AudioFeatures.tags).where(  # type: ignore[arg-type]
            AudioFeatures.track_id.in_(id_set)  # type: ignore[union-attr]
        )
    ).all():
        g, i = _parse_tags(f[1])
        if g:
            genres[f[0]] = g
        if i:
            instruments[f[0]] = i
    for row in session.exec(
        select(Lyrics.track_id, Lyrics.language, Lyrics.topics, Lyrics.text).where(  # type: ignore[arg-type]
            Lyrics.track_id.in_(id_set)  # type: ignore[union-attr]
        )
    ).all():
        tid, lang, topics_json, text = row
        if topics_json:
            try:
                vec = json.loads(topics_json)
                if vec:
                    topics[tid] = {k: float(v) for k, v in vec.items()}
            except ValueError:
                pass
        if text:
            texts_by_lang.setdefault(lang or "en", {})[tid] = text

    tfidf: dict[str, object] = {}
    for lang, texts in texts_by_lang.items():
        if len(texts) < 2:
            continue
        try:
            matrix = TfidfVectorizer(max_features=20000).fit_transform(
                texts.values()
            )
        except ValueError:
            continue
        # TfidfVectorizer по умолчанию даёт L2-нормированные строки
        for tid, row_idx in zip(texts.keys(), range(matrix.shape[0])):
            tfidf[tid] = matrix[row_idx]
    return genres, instruments, topics, tfidf


def _tfidf_dist(tfidf: dict[str, object], a: str, b: str) -> float | None:
    """Косинусное расстояние текстов (только одинаковый корпус = язык)."""
    va, vb = tfidf.get(a), tfidf.get(b)
    if va is None or vb is None or va.shape != vb.shape:
        return None
    return float(1.0 - va.multiply(vb).sum())


def similar_tracks_v2(track_id: str, k: int = 6) -> list[dict] | None:
    """Взвешенная похожесть по группам фич + теги/тексты/темы.

    None — недостаточно v2-треков. Группы участвуют в скоре пары только
    если данные есть у обоих треков; общий скор нормируется на сумму
    весов доступных групп (треки без текстов не штрафуются).
    """
    weights = {
        "timbre": W_TIMBRE,
        "rhythm": W_RHYTHM,
        "harmony": W_HARMONY,
        "macro": W_MACRO,
        "instruments": W_INSTRUMENTS,
        "genre": W_GENRE,
        "lyrics": W_LYRICS,
        "topics": W_TOPICS,
    }
    with Session(engine) as session:
        features = session.exec(
            select(AudioFeatures).where(AudioFeatures.source == "audio")
        ).all()
        groups, usable = _v2_matrix(session, features)
        if len(usable) < MIN_V2_TRACKS or track_id not in groups["timbre"]:
            return None
        ids = [f.track_id for f in usable]
        genres, instruments, topics, tfidf = _load_semantic(session, ids)

        def pair_distance(other_id: str) -> tuple[float | None, str]:
            """(общий скор, ближайшая группа); None — нет общих групп."""
            per_group: dict[str, float] = {}
            for g, dim in GROUP_DIMS.items():
                # L2 по стандартизованным фичам, нормированный на размерность,
                # чтобы масштаб был сопоставим с косинусными расстояниями 0..2
                d = float(np.linalg.norm(groups[g][track_id] - groups[g][other_id]))
                per_group[g] = d / math.sqrt(dim)
            for g, vecs in (
                ("instruments", instruments),
                ("genre", genres),
                ("topics", topics),
            ):
                d = _cosine_dist(vecs.get(track_id), vecs.get(other_id))  # type: ignore[arg-type]
                if d is not None:
                    per_group[g] = d
            d = _tfidf_dist(tfidf, track_id, other_id)
            if d is not None:
                per_group["lyrics"] = d
            if not per_group:
                return None, ""
            w_sum = sum(weights[g] for g in per_group)
            total = sum(weights[g] * per_group[g] for g in per_group) / w_sum
            closest = min(per_group, key=per_group.get)
            return total, closest

        scored: list[tuple[float, AudioFeatures, str]] = []
        for other in usable:
            if other.track_id == track_id:
                continue
            total, label = pair_distance(other.track_id)
            if total is None:
                continue
            scored.append((total, other, GROUP_LABELS[label]))
        scored.sort(key=lambda x: x[0])

        result = []
        for total, other, label in scored[:k]:
            t = session.get(Track, other.track_id)
            if t is None:
                continue
            result.append(
                {
                    "track": t,
                    "distance": round(total, 3),
                    "tempo": other.tempo,
                    "match": label,
                }
            )
        return result


def similar_artists(track_id: str, k: int = 5) -> list[dict] | None:
    """Ближайшие исполнители из истории по центроидам их фич."""
    with Session(engine) as session:
        features = session.exec(
            select(AudioFeatures).where(AudioFeatures.source == "audio")
        ).all()
        groups, usable = _v2_matrix(session, features)
        if len(usable) < MIN_V2_TRACKS or track_id not in groups["timbre"]:
            return None

        weights = {
            "timbre": W_TIMBRE,
            "rhythm": W_RHYTHM,
            "harmony": W_HARMONY,
            "macro": W_MACRO,
        }
        by_artist: dict[str, list[str]] = {}
        for f in usable:
            row = session.get(Track, f.track_id)
            if row is not None and row.channel:
                by_artist.setdefault(row.channel, []).append(f.track_id)
        if len(by_artist) < 2:
            return None

        def artist_vec(ids: list[str]) -> np.ndarray:
            return np.mean(
                [np.concatenate([groups[g][i] for g in weights]) for i in ids], axis=0
            )

        selected = session.get(Track, track_id)
        if selected is None or selected.channel not in by_artist:
            return None
        sel_vec = artist_vec(by_artist[selected.channel])

        scored: list[tuple[float, str]] = []
        for ch, ids in by_artist.items():
            if ch == selected.channel:
                continue
            vec = artist_vec(ids)
            dist = float(np.linalg.norm(sel_vec - vec))
            scored.append((dist, ch))
        scored.sort(key=lambda x: x[0])

        result = []
        for dist, ch in scored[:k]:
            tracks = session.exec(
                select(Track).where(Track.channel == ch, Track.is_music == True)  # noqa: E712
            ).all()
            plays = sum(t.play_count for t in tracks)
            result.append(
                {
                    "channel": ch,
                    "distance": round(dist, 3),
                    "tracks_analyzed": len(by_artist[ch]),
                    "tracks_total": len(tracks),
                    "plays": plays,
                }
            )
        return result


def similar_tracks(track_id: str, k: int = 4) -> list[dict]:
    with Session(engine) as session:
        features = session.exec(select(AudioFeatures)).all()
        if len(features) < 2:
            return []
        selected = session.get(AudioFeatures, track_id)
        if selected is None:
            return []
        if selected.source == "audio":
            pool = [f for f in features if f.source == "audio"]
            cols = ["tempo", "energy", "danceability", "acousticness"]
        else:
            pool = features
            cols = MOOD_COLS
        if len(pool) < 2:
            pool, cols = features, MOOD_COLS
        X = np.array([[getattr(f, c) for c in cols] for f in pool])
        X_scaled = StandardScaler().fit_transform(X)
        idx_map = {f.track_id: i for i, f in enumerate(pool)}
        if track_id not in idx_map:
            return []
        nn = NearestNeighbors(n_neighbors=min(k + 1, len(pool)), metric="euclidean")
        nn.fit(X_scaled)
        dist, ind = nn.kneighbors([X_scaled[idx_map[track_id]]])
        result = []
        for d, i in zip(dist[0], ind[0]):
            fid = pool[int(i)].track_id
            if fid == track_id:
                continue
            t = session.get(Track, fid)
            if t is None:
                continue
            result.append(
                {
                    "track": t,
                    "distance": round(float(d), 3),
                    "tempo": pool[int(i)].tempo,
                }
            )
            if len(result) >= k:
                break
        return result


def _throttle() -> None:
    global _last_call
    wait = _last_call + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def mb_artists_for_tags(tags: list[str], per_tag: int = 8) -> tuple[list[dict], str]:
    if not settings.mb_enabled:
        return [], "MusicBrainz отключён в настройках (MB_ENABLED=false)"
    artists: list[dict] = []
    now = time.monotonic()
    for tag in tags:
        cached = _cache.get(tag)
        if cached and now - cached[0] < CACHE_TTL:
            artists.extend(cached[1])
            continue
        _throttle()
        try:
            resp = httpx.get(
                MB_API,
                params={
                    "query": f"tag:{tag}",
                    "fmt": "json",
                    "limit": per_tag,
                    "sort": "score-desc",
                },
                headers={"User-Agent": settings.mb_user_agent},
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            return artists, f"MusicBrainz недоступен: {type(exc).__name__}"
        items = []
        for a in payload.get("artists", []):
            name = a.get("name", "")
            if not name:
                continue
            country = a.get("country") or ""
            tags_list = [
                t.get("name", "") for t in (a.get("tags") or [])[:3]
            ]
            items.append(
                {"name": name, "country": country, "tags": ", ".join(filter(None, tags_list))}
            )
        _cache[tag] = (time.monotonic(), items)
        artists.extend(items)
    seen: set[str] = set()
    unique = []
    for a in artists:
        if a["name"] in seen:
            continue
        seen.add(a["name"])
        unique.append(a)
    return unique[:16], ""


def mb_for_track(track_id: str) -> tuple[list[dict], str, str]:
    with Session(engine) as session:
        t = session.get(Track, track_id)
        mood_name = ""
        if t is not None and t.cluster_id is not None:
            cluster = session.get(Cluster, t.cluster_id)
            if cluster is not None:
                mood_name = cluster.name.split(" ·")[0]
    tags = MOOD_TAGS.get(mood_name, ["indie"])
    artists, error = mb_artists_for_tags(tags)
    return artists, error, mood_name
