import base64
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
    "mood_electronic",
    "mood_acoustic",
    "mood_party",
    "mood_epic",
    "mood_dark",
    "mood_romantic",
    "mood_atmospheric",
]

# веса групп фич для похожести v2
W_TIMBRE = 0.15
W_EMBEDDING = 0.30
W_RHYTHM = 0.15
W_HARMONY = 0.15
W_MACRO = 0.10
W_MOODS = 0.10
W_INSTRUMENTS = 0.10
W_GENRE = 0.10
W_LYRICS = 0.075
W_TOPICS = 0.075
KEY_BONUS = 0.05  # скидка к дистанции гармонии за совпадение тональности
KEY_CONF_GATE = 0.7  # минимальная mode_conf обоих треков для бонуса
ARTIST_SHRINKAGE = 3.0
MIN_V2_TRACKS = 2


def _parse(v: str | None) -> np.ndarray | None:
    if not v:
        return None
    try:
        return np.array(json.loads(v), dtype=float)
    except (ValueError, TypeError):
        return None


def _parse_embedding(v: str | None) -> np.ndarray | None:
    """base64(float16[1280]) из AudioFeatures.embedding → np.float32."""
    if not v:
        return None
    try:
        raw = base64.b64decode(v)
        return np.frombuffer(raw, dtype=np.float16).astype(np.float32)
    except (ValueError, TypeError):
        return None


def _vec_cosine_dist(a: np.ndarray, b: np.ndarray) -> float | None:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return None
    return float(1.0 - float(a @ b) / (na * nb))


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
    # 26 mfcc + 12 chroma + 7 contrast + 3 rhythm + 5 macro = 53
    groups: dict[str, dict[str, np.ndarray]] = {
        "timbre": dict(zip(ids, scaled[:, 0:33])),
        "harmony": dict(zip(ids, scaled[:, 33:45])),
        "rhythm": dict(zip(ids, scaled[:, 45:48])),
        "macro": dict(zip(ids, scaled[:, 48:53])),
    }
    return groups, usable


GROUP_LABELS = {
    "embedding": "по нейро-тембру",
    "timbre": "по тембру",
    "rhythm": "по ритму",
    "harmony": "по гармонии",
    "macro": "по характеру",
    "moods": "по настроению",
    "instruments": "по инструментам",
    "genre": "по жанру",
    "lyrics": "по тексту",
    "topics": "по темам",
}

# размерности векторных групп (для нормализации масштаба L2-расстояний);
# timbre = mfcc (26) + contrast (7), embedding — косинус, dim не важна
GROUP_DIMS = {"timbre": 33, "harmony": 12, "rhythm": 3, "macro": 5}


def _parse_tags(tags_json: str | None) -> dict:
    """Разбор Essentia tags json.

    Жанры берутся из распределения стилей (топ-20), при отсутствии —
    из старого списка топ-3. Также: инструменты и сырые moodtheme-теги.
    """
    if not tags_json:
        return {}
    try:
        data = json.loads(tags_json)
    except ValueError:
        return {}
    styles = {
        str(name): float(score)
        for name, score in (data.get("styles") or {}).items()
    }
    genres = (
        styles
        if styles
        else {g["name"]: float(g.get("score", 0.0)) for g in data.get("genres", [])}
    )
    instruments = {
        g["name"]: float(g.get("score", 0.0)) for g in data.get("instruments", [])
    }
    moodtags = {
        str(name): float(score)
        for name, score in (data.get("moodtags") or {}).items()
    }
    return {
        "genres": genres,
        "instruments": instruments,
        "moodtags": moodtags,
    }


def _cosine_dist(
    a: dict[str, float] | None, b: dict[str, float] | None
) -> float | None:
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
    dict[str, dict[str, float]],
]:
    """Теговые и текстовые данные треков.

    Возвращает (genres, instruments, topics, tfidf, moodtags):
    genres/instruments/topics/moodtags — {track_id: вектор-словарь};
    tfidf — {track_id: нормированный разреженный вектор текста}.
    """
    genres: dict[str, dict[str, float]] = {}
    instruments: dict[str, dict[str, float]] = {}
    moodtags: dict[str, dict[str, float]] = {}
    topics: dict[str, dict[str, float]] = {}
    texts_by_lang: dict[str, dict[str, str]] = {}
    id_set = set(ids)
    for f in session.exec(
        select(AudioFeatures.track_id, AudioFeatures.tags).where(  # type: ignore[arg-type]
            AudioFeatures.track_id.in_(id_set)  # type: ignore[union-attr]
        )
    ).all():
        parsed = _parse_tags(f[1])
        if parsed.get("genres"):
            genres[f[0]] = parsed["genres"]
        if parsed.get("instruments"):
            instruments[f[0]] = parsed["instruments"]
        if parsed.get("moodtags"):
            moodtags[f[0]] = parsed["moodtags"]
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
    return genres, instruments, topics, tfidf, moodtags


