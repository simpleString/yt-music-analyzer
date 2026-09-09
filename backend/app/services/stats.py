import json
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, text
from sqlmodel import Session, select

from app.models import Listen, Track

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
AVG_UNKNOWN_SECONDS = 210.0

ARTIST_EXPR = "COALESCE(NULLIF(t.artist_canonical, ''), t.channel)"

MOODS = [
    "happy",
    "sad",
    "relaxed",
    "aggressive",
    "electronic",
    "acoustic",
    "party",
    "epic",
    "dark",
    "romantic",
    "atmospheric",
]

VOCAL_RATIO_FALLBACK = 0.5


def _music_listen_join(
    date_from: date | None = None, date_to: date | None = None
) -> tuple[str, dict]:
    sql = "FROM listen l JOIN track t ON t.video_id = l.track_id WHERE t.is_music = 1"
    params: dict = {}
    if date_from is not None:
        sql += " AND l.listened_at >= :dfrom"
        params["dfrom"] = datetime.combine(date_from, datetime.min.time())
    if date_to is not None:
        sql += " AND l.listened_at < :dto"
        params["dto"] = datetime.combine(date_to + timedelta(days=1), datetime.min.time())
    return sql, params


def totals(
    session: Session, date_from: date | None = None, date_to: date | None = None
) -> dict:
    join, params = _music_listen_join(date_from, date_to)
    period = date_from is not None or date_to is not None
    if period:
        music_ids = set()
    else:
        tracks_total = len(session.exec(select(Track.video_id)).all())  # type: ignore[arg-type]
        music = session.exec(
            select(Track.video_id).where(Track.is_music == True)  # noqa: E712
        ).all()
        music_ids = {v for v in music}
    listens_total = len(session.exec(select(Listen.id)).all())  # type: ignore[arg-type]
    music_listens = session.execute(
        text(f"SELECT COUNT(*), MIN(l.listened_at), MAX(l.listened_at) {join}"), params
    ).one()
    seconds = session.execute(
        text(
            "SELECT SUM(CASE WHEN t.duration IS NULL THEN :avg ELSE t.duration END) "
            + join
        ),
        {**params, "avg": AVG_UNKNOWN_SECONDS},
    ).scalar()
    analyzed = session.execute(text("SELECT COUNT(*) FROM audio_features")).scalar()
    period_tracks = (
        int(
            session.execute(
                text(f"SELECT COUNT(DISTINCT t.video_id) {join}"), params
            ).scalar()
            or 0
        )
        if period
        else None
    )
    return {
        "tracks_total": tracks_total if not period else period_tracks,
        "music_tracks": len(music_ids) if not period else period_tracks,
        "listens_total": listens_total,
        "music_listens": int(music_listens[0] or 0),
        "hours_est": round(float(seconds or 0) / 3600, 1),
        "first_listen": music_listens[1],
        "last_listen": music_listens[2],
        "analyzed": int(analyzed or 0),
    }


def artists(session: Session, limit: int = 20000) -> list[dict]:
    """All artists (canonical) with plays/track counts and last listen."""
    join, params = _music_listen_join()
    rows = session.execute(
        text(
            f"SELECT {ARTIST_EXPR} AS artist, COUNT(*) AS plays, "
            "COUNT(DISTINCT t.video_id) AS tracks, MAX(l.listened_at) AS last "
            + join
            + f" AND {ARTIST_EXPR} != '' GROUP BY artist ORDER BY plays DESC LIMIT :lim"
        ),
        {**params, "lim": limit},
    ).all()
    # representative video per artist (most played track) — used as the
    # artist image (YouTube thumbnail) in the artists list
    top_rows = session.execute(
        text(
            "SELECT artist, video_id FROM ("
            f" SELECT {ARTIST_EXPR} AS artist, t.video_id AS video_id, "
            "ROW_NUMBER() OVER ("
            f" PARTITION BY {ARTIST_EXPR} ORDER BY COUNT(*) DESC, t.video_id"
            ") AS rn "
            + join
            + f" AND {ARTIST_EXPR} != '' GROUP BY artist, t.video_id"
            ") WHERE rn = 1"
        ),
        params,
    ).all()
    top_video = {r[0]: r[1] for r in top_rows}
    return [
        {
            "channel": r[0],
            "plays": r[1],
            "tracks": r[2],
            "last_listen": r[3],
            "top_video_id": top_video.get(r[0], ""),
        }
        for r in rows
    ]


