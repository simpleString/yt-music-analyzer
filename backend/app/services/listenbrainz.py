"""ListenBrainz global similar artists (Labs API, no key needed).

https://labs.api.listenbrainz.org/similar-artists/json — collaboratively
filtered over anonymized listens of all ListenBrainz users. Requires the
MusicBrainz ID of the seed artist: taken from the MbArtist cache (the
"mb-genres" prefill job stores it) or resolved on demand through the
MusicBrainz search. Results are cached in the lb_similar table.
"""

import json
from datetime import datetime, timedelta

import httpx
from sqlmodel import Session

from app.config import settings
from app.db import engine
from app.models import LbSimilar
from app.services import musicbrainz as mb_svc

LB_LABS = "https://labs.api.listenbrainz.org/similar-artists/json"
ALGORITHM = (
    "session_based_days_7500_session_300_contribution_5_"
    "threshold_10_limit_100_filter_True_skip_30"
)
# how many similar artists to keep per request (API returns up to 100)
MAX_PER_ARTIST = 25


def _is_fresh(fetched_at: datetime) -> bool:
    return fetched_at >= datetime.utcnow() - timedelta(
        days=settings.lb_cache_days
    )


def _fetch(mbid: str) -> list[dict] | None:
    """Live LB query; None on network error (not cached)."""
    try:
        resp = httpx.get(
            LB_LABS,
            params={"artist_mbids": mbid, "algorithm": ALGORITHM},
            timeout=20,
            headers={"User-Agent": settings.mb_user_agent},
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    items: list[dict] = []
    for it in data if isinstance(data, list) else []:
        if it.get("reference_mbid") != mbid:
            continue
        name = it.get("name", "")
        if not name:
            continue
        items.append(
            {
                "name": name,
                "mbid": it.get("artist_mbid", ""),
                "comment": it.get("comment", "") or "",
                "type": it.get("type", "") or "",
                "score": int(it.get("score") or 0),
            }
        )
        if len(items) >= MAX_PER_ARTIST:
            break
    return items


def _cached(mbid: str) -> list[dict] | None:
    with Session(engine) as session:
        row = session.get(LbSimilar, mbid)
    if row is None or not _is_fresh(row.fetched_at):
        return None
    try:
        data = json.loads(row.payload or "[]")
        return data if isinstance(data, list) else None
    except ValueError:
        return None


def _save(mbid: str, items: list[dict]) -> None:
    with Session(engine) as session:
        session.merge(
            LbSimilar(
                mbid=mbid,
                payload=json.dumps(items, ensure_ascii=False),
                fetched_at=datetime.utcnow(),
            )
        )
        session.commit()


def similar_for_name(name: str, limit: int = 12) -> tuple[list[dict], str]:
    """Similar artists for a seed artist name.

    Returns (artists, error); artists is [] both on failure and when the
    seed artist cannot be resolved — the error string tells those apart.
    """
    if not settings.lb_enabled:
        return [], "ListenBrainz disabled in settings (LB_ENABLED=false)"
    name = (name or "").strip()
    if not name:
        return [], ""
    info = mb_svc.artist_info(name)
    mbid = (info or {}).get("mbid", "")
    if not mbid:
        # unknown to MusicBrainz — no global mapping possible
        return [], ""
    cached = _cached(mbid)
    if cached is None:
        cached = _fetch(mbid)
        if cached is None:
            return [], "ListenBrainz unavailable"
        _save(mbid, cached)
    return cached[:limit], ""