def _tfidf_dist(tfidf: dict[str, object], a: str, b: str) -> float | None:
    """Косинусное расстояние текстов (только одинаковый корпус = язык)."""
    va, vb = tfidf.get(a), tfidf.get(b)
    if va is None or vb is None or va.shape != vb.shape:
        return None
    return float(1.0 - va.multiply(vb).sum())


def _essentia_tags_vec(tags_json: str) -> dict[str, any]:
    """Parse Essentia tags JSON and return a dict with genre, instrument, mood, vocal vectors."""
    if not tags_json:
        return {"genres": {}, "instruments": {}, "moods": {}, "vocal": 0.0}
    try:
        data = json.loads(tags_json)
    except ValueError:
        return {"genres": {}, "instruments": {}, "moods": {}, "vocal": 0.0}
    genres = {g["name"]: float(g.get("score", 0.0)) for g in data.get("genres", [])}
    instruments = {
        g["name"]: float(g.get("score", 0.0)) for g in data.get("instruments", [])
    }
    moods = data.get("moods", {})
    mood_vec = {k: float(moods.get(k, 0.0)) for k in MOOD_COLS}
    vocal = float(data.get("vocal_ratio", 0.0))
    return {"genres": genres, "instruments": instruments, "moods": mood_vec, "vocal": vocal}


def _essentia_cosine(a: dict[str, float], b: dict[str, float]) -> float | None:
    if not a or not b:
        return None
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0.0 or nb == 0.0:
        return None
    return 1.0 - dot / (na * nb)


def _essentia_similarity(t1: dict[str, any], t2: dict[str, any]) -> float:
    """Return a combined similarity score 0..1 (higher = more similar)."""
    # genre cosine (higher = more similar); we invert distance to similarity
    g_dist = _essentia_cosine(t1["genres"], t2["genres"])
    g_sim = 1.0 - g_dist if g_dist is not None else 0.0

    # instrument cosine
    i_dist = _essentia_cosine(t1["instruments"], t2["instruments"])
    i_sim = 1.0 - i_dist if i_dist is not None else 0.0

    # mood cosine (8-dim)
    m_dist = _essentia_cosine(t1["moods"], t2["moods"])
    m_sim = 1.0 - m_dist if m_dist is not None else 0.0

    # vocal ratio proximity: 1 - |v1-v2|
    v_diff = abs(t1["vocal"] - t2["vocal"])
    v_sim = 1.0 - v_diff

    # weights (sum to 1)
    w_g, w_i, w_m, w_v = 0.30, 0.15, 0.30, 0.25
    total = w_g * g_sim + w_i * i_sim + w_m * m_sim + w_v * v_sim
    # normalise by sum of weights (they already sum to 1)
    return round(total, 3)


def similar_tracks_essentia(
    track_id: str, offset: int = 0, limit: int = 6
) -> tuple[list[dict], int] | None:
    """Find similar tracks using Essentia tags (genres, instruments, moods, vocal_ratio).

    Returns (results, total) where results is the paginated slice.
    None — not enough data.
    """
    with Session(engine) as session:
        features = session.exec(
            select(AudioFeatures).where(AudioFeatures.source == "audio")
        ).all()
        tags_map: dict[str, str] = {}
        for f in features:
            tags_map[f.track_id] = f.tags or ""

        if track_id not in tags_map:
            return None

        t1 = _essentia_tags_vec(tags_map[track_id])
        if not any(t1["genres"]) and not any(t1["instruments"]):
            return None

        scored: list[tuple[float, AudioFeatures]] = []
        for f in features:
            if f.track_id == track_id:
                continue
            t2 = _essentia_tags_vec(f.tags or "")
            sim = _essentia_similarity(t1, t2)
            scored.append((sim, f))
        scored.sort(key=lambda x: x[0], reverse=True)

        total = len(scored)
        result = []
        for sim, f in scored[offset : offset + limit]:
            t = session.get(Track, f.track_id)
            if t is None:
                continue
            dist = round(1.0 - sim, 3)
            result.append(
                {
                    "track": t,
                    "distance": dist,
                    "match": "essentia",
                }
            )
        return result, total


