"""Listening-session analytics: co-occurrence and next-track (Markov).

Sessions are built from the Listen table: consecutive music listens with
a gap above SESSION_GAP_MIN minutes start a new session. Two artifacts:

- cooccur: how many sessions two tracks share (ordered pairs track_a < track_b)
- next_track: transitions prev -> next within a session, counting only
  listens with a gap of at most MARKOV_GAP_MIN minutes

Both are rebuilt by the background job "sessions" (also auto-run after
each import) and queried by the recommendation endpoints. Recency decay
is applied at query time (score halves every COOCCUR_HALF_LIFE_DAYS).

24/7 radio streams can produce a single giant "session": co-occurrence
pairs are skipped for sessions with more than SESSION_MAX_TRACKS unique
tracks (pair counting is quadratic), transitions are still kept.
"""

import threading
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import func, text
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.models import Cooccur, NextTrack, Track
from app.services import jobs

_INSERT = 2000


def _iter_sessions(gap_min: int) -> list[list[tuple[str, datetime]]]:
    """Music listens ordered by time, split into sessions.

    A session is a list of (track_id, listened_at) with consecutive gaps
    of at most gap_min minutes. Raw SQL returns the stored DATETIME
    strings — parsed back here.
    """
    with Session(engine) as session:
        rows = session.execute(
            text(
                "SELECT l.track_id, l.listened_at "
                "FROM listen l JOIN track t ON t.video_id = l.track_id "
                "WHERE t.is_music = 1 ORDER BY l.listened_at"
            )
        ).all()
    gap = timedelta(minutes=gap_min)
    sessions: list[list[tuple[str, datetime]]] = []
    current: list[tuple[str, datetime]] = []
    prev_at: datetime | None = None
    for raw_id, raw_at in rows:
        at = raw_at if isinstance(raw_at, datetime) else datetime.fromisoformat(str(raw_at))
        if prev_at is not None and at - prev_at > gap:
            sessions.append(current)
            current = []
        current.append((str(raw_id), at))
        prev_at = at
    if current:
        sessions.append(current)
    return sessions


def _bulk_insert(session: Session, sql: str, rows: list[dict]) -> None:
    for i in range(0, len(rows), _INSERT):
        session.execute(text(sql), rows[i : i + _INSERT])
        session.commit()


def run_sessions(stop: threading.Event | None = None) -> None:
    """Rebuild cooccur + next_track tables from the listen history."""
    try:
        if not jobs.start_job("sessions"):
            return
        stop = stop if stop is not None else threading.Event()

        sessions = _iter_sessions(settings.session_gap_min)
        if jobs.should_stop("sessions", stop):
            jobs.stop_job("sessions")
            return

        max_tracks = settings.session_max_tracks
        pair_cnt: Counter[tuple[str, str]] = Counter()
        pair_last: dict[tuple[str, str], datetime] = {}
        trans_cnt: Counter[tuple[str, str]] = Counter()
        trans_last: dict[tuple[str, str], datetime] = {}
        skipped_big = 0

        markov_gap = timedelta(minutes=settings.markov_gap_min)
        for sess in sessions:
            last_at = sess[-1][1]
            # co-occurrence: unique track pairs per session
            ids = sorted({t for t, _ in sess})
            if len(ids) > max_tracks:
                skipped_big += 1
            else:
                for i in range(len(ids)):
                    for j in range(i + 1, len(ids)):
                        key = (ids[i], ids[j])
                        pair_cnt[key] += 1
                        prev = pair_last.get(key)
                        if prev is None or last_at > prev:
                            pair_last[key] = last_at
            # Markov: consecutive transitions with a small gap
            for (cur, at1), (nxt_id, at2) in zip(sess, sess[1:]):
                if cur == nxt_id or at2 - at1 > markov_gap:
                    continue
                key = (cur, nxt_id)
                trans_cnt[key] += 1
                prev = trans_last.get(key)
                if prev is None or last_at > prev:
                    trans_last[key] = last_at

        total = len(pair_cnt) + len(trans_cnt) or 1
        done = 0

        with Session(engine) as session:
            session.execute(text("DELETE FROM cooccur"))
            session.execute(text("DELETE FROM next_track"))
            session.commit()

            _bulk_insert(
                session,
                "INSERT INTO cooccur (track_a, track_b, cnt, last_at) "
                "VALUES (:a, :b, :cnt, :at)",
                [
                    {"a": a, "b": b, "cnt": cnt, "at": pair_last[(a, b)]}
                    for (a, b), cnt in pair_cnt.items()
                ],
            )
            done += len(pair_cnt)
            jobs.progress("sessions", done, total, "co-occurrence written")

            _bulk_insert(
                session,
                "INSERT INTO next_track (cur, nxt, cnt, last_at) "
                "VALUES (:cur, :nxt, :cnt, :at)",
                [
                    {"cur": cur, "nxt": nxt, "cnt": cnt, "at": trans_last[(cur, nxt)]}
                    for (cur, nxt), cnt in trans_cnt.items()
                ],
            )
            done += len(trans_cnt)

        detail = (
            f"{len(sessions)} sessions, {len(pair_cnt)} co-occur pairs, "
            f"{len(trans_cnt)} transitions"
        )
        if skipped_big:
            detail += f"; pairs skipped in {skipped_big} oversized sessions"
        jobs.finish_job("sessions", detail=detail)
    except Exception as exc:  # noqa: BLE001
        jobs.fail_job("sessions", f"{type(exc).__name__}: {exc}")
        raise