def artist_summary(
    session: Session,
    name: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict | None:
    """Header stats for the artist page (same canonical artist as artists())."""
    join, params = _music_listen_join(date_from, date_to)
    match = f"{ARTIST_EXPR} = :artist"
    row = session.execute(
        text(
            "SELECT COUNT(*), COUNT(DISTINCT t.video_id), "
            "MIN(l.listened_at), MAX(l.listened_at) "
            + join
            + f" AND {match}"
        ),
        {**params, "artist": name},
    ).one()
    if not row[0]:
        return None
    top = session.execute(
        text(
            "SELECT t.video_id, t.title, t.channel, COUNT(*) AS plays "
            + join
            + f" AND {match} "
            + "GROUP BY t.video_id ORDER BY plays DESC, t.title LIMIT 1"
        ),
        {**params, "artist": name},
    ).one()
    return {
        "name": name,
        "plays": int(row[0] or 0),
        "tracks": int(row[1] or 0),
        "first_listen": row[2],
        "last_listen": row[3],
        "top_track": {
            "video_id": top[0],
            "title": top[1],
            "channel": top[2],
            "plays": int(top[3] or 0),
        },
    }


def by_hour(
    session: Session, date_from: date | None = None, date_to: date | None = None
) -> list[tuple[str, int]]:
    join, params = _music_listen_join(date_from, date_to)
    rows = session.execute(
        text(
            "SELECT strftime('%H', l.listened_at) AS h, COUNT(*) "
            + join
            + " GROUP BY h ORDER BY h"
        ),
        params,
    ).all()
    return [(r[0], r[1]) for r in rows]


def by_weekday(
    session: Session, date_from: date | None = None, date_to: date | None = None
) -> list[tuple[str, int]]:
    join, params = _music_listen_join(date_from, date_to)
    rows = session.execute(
        text(
            "SELECT (CAST(strftime('%w', l.listened_at) AS INTEGER) + 6) % 7 AS wd, COUNT(*) "
            + join
            + " GROUP BY wd ORDER BY wd"
        ),
        params,
    ).all()
    return [(WEEKDAYS[r[0]], r[1]) for r in rows]


def by_month(
    session: Session, date_from: date | None = None, date_to: date | None = None
) -> list[tuple[str, int]]:
    join, params = _music_listen_join(date_from, date_to)
    rows = session.execute(
        text(
            "SELECT strftime('%Y-%m', l.listened_at) AS m, COUNT(*) "
            + join
            + " GROUP BY m ORDER BY m"
        ),
        params,
    ).all()
    return [(r[0], r[1]) for r in rows]


def by_week(
    session: Session, date_from: date | None = None, date_to: date | None = None
) -> list[tuple[str, int]]:
    """Listens by week; label is the Monday date of that week."""
    join, params = _music_listen_join(date_from, date_to)
    rows = session.execute(
        text(
            "SELECT strftime('%Y-%m-%d', l.listened_at, '-6 days', 'weekday 1') AS w, COUNT(*) "
            + join
            + " GROUP BY w ORDER BY w"
        ),
        params,
    ).all()
    return [(r[0], r[1]) for r in rows]


def _feature_listen_join(
    date_from: date | None = None, date_to: date | None = None
) -> tuple[str, dict]:
    sql = (
        "FROM listen l JOIN track t ON t.video_id = l.track_id "
        "JOIN audio_features f ON f.track_id = t.video_id "
        "WHERE t.is_music = 1"
    )
    params: dict = {}
    if date_from is not None:
        sql += " AND l.listened_at >= :dfrom"
        params["dfrom"] = datetime.combine(date_from, datetime.min.time())
    if date_to is not None:
        sql += " AND l.listened_at < :dto"
        params["dto"] = datetime.combine(date_to + timedelta(days=1), datetime.min.time())
    return sql, params


def _lyrics_listen_join(
    date_from: date | None = None, date_to: date | None = None
) -> tuple[str, dict]:
    sql = (
        "FROM listen l JOIN track t ON t.video_id = l.track_id "
        "JOIN lyrics ly ON ly.track_id = t.video_id "
        "AND ly.text != '' AND ly.source != 'whisper' "
        "WHERE t.is_music = 1"
    )
    params: dict = {}
    if date_from is not None:
        sql += " AND l.listened_at >= :dfrom"
        params["dfrom"] = datetime.combine(date_from, datetime.min.time())
    if date_to is not None:
        sql += " AND l.listened_at < :dto"
        params["dto"] = datetime.combine(date_to + timedelta(days=1), datetime.min.time())
    return sql, params


def _period_bounds(date_from, date_to) -> tuple[date, date]:
    """Effective period; defaults to the last 30 days."""
    to = date_to or date.today()
    from_ = date_from or (to - timedelta(days=29))
    return from_, to


def _prev_bounds(date_from, date_to) -> tuple[date | None, date | None]:
    """Same-length period immediately before; None when period is not set."""
    if date_from is None:
        return None, None
    to = date_to or date.today()
    length = (to - date_from).days + 1
    prev_to = date_from - timedelta(days=1)
    return prev_to - timedelta(days=length - 1), prev_to


def _bucket(granularity: str) -> str:
    if granularity == "week":
        return "strftime('%Y-%m-%d', l.listened_at, '-6 days', 'weekday 1')"
    return "strftime('%Y-%m', l.listened_at)"


def _period_numbers(
    session: Session, date_from: date | None, date_to: date | None
) -> dict:
    join, params = _music_listen_join(date_from, date_to)
    row = session.execute(
        text(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN t.duration IS NULL THEN :avg ELSE t.duration END), "
            f"COUNT(DISTINCT {ARTIST_EXPR}), COUNT(DISTINCT t.video_id) "
            + join
        ),
        {**params, "avg": AVG_UNKNOWN_SECONDS},
    ).one()
    return {
        "listens": int(row[0] or 0),
        "hours": round(float(row[1] or 0) / 3600, 1),
        "artists": int(row[2] or 0),
        "tracks": int(row[3] or 0),
    }