def similar_tracks_v2(
    track_id: str, offset: int = 0, limit: int = 6
) -> tuple[list[dict], int] | None:
    """Взвешенная похожесть по группам фич + теги/тексты/темы.

    Возвращает (страница результатов, всего), как similar_tracks_essentia.
    None — недостаточно v2-треков. Группы участвуют в скоре пары только
    если данные есть у обоих треков; общий скор нормируется на сумму
    весов доступных групп (треки без текстов не штрафуются).
    """
    weights = {
        "embedding": W_EMBEDDING,
        "timbre": W_TIMBRE,
        "rhythm": W_RHYTHM,
        "harmony": W_HARMONY,
        "macro": W_MACRO,
        "moods": W_MOODS,
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
        genres, instruments, topics, tfidf, moodtags = _load_semantic(session, ids)

        # нейро-эмбеддинги, настроения и тональности из колонок фич
        embedding_map = {
            f.track_id: _parse_embedding(f.embedding) for f in usable
        }
        moods_map = {
            f.track_id: {c: float(getattr(f, c)) for c in MOOD_COLS}
            for f in usable
        }
        keys_map = {
            f.track_id: (f.key or "", float(f.mode_conf or 0.0))
            for f in usable
        }

        def pair_distance(other_id: str) -> tuple[float | None, str]:
            """(общий скор, ближайшая группа); None — нет общих групп."""
            per_group: dict[str, float] = {}
            for g, dim in GROUP_DIMS.items():
                # L2 по стандартизованным фичам, нормированный на размерность,
                # чтобы масштаб был сопоставим с косинусными расстояниями 0..2
                d = float(np.linalg.norm(groups[g][track_id] - groups[g][other_id]))
                per_group[g] = d / math.sqrt(dim)
            emb_a = embedding_map.get(track_id)
            emb_b = embedding_map.get(other_id)
            if emb_a is not None and emb_b is not None:
                d = _vec_cosine_dist(emb_a, emb_b)
                if d is not None:
                    per_group["embedding"] = d
            mood_d = _cosine_dist(
                moods_map.get(track_id), moods_map.get(other_id)
            )
            tag_d = _cosine_dist(
                moodtags.get(track_id), moodtags.get(other_id)  # type: ignore[arg-type]
            )
            mood_ds = [d for d in (mood_d, tag_d) if d is not None]
            if mood_ds:
                per_group["moods"] = float(np.mean(mood_ds))
            for g, vecs in (
                ("instruments", instruments),
                ("genre", genres),
                ("topics", topics),
            ):
                d = _cosine_dist(vecs.get(track_id), vecs.get(other_id))
                if d is not None:
                    per_group[g] = d
            d = _tfidf_dist(tfidf, track_id, other_id)
            if d is not None:
                per_group["lyrics"] = d
            # бонус за совпадение тональности (обе уверенны в ней)
            key_a = keys_map.get(track_id)
            key_b = keys_map.get(other_id)
            if (
                key_a
                and key_b
                and key_a[0]
                and key_a[0] == key_b[0]
                and key_a[1] >= KEY_CONF_GATE
                and key_b[1] >= KEY_CONF_GATE
                and "harmony" in per_group
            ):
                per_group["harmony"] = max(
                    0.0, per_group["harmony"] - KEY_BONUS
                )
            if not per_group:
                return None, ""
            w_sum = sum(weights[g] for g in per_group)
            total = sum(weights[g] * per_group[g] for g in per_group) / w_sum
            closest = min(per_group, key=lambda g: per_group[g])
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
        for total, other, label in scored[offset : offset + limit]:
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
        return result, len(scored)


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


def similar_tracks(
    track_id: str, offset: int = 0, limit: int = 6
) -> tuple[list[dict], int] | None:
    """Простая похожесть по числовым фичам (запасной вариант без v2).

    Возвращает (страница результатов, всего), как similar_tracks_essentia.
    None — недостаточно данных.
    """
    with Session(engine) as session:
        features = session.exec(select(AudioFeatures)).all()
        if len(features) < 2:
            return None
        selected = session.get(AudioFeatures, track_id)
        if selected is None:
            return None
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
            return None
        k = min(offset + limit + 1, len(pool))
        nn = NearestNeighbors(n_neighbors=k, metric="euclidean")
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
                    "match": "",
                }
            )
        return result[offset : offset + limit], len(pool) - 1


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