def rebuild_in_background() -> None:
    """Fire-and-forget rebuild (used after import); skipped if running."""
    threading.Thread(
        target=run_sessions, daemon=True, name="stage-sessions"
    ).start()


def _decay(last_at: datetime | None, now: datetime) -> float:
    """Recency multiplier: halves every cooccur_half_life_days."""
    if last_at is None:
        return 0.5
    days = max((now - last_at).days, 0)
    return 0.5 ** (days / float(settings.cooccur_half_life_days))


def co_listened(track_id: str, limit: int = 10) -> dict | None:
    """Tracks sharing listening sessions with the seed track.

    Returns {"items": [...], "total": n}; None — tables never built.
    """
    with Session(engine) as session:
        if session.get(Track, track_id) is None:
            return {"items": [], "total": 0}
        if not session.scalar(select(func.count()).select_from(Cooccur)):
            return None
        now = datetime.utcnow()
        rows = session.execute(
            text(
                "SELECT CASE WHEN track_a = :t THEN track_b ELSE track_a END, "
                "cnt, last_at FROM cooccur WHERE track_a = :t OR track_b = :t"
            ),
            {"t": track_id},
        ).all()
        scored = []
        for other, cnt, raw_at in rows:
            last_at = raw_at if isinstance(raw_at, datetime) else datetime.fromisoformat(str(raw_at))
            score = cnt * _decay(last_at, now)
            scored.append((score, cnt, other, last_at))
        scored.sort(key=lambda x: x[0], reverse=True)
        items = []
        for score, cnt, other, last_at in scored[:limit]:
            t = session.get(Track, other)
            if t is None:
                continue
            items.append(
                {
                    "track": _track_brief(t),
                    "cnt": cnt,
                    "last_listen": last_at.isoformat() if last_at else None,
                    "score": round(score, 3),
                }
            )
        return {"items": items, "total": len(scored)}


def next_tracks(track_id: str, limit: int = 10) -> dict | None:
    """What usually comes after the seed track (Markov over sessions).

    Returns {"items": [...], "total": n}; None — tables never built.
    """
    with Session(engine) as session:
        if session.get(Track, track_id) is None:
            return {"items": [], "total": 0}
        if not session.scalar(select(func.count()).select_from(NextTrack)):
            return None
        now = datetime.utcnow()
        rows = session.execute(
            text("SELECT nxt, cnt, last_at FROM next_track WHERE cur = :t"),
            {"t": track_id},
        ).all()
        if not rows:
            return {"items": [], "total": 0}
        total_from = sum(r[1] for r in rows) + len(rows)  # +1 smoothing
        scored = []
        for nxt, cnt, raw_at in rows:
            last_at = raw_at if isinstance(raw_at, datetime) else datetime.fromisoformat(str(raw_at))
            p = (cnt + 1) / total_from
            score = p * _decay(last_at, now)
            scored.append((score, p, cnt, nxt, last_at))
        scored.sort(key=lambda x: x[0], reverse=True)
        items = []
        for score, p, cnt, nxt, last_at in scored[:limit]:
            t = session.get(Track, nxt)
            if t is None:
                continue
            items.append(
                {
                    "track": _track_brief(t),
                    "cnt": cnt,
                    "p": round(p, 3),
                    "last_listen": last_at.isoformat() if last_at else None,
                    "score": round(score, 3),
                }
            )
        return {"items": items, "total": len(scored)}


def _track_brief(t: Track) -> dict:
    return {
        "video_id": t.video_id,
        "title": t.title,
        "channel": t.channel,
        "artist": t.artist_canonical or t.channel,
        "play_count": t.play_count,
    }
