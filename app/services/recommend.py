import time

import httpx
import numpy as np
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.models import AudioFeatures, Cluster, Track

MB_API = "https://musicbrainz.org/ws/2/artist"
MIN_INTERVAL = 1.1

MOOD_TAGS = {
    "Весёлое": ["pop", "dance"],
    "Энергичное": ["electronic", "dance"],
    "Спокойное": ["ambient", "chillout"],
    "Меланхоличное": ["indie", "post-rock"],
}

_last_call = 0.0
_cache: dict[str, tuple[float, list[dict]]] = {}
CACHE_TTL = 86400.0


MOOD_COLS = ["mood_happy", "mood_sad", "mood_relaxed", "mood_aggressive"]


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