def kpi(
    session: Session, date_from: date | None = None, date_to: date | None = None
) -> dict:
    """Current-period numbers plus the same-length previous period."""
    current = _period_numbers(session, date_from, date_to)
    prev_from, prev_to = _prev_bounds(date_from, date_to)
    prev = _period_numbers(session, prev_from, prev_to) if prev_from else None
    result: dict[str, dict] = {}
    for key, value in current.items():
        result[key] = {"value": value, "prev": prev[key] if prev else None}
    return result


def discoveries(
    session: Session, date_from: date | None = None, date_to: date | None = None, limit: int = 5
) -> dict:
    """Artists/tracks heard for the first time inside the period."""
    from_, to = _period_bounds(date_from, date_to)
    dfrom = datetime.combine(from_, time.min)
    dto = datetime.combine(to + timedelta(days=1), time.min)
    base = (
        "FROM listen l JOIN track t ON t.video_id = l.track_id "
        "WHERE t.is_music = 1"
    )
    in_period = " AND l.listened_at >= :dfrom AND l.listened_at < :dto"
    params = {"dfrom": dfrom, "dto": dto, "lim": limit}

    artists = session.execute(
        text(
            "SELECT a.artist, a.plays FROM ("
            f" SELECT {ARTIST_EXPR} AS artist, COUNT(*) AS plays {base}{in_period}"
            f" AND {ARTIST_EXPR} != '' GROUP BY artist"
            ") a JOIN ("
            f" SELECT {ARTIST_EXPR} AS artist, MIN(l.listened_at) AS first {base}"
            f" AND {ARTIST_EXPR} != '' GROUP BY artist"
            ") f ON f.artist = a.artist"
            " WHERE f.first >= :dfrom AND f.first < :dto"
            " ORDER BY a.plays DESC LIMIT :lim"
        ),
        params,
    ).all()
    new_artists_total = session.execute(
        text(
            "SELECT COUNT(*) FROM ("
            f" SELECT {ARTIST_EXPR} AS artist, MIN(l.listened_at) AS first {base}"
            f" AND {ARTIST_EXPR} != '' GROUP BY artist"
            ") WHERE first >= :dfrom AND first < :dto"
        ),
        params,
    ).scalar()

    tracks = session.execute(
        text(
            "SELECT nt.video_id, nt.title, nt.channel, nt.artist, nt.plays FROM ("
            " SELECT t.video_id, t.title, t.channel, "
            f" {ARTIST_EXPR} AS artist, COUNT(*) AS plays {base}{in_period}"
            " GROUP BY t.video_id"
            ") nt JOIN ("
            " SELECT t.video_id, MIN(l.listened_at) AS first "
            + base
            + " GROUP BY t.video_id"
            ") ft ON ft.video_id = nt.video_id"
            " WHERE ft.first >= :dfrom AND ft.first < :dto"
            " ORDER BY nt.plays DESC LIMIT :lim"
        ),
        params,
    ).all()
    new_tracks_total = session.execute(
        text(
            "SELECT COUNT(*) FROM ("
            " SELECT t.video_id, MIN(l.listened_at) AS first "
            + base
            + " GROUP BY t.video_id"
            ") WHERE first >= :dfrom AND first < :dto"
        ),
        params,
    ).scalar()

    return {
        "new_artists_total": int(new_artists_total or 0),
        "top_new_artists": [
            {"name": r[0], "plays": int(r[1])} for r in artists
        ],
        "new_tracks_total": int(new_tracks_total or 0),
        "top_new_tracks": [
            {
                "video_id": r[0],
                "title": r[1],
                "channel": r[2],
                "artist": r[3],
                "plays": int(r[4]),
            }
            for r in tracks
        ],
    }


