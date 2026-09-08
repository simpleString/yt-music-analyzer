"""MusicBrainz artist info: genres, tags, country, life span.

WS/2 endpoints, no API key; the only requirements are a descriptive
User-Agent and <= 1 request/second (see https://musicbrainz.org/doc/MusicBrainz_API).
Results are cached in the mb_artist table keyed by the canonical artist
name; "not found" misses are cached with a shorter TTL and network
errors are not cached at all (same policy as lyrics.py).
"""

import difflib
import json
import threading
import time
from datetime import datetime, timedelta

import httpx
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.models import MbArtist, Track

MB_API = "https://musicbrainz.org/ws/2"
MIN_INTERVAL = 1.1
# search score below this means "probably a different artist" — a mismatch
# would put someone else's genres on the artist page
MIN_SCORE = 75
EMPTY_TTL_DAYS = 3
# consecutive network errors before the prefill job gives up
MAX_NET_ERRORS = 10

# shared with recommend.py so the two modules never exceed 1 r/s together
_last_call = 0.0
_throttle_lock = threading.Lock()


def _throttle() -> None:
    global _last_call
    with _throttle_lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _is_fresh(fetched_at: datetime, mbid: str) -> bool:
    days = settings.mb_cache_days if mbid else EMPTY_TTL_DAYS
    return fetched_at >= datetime.utcnow() - timedelta(days=days)


def _row_payload(row: MbArtist) -> dict | None:
    """Cached info dict; None for "not found" miss rows."""
    if not row.mbid:
        return None
    try:
        payload = json.loads(row.payload or "{}")
    except ValueError:
        return None
    if not isinstance(payload, dict) or not payload:
        return None
    payload["mbid"] = row.mbid
    return payload


def _save(name: str, mbid: str, payload: dict) -> None:
    with Session(engine) as session:
        session.merge(
            MbArtist(
                name=name,
                mbid=mbid,
                payload=json.dumps(payload, ensure_ascii=False),
                fetched_at=datetime.utcnow(),
            )
        )
        session.commit()


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _name_matches(query: str, artist: dict) -> bool:
    """The search query must look like this artist: equal/similar to the
    name or one of its aliases (MB aliases cover Cyrillic ↔ latin).
    Guards against attaching someone else's genres (score alone is not
    enough: "OM." used to match "Om Unit" with a high score)."""
    q = _norm(query)
    if not q:
        return False
    names = [artist.get("name", "")]
    names += [a.get("name", "") for a in artist.get("aliases") or []]
    for n in names:
        c = _norm(n)
        if not c:
            continue
        if q == c:
            return True
        if difflib.SequenceMatcher(None, q, c).ratio() >= 0.8:
            return True
        if len(q) >= 4 and (q in c or c in q):
            return True
    return False


def _get_json(client: httpx.Client, path: str, params: dict) -> dict:
    """GET with one retry on a transient 503 (MB recommends waiting ~1s
    after rate limiting)."""
    resp = None
    for attempt in (1, 2):
        _throttle()
        resp = client.get(f"{MB_API}{path}", params=params)
        if resp.status_code != 503 or attempt == 2:
            break
        time.sleep(1.2)
    resp.raise_for_status()
    return resp.json()


def _search_artist(client: httpx.Client, name: str) -> dict | None:
    """Best matching artist (mbid + name) or None. MB search covers aliases,
    so Cyrillic/latin name variants are found too."""
    for query in (f'artist:"{name}"', name):
        artists = (
            _get_json(
                client, "/artist", {"query": query, "fmt": "json", "limit": 5}
            ).get("artists")
            or []
        )
        for artist in sorted(artists, key=lambda a: -a.get("score", 0)):
            if (
                artist.get("score", 0) >= MIN_SCORE
                and artist.get("id")
                and _name_matches(name, artist)
            ):
                return {"id": artist["id"], "name": artist.get("name", "")}
    return None


def _lookup_artist(client: httpx.Client, mbid: str) -> dict:
    """Artist details with curated genres and folksonomy tags."""
    a = _get_json(client, f"/artist/{mbid}", {"inc": "genres+tags", "fmt": "json"})
    life = a.get("life-span") or {}

    def tag_list(items) -> list[dict]:
        return sorted(
            (
                {"name": t.get("name", ""), "count": int(t.get("count") or 0)}
                for t in items or []
                if t.get("name")
            ),
            key=lambda t: -t["count"],
        )

    return {
        "name": a.get("name", ""),
        "disambiguation": a.get("disambiguation", "") or "",
        "country": a.get("country", "") or "",
        "area": (a.get("area") or {}).get("name", "") or "",
        "type": a.get("type", "") or "",
        "life_span": {
            "begin": life.get("begin", "") or "",
            "end": life.get("end", "") or "",
            "ended": bool(life.get("ended")),
        },
        "genres": tag_list(a.get("genres")),
        "tags": tag_list(a.get("tags")),
    }


