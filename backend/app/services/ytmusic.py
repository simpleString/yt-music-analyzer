"""YouTube Music (unofficial API): extra track metadata + native "radio" similar tracks.

No API key and no authentication needed — only public browsing endpoints.
The watch playlist (what YT Music queues when you press "Start radio") is a
single request that returns the seed track with album/year/artists (metadata)
plus the recommended similar tracks.
"""

import json
import threading
import time
from datetime import datetime, timedelta

from sqlmodel import Session

from app.config import settings
from app.db import engine
from app.models import YtmMeta, YtmSimilar

_client = None
# one client + one throttle clock for all threads
_lock = threading.Lock()
_last_call = 0.0

# rows with no data (track not in YT Music catalog / transient error) are
# retried sooner than successful ones
EMPTY_TTL_DAYS = 1


def enabled() -> bool:
    return settings.ytm_enabled


def _get_client():
    global _client
    with _lock:
        if _client is None:
            from ytmusicapi import YTMusic

            _client = YTMusic(language=settings.ytm_language or None)
        return _client


def _throttle() -> None:
    global _last_call
    with _lock:
        wait = settings.ytm_throttle - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _parse_length(value) -> float | None:
    """YT Music length formats: '3:07', '1:03:07' or plain seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    parts = str(value).strip().split(":")
    if not all(p.isdigit() for p in parts) or not 1 <= len(parts) <= 3:
        return None
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + int(p)
    return float(seconds)


def _norm_track(item: dict) -> dict | None:
    vid = item.get("videoId")
    if not vid:
        return None
    artists = [
        a.get("name", "") for a in (item.get("artists") or []) if a.get("name")
    ]
    thumbs = item.get("thumbnail") or []
    thumb = ""
    if thumbs:
        best = max(thumbs, key=lambda t: t.get("width", 0) or 0)
        thumb = best.get("url", "")
    return {
        "video_id": vid,
        "title": item.get("title", ""),
        "artist": ", ".join(artists),
        "album": (item.get("album") or {}).get("name", ""),
        "year": str(item.get("year") or ""),
        "thumbnail": thumb,
        "duration": _parse_length(item.get("length")),
    }


def _fetch(video_id: str, title: str) -> tuple[dict, list[dict]] | None:
    """One radio request: (seed meta, similar tracks). None — request failed."""
    try:
        client = _get_client()
        _throttle()
        res = client.get_watch_playlist(
            videoId=video_id, radio=True, limit=settings.ytm_limit
        )
    except Exception:
        return None
    normed: list[dict] = []
    seen: set[str] = set()
    for item in res.get("tracks") or []:
        t = _norm_track(item)
        if t is not None and t["video_id"] not in seen:
            seen.add(t["video_id"])
            normed.append(t)
    if not normed:
        return None
    folded = title.casefold().strip()
    seed = next((t for t in normed if t["video_id"] == video_id), None)
    if seed is None and folded:
        seed = next((t for t in normed if t["title"].casefold().strip() == folded), None)
    similar = [t for t in normed if t is not seed]
    meta = {}
    if seed is not None:
        meta = {
            "album": seed["album"],
            "album_id": "",
            "year": seed["year"],
            "artists": [
                {"name": a} for a in seed["artist"].split(", ") if a
            ],
            "thumbnail": seed["thumbnail"],
        }
    return meta, similar


def _is_fresh(fetched_at: datetime, payload: str) -> bool:
    days = settings.ytm_cache_days if payload and payload != "[]" else EMPTY_TTL_DAYS
    return fetched_at >= datetime.utcnow() - timedelta(days=days)


def _save(video_id: str, meta: dict, similar: list[dict]) -> None:
    now = datetime.utcnow()
    with Session(engine) as session:
        if meta.get("album") or meta.get("year") or meta.get("artists"):
            session.merge(
                YtmMeta(
                    track_id=video_id,
                    album=meta.get("album", ""),
                    album_id=meta.get("album_id", ""),
                    year=meta.get("year", ""),
                    artists=json.dumps(meta.get("artists", []), ensure_ascii=False),
                    thumbnails=json.dumps(
                        ([{"url": meta["thumbnail"]}] if meta.get("thumbnail") else []),
                        ensure_ascii=False,
                    ),
                    fetched_at=now,
                )
            )
        session.merge(
            YtmSimilar(
                seed_video_id=video_id,
                payload=json.dumps(similar, ensure_ascii=False),
                fetched_at=now,
            )
        )
        session.commit()


def _load_meta(video_id: str) -> dict:
    with Session(engine) as session:
        row = session.get(YtmMeta, video_id)
        if row is None:
            return {}
        try:
            artists = json.loads(row.artists or "[]")
            thumbs = json.loads(row.thumbnails or "[]")
        except ValueError:
            artists, thumbs = [], []
        thumbnail = thumbs[0].get("url", "") if thumbs else ""
        return {
            "album": row.album,
            "year": row.year,
            "artists": artists,
            "thumbnail": thumbnail,
        }


def _meta_fresh(video_id: str) -> bool:
    with Session(engine) as session:
        row = session.get(YtmMeta, video_id)
        if row is None:
            return False
        payload = row.artists if (row.album or row.year) else ""
        return _is_fresh(row.fetched_at, payload)


def similar(video_id: str, title: str = "") -> list[dict]:
    """YouTube-native similar tracks, cached in ytm_similar. [] — unavailable."""
    if not settings.ytm_enabled:
        return []
    with Session(engine) as session:
        row = session.get(YtmSimilar, video_id)
        if row is not None and _is_fresh(row.fetched_at, row.payload):
            try:
                return json.loads(row.payload or "[]")
            except ValueError:
                pass
    data = _fetch(video_id, title)
    if data is None:
        return []
    meta, items = data
    _save(video_id, meta, items)
    return items


def meta_for_track(video_id: str, title: str = "") -> dict:
    """Album/year/artists for the track card; fetches (and caches) on demand."""
    if not settings.ytm_enabled:
        return {}
    if _meta_fresh(video_id):
        return _load_meta(video_id)
    items = similar(video_id, title)  # populates ytm_meta as a side effect
    if _meta_fresh(video_id):
        return _load_meta(video_id)
    # empty result: remember the miss so meta_for_track stops refetching
    if not items:
        with Session(engine) as session:
            existing = session.get(YtmMeta, video_id)
            if existing is None:
                session.merge(YtmMeta(track_id=video_id, fetched_at=datetime.utcnow()))
                session.commit()
    return {}