def genre_distribution(
    session: Session, date_from: date | None = None, date_to: date | None = None, limit: int = 10
) -> tuple[list[dict], float]:
    """Top genres weighted by listens; tags JSON is parsed in Python."""
    total = session.execute(
        text("SELECT COUNT(*) " + _music_listen_join(date_from, date_to)[0]),
        _music_listen_join(date_from, date_to)[1],
    ).scalar()
    join, params = _feature_listen_join(date_from, date_to)
    rows = session.execute(
        text("SELECT f.tags, COUNT(*) " + join + " AND f.tags != '' GROUP BY f.tags"),
        params,
    ).all()
    counts: dict[str, int] = {}
    covered = 0
    for tags_json, n in rows:
        covered += n
        try:
            genres = json.loads(tags_json).get("genres", [])
        except (ValueError, TypeError, KeyError):
            continue
        for g in genres:
            name = g.get("name", "")
            if name:
                counts[name] = counts.get(name, 0) + n
    top = sorted(counts.items(), key=lambda x: -x[1])[:limit]
    distribution = [{"name": name, "listens": n} for name, n in top]
    coverage = round(covered / total, 3) if total else 0.0
    return distribution, coverage


def avg_features(
    session: Session, date_from: date | None = None, date_to: date | None = None
) -> dict:
    """Average audio features over listens (weights = play counts)."""
    total = session.execute(
        text("SELECT COUNT(*) " + _music_listen_join(date_from, date_to)[0]),
        _music_listen_join(date_from, date_to)[1],
    ).scalar()
    join, params = _feature_listen_join(date_from, date_to)
    covered = int(
        session.execute(text("SELECT COUNT(*) " + join), params).scalar() or 0
    )
    row = session.execute(
        text(
            "SELECT AVG(f.tempo), AVG(f.energy), AVG(f.danceability), "
            "AVG(f.acousticness), AVG(f.brightness) " + join
        ),
        params,
    ).one()
    return {
        "tempo": round(float(row[0]), 1) if row[0] is not None else None,
        "energy": round(float(row[1]), 2) if row[1] is not None else None,
        "danceability": round(float(row[2]), 2) if row[2] is not None else None,
        "acousticness": round(float(row[3]), 2) if row[3] is not None else None,
        "brightness": round(float(row[4]), 2) if row[4] is not None else None,
        "coverage": round(covered / total, 3) if total else 0.0,
    }