def artist_info(name: str) -> dict | None:
    """Cached MusicBrainz info for the artist page. None — disabled,
    not found (cached miss) or network error."""
    name = (name or "").strip()
    if not name or not settings.mb_enabled:
        return None
    with Session(engine) as session:
        row = session.get(MbArtist, name)
        if row is not None and _is_fresh(row.fetched_at, row.mbid):
            return _row_payload(row)
    try:
        with httpx.Client(
            timeout=25, headers={"User-Agent": settings.mb_user_agent}
        ) as client:
            hit = _search_artist(client, name)
            if hit is None:
                _save(name, "", {})
                return None
            data = _lookup_artist(client, hit["id"])
    except (httpx.HTTPError, ValueError):
        return None
    _save(name, hit["id"], data)
    return {**data, "mbid": hit["id"]}


def cached_genre(name: str) -> str:
    """Top cached genre for the artists list (no network)."""
    with Session(engine) as session:
        row = session.get(MbArtist, name)
    if row is None or not row.payload:
        return ""
    try:
        genres = json.loads(row.payload).get("genres") or []
    except ValueError:
        return ""
    return genres[0].get("name", "") if genres else ""


def fresh_names() -> set[str]:
    """Artists with a not-yet-stale cache row (prefill skip list)."""
    with Session(engine) as session:
        rows = session.exec(select(MbArtist)).all()
    return {
        row.name
        for row in rows
        if _is_fresh(row.fetched_at, row.mbid)
    }


def run_mb_genres(stop=None) -> None:
    from app.services import jobs

    if not jobs.start_job("mb-genres"):
        return
    stop = stop if stop is not None else threading.Event()
    try:
        if not settings.mb_enabled:
            jobs.finish_job("mb-genres", "MusicBrainz disabled in settings")
            return
        from sqlalchemy import func

        artist_expr = func.coalesce(
            func.nullif(Track.artist_canonical, ""), Track.channel
        )
        with Session(engine) as session:
            rows = session.exec(
                select(
                    artist_expr.label("artist"),
                    func.sum(Track.play_count).label("plays"),
                )
                .where(
                    Track.is_music == True,  # noqa: E712
                    artist_expr != "",
                )
                .group_by(artist_expr)
                .order_by(func.sum(Track.play_count).desc())
            ).all()
        names = [r[0] for r in rows if r[0]]
        fresh = fresh_names()
        todo = [n for n in names if n not in fresh]
        if settings.mb_prefill_limit > 0:
            todo = todo[: settings.mb_prefill_limit]
        total = len(todo)
        jobs.progress(
            "mb-genres", 0, total,
            f"to fetch: {total} ({len(names) - total} cached)"
            if total
            else "all artists are already cached",
        )
        found = 0
        net_errors = 0
        with httpx.Client(
            timeout=25, headers={"User-Agent": settings.mb_user_agent}
        ) as client:
            for i, name in enumerate(todo):
                if jobs.should_stop("mb-genres", stop):
                    jobs.stop_job(
                        "mb-genres", detail=f"stopped; fetched {found} of {i}"
                    )
                    return
                try:
                    hit = _search_artist(client, name)
                    if hit is None:
                        _save(name, "", {})
                    else:
                        data = _lookup_artist(client, hit["id"])
                        _save(name, hit["id"], data)
                        found += 1
                except (httpx.HTTPError, ValueError):
                    # network outage — keep progress, abort soon
                    net_errors += 1
                    if net_errors >= MAX_NET_ERRORS:
                        jobs.fail_job(
                            "mb-genres",
                            "network unavailable (10 consecutive errors)",
                        )
                        return
                    continue
                net_errors = 0
                if (i + 1) % 10 == 0 or i + 1 == total:
                    jobs.progress(
                        "mb-genres",
                        i + 1,
                        total,
                        f"found {found} of {i + 1}; last: {name[:45]}",
                    )
        if jobs.should_stop("mb-genres", stop):
            jobs.stop_job(
                "mb-genres", detail=f"stopped; fetched {found} of {total}"
            )
            return
        jobs.finish_job(
            "mb-genres",
            f"found {found} artists out of {total} "
            f"({total - found} not found on MusicBrainz)",
        )
    except Exception as exc:  # noqa: BLE001
        from app.services import jobs as jobs_svc

        jobs_svc.fail_job("mb-genres", f"{type(exc).__name__}: {exc}")
        raise