def mood_profile(
    session: Session, date_from: date | None = None, date_to: date | None = None
) -> dict:
    """Average mood values across listens, for the radar chart."""
    join, params = _feature_listen_join(date_from, date_to)
    cols = ", ".join(f"AVG(f.mood_{m})" for m in MOODS)
    row = session.execute(text("SELECT " + cols + " " + join), params).one()
    return {
        m: round(float(v), 3) if v is not None else 0.0
        for m, v in zip(MOODS, row)
    }


def by_key(
    session: Session, date_from: date | None = None, date_to: date | None = None, limit: int = 12
) -> list[tuple[str, int]]:
    join, params = _feature_listen_join(date_from, date_to)
    rows = session.execute(
        text(
            "SELECT f.key, COUNT(*) "
            + join
            + " AND f.key != '' GROUP BY f.key ORDER BY COUNT(*) DESC LIMIT :lim"
        ),
        {**params, "lim": limit},
    ).all()
    return [(r[0], r[1]) for r in rows]


def vocal_split(
    session: Session, date_from: date | None = None, date_to: date | None = None
) -> dict:
    """Vocal vs instrumental listens (whisper verdict with ratio fallback)."""
    total = session.execute(
        text("SELECT COUNT(*) " + _music_listen_join(date_from, date_to)[0]),
        _music_listen_join(date_from, date_to)[1],
    ).scalar()
    join, params = _feature_listen_join(date_from, date_to)
    row = session.execute(
        text(
            "SELECT SUM(CASE WHEN COALESCE(f.has_vocals, "
            "f.vocal_ratio >= :vr) = 1 THEN 1 ELSE 0 END), COUNT(*) "
            + join
        ),
        {**params, "vr": VOCAL_RATIO_FALLBACK},
    ).one()
    checked = int(row[1] or 0)
    vocal = int(row[0] or 0)
    return {
        "vocal": vocal,
        "instrumental": checked - vocal,
        "coverage": round(checked / total, 3) if total else 0.0,
    }


def language_distribution(
    session: Session, date_from: date | None = None, date_to: date | None = None, limit: int = 8
) -> list[tuple[str, int]]:
    join, params = _lyrics_listen_join(date_from, date_to)
    rows = session.execute(
        text(
            "SELECT ly.language, COUNT(*) "
            + join
            + " AND ly.language != '' GROUP BY ly.language "
            "ORDER BY COUNT(*) DESC LIMIT :lim"
        ),
        {**params, "lim": limit},
    ).all()
    return [(r[0], r[1]) for r in rows]


def mood_trend(
    session: Session,
    date_from: date | None = None,
    date_to: date | None = None,
    granularity: str = "month",
) -> list[tuple[str, dict]]:
    """Average energy and lyrics sentiment per bucket ('how mood evolved')."""
    bucket = _bucket(granularity)
    fjoin, fparams = _feature_listen_join(date_from, date_to)
    energy = {
        r[0]: (r[1], r[2])
        for r in session.execute(
            text(
                f"SELECT {bucket} AS b, AVG(f.energy), COUNT(*) "
                + fjoin
                + " GROUP BY b ORDER BY b"
            ),
            fparams,
        ).all()
    }
    ljoin, lparams = _lyrics_listen_join(date_from, date_to)
    sentiment = {
        r[0]: r[1]
        for r in session.execute(
            text(
                f"SELECT {bucket} AS b, AVG(ly.sentiment) "
                + ljoin
                + " GROUP BY b ORDER BY b"
            ),
            lparams,
        ).all()
    }
    merged: dict[str, dict] = {}
    for b, (e, n) in energy.items():
        merged[b] = {
            "energy": round(float(e), 3),
            "sentiment": round(float(sentiment[b]), 3) if b in sentiment else None,
            "listens": int(n),
        }
    return sorted(merged.items())
