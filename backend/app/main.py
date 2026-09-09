import json
import re
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import and_, func, or_, text, text
from sqlmodel import Session, select

from app.config import settings
from app.db import engine, init_db
from app.models import (
    AudioFeatures,
    Cluster,
    Job,
    Listen,
    Lyrics,
    Track,
    TrackError,
)
from app.parsers.takeout import load_history_file
from app.services import jobs as jobs_svc
from app.services import preflight as preflight_svc
from app.services.audio import run_audio_analysis
from app.services.audio import analyze_one_status, analyze_track_now
from app.services.clustering import run_clustering
from app.services.importer import run_import
from app.services.lyrics import run_lyrics
from app.services.music_filter import run_filter
from app.services.musicbrainz import run_mb_genres
from app.services.recommend import (
    pair_essentia_match,
    similar_artists,
    similar_tracks_v2,
    similar_tracks_essentia,
)
from app.services import stats as stats_svc
from app.services import errors as errors_svc
from app.services import musicbrainz as mb_svc
from app.services import ytmusic as ytm_svc
from app.services import context as context_svc
from app.services import listenbrainz as lb_svc
from app.services import mixing as mixing_svc
from app.services import sessions as sessions_svc

DIST_DIR = settings.frontend_dist

_workers: dict[str, threading.Thread] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    jobs_svc.cancel_orphans()
    preflight_svc.run_preflight()
    yield
    # on server shutdown (Ctrl+C/reload) ask background jobs
    # to finish — otherwise non-daemon threads keep working through the queue
    for kind in jobs_svc.KINDS:
        jobs_svc.request_cancel(kind)


app = FastAPI(title="yt-music-analyzer", lifespan=lifespan)


def _spawn(kind: str, target) -> None:
    stop = jobs_svc.register_cancel(kind)

    def wrapped() -> None:
        try:
            target(stop)
        finally:
            jobs_svc.clear_cancel(kind)

    t = threading.Thread(target=wrapped, daemon=True, name=f"stage-{kind}")
    _workers[kind] = t
    t.start()


def _track_payload(t: Track) -> dict:
    return {
        "video_id": t.video_id,
        "title": t.title,
        "channel": t.channel,
        "artist": t.artist_canonical or t.channel,
        "play_count": t.play_count,
    }


def _top_mood_ids(session: Session, mood: str) -> list[str]:
    """video_ids of analyzed tracks whose dominant mood is `mood`.

    Essentia mood heads have incomparable scales (epic tops out at ~0.25
    across the library while happy reaches 0.99): a raw argmax would make
    some moods nearly unfilterable, so every head is normalized by its
    own maximum before the argmax. Ties count as a match.
    """
    moods = stats_svc.MOODS
    idx = moods.index(mood)
    cols = ", ".join(f"mood_{m}" for m in moods)
    rows = session.execute(
        text(
            "SELECT track_id, " + cols + " FROM audio_features "
            "WHERE source = 'audio'"
        )
    ).all()
    if not rows:
        return []
    maxes = [
        max((r[i + 1] or 0.0) for r in rows) or 1.0 for i in range(len(moods))
    ]
    ids = []
    for r in rows:
        vals = [(r[i + 1] or 0.0) / maxes[i] for i in range(len(moods))]
        if vals[idx] >= max(vals):
            ids.append(r[0])
    return ids


def _feature_info(session: Session, video_id: str) -> dict:
    """Audio feature summary of a track for recommendation tables."""
    info: dict = {
        "cluster": "",
        "genre": "",
        "language": "",
        "tempo": None,
        "energy": None,
        "danceability": None,
        "acousticness": None,
        "duration": None,
    }
    t = session.get(Track, video_id)
    if t is None:
        return info
    info["duration"] = t.duration
    if t.cluster_id is not None:
        c = session.get(Cluster, t.cluster_id)
        if c is not None:
            info["cluster"] = c.name
    f = session.get(AudioFeatures, video_id)
    if f is not None and f.source == "audio":
        info["tempo"] = _f(f.tempo, 1)
        info["energy"] = _f(f.energy)
        info["danceability"] = _f(f.danceability)
        info["acousticness"] = _f(f.acousticness)
        if f.tags:
            try:
                genres = json.loads(f.tags).get("genres") or []
                if genres:
                    info["genre"] = genres[0].get("name", "")
            except (ValueError, TypeError, KeyError):
                pass
    ly = session.get(Lyrics, video_id)
    if ly is not None:
        info["language"] = ly.language
    return info


def _job_payload(job: Job) -> dict:
    return {
        "kind": job.kind,
        "status": job.status,
        "total": job.total,
        "done": job.done,
        "detail": job.detail,
        "error": job.error,
        "updated_at": job.updated_at.isoformat(),
    }


def _state_payload(session: Session) -> dict:
    totals = stats_svc.totals(session)
    job_rows = session.exec(select(Job).order_by(Job.id)).all()
    latest: dict[str, Job] = {}
    for j in job_rows:
        latest[j.kind] = j
    return {
        "totals": totals,
        "jobs": [
            _job_payload(latest[k]) for k in jobs_svc.KINDS if k in latest
        ],
        "has_api_key": bool(settings.youtube_api_key.strip()),
        "audio_limit": settings.audio_analysis_limit,
    }


@app.get("/api/state")
def api_state() -> dict:
    with Session(engine) as session:
        return _state_payload(session)


@app.post("/api/import")
async def api_import(
    file: UploadFile = File(...),
    tz: str = Form(""),
) -> dict:
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    target = str(settings.uploads_dir / "history.json")
    Path(target).write_bytes(await file.read())
    try:
        load_history_file(target)
    except Exception:
        raise HTTPException(
            400,
            "Failed to parse JSON. Expected a “YouTube watch history” "
            "file exported via Google Takeout (My Activity → YouTube, "
            "JSON format).",
        )
    try:
        ZoneInfo(tz.strip())
        tz_name = tz.strip()
    except Exception:
        tz_name = ""
    _spawn("import", lambda stop: run_import(target, stop, tz_name))
    return {"ok": True}


@app.post("/api/pipeline/filter")
def api_pipeline_filter() -> dict:
    _spawn("filter", run_filter)
    return {"ok": True}


@app.post("/api/pipeline/audio")
def api_pipeline_audio() -> dict:
    _spawn("audio", run_audio_analysis)
    return {"ok": True}


@app.post("/api/pipeline/audio-retry")
def api_pipeline_audio_retry() -> dict:
    from app.services.audio import reset_unavailable

    reset = reset_unavailable()
    _spawn("audio", run_audio_analysis)
    return {"ok": True, "reset": reset}


@app.post("/api/pipeline/clusters")
def api_pipeline_clusters() -> dict:
    _spawn("clusters", run_clustering)
    return {"ok": True}


@app.post("/api/pipeline/lyrics")
def api_pipeline_lyrics() -> dict:
    _spawn("lyrics", run_lyrics)
    return {"ok": True}


@app.post("/api/pipeline/mb-genres")
def api_pipeline_mb_genres() -> dict:
    _spawn("mb-genres", run_mb_genres)
    return {"ok": True}


@app.post("/api/pipeline/sessions")
def api_pipeline_sessions() -> dict:
    _spawn("sessions", sessions_svc.run_sessions)
    return {"ok": True}


def _date_str(v) -> str | None:
    if v is None:
        return None
    return v[:10] if isinstance(v, str) else v.date().isoformat()


def _f(v: float | None, nd: int = 2) -> float | None:
    return round(v, nd) if v is not None else None


ARTIST_EXPR = func.coalesce(
    func.nullif(Track.artist_canonical, ""), Track.channel
)


@app.get("/api/tracks")
def api_tracks(
    q: str = "",
    page: int = 1,
    per_page: int = 200,
    sort: str = "play_count",
    order: str = "desc",
    cluster_id: int | None = None,
    hidden: bool = False,
    genre: str = "",
    language: str = "",
    key: str = "",
    mood: str = "",
    instrumental: bool = False,
    artist: str = "",
    errors: bool = False,
) -> dict:
    import json as _json

    per_page = max(1, min(per_page, 500))
    page = max(1, page)
    if sort not in (
        "play_count",
        "first_listen",
        "last_listen",
        "duration",
        "tempo",
        "energy",
        "danceability",
        "acousticness",
    ):
        sort = "play_count"
    if order not in ("asc", "desc"):
        order = "desc"
    conditions = [Track.is_music == (not hidden)]  # noqa: E712
    if artist.strip():
        conditions.append(ARTIST_EXPR == artist.strip())
    term = q.strip()
    if term:
        # REGEXP (Python-backed, Unicode-aware) — SQLite lower()/LIKE are
        # ASCII-only and miss Cyrillic in other case; artist_canonical is
        # the normalized artist used for the artist search
        pattern = re.escape(term)
        conditions.append(
            or_(
                Track.title.op("REGEXP")(pattern),
                Track.channel.op("REGEXP")(pattern),
                Track.artist_canonical.op("REGEXP")(pattern),
            )
        )
    if cluster_id is not None:
        conditions.append(Track.cluster_id == cluster_id)
    if genre:
        # match only the top-3 "genres" array (what the track card shows and
        # the dashboard counts), not other names inside the tags JSON
        conditions.append(
            text(
                "EXISTS (SELECT 1 FROM json_each("
                "CASE WHEN json_valid(audio_features.tags) "
                "THEN audio_features.tags ELSE '[]' END, '$.genres') je "
                "WHERE json_extract(je.value, '$.name') = :genre_name)"
            ).bindparams(genre_name=genre)
        )
    if key.strip():
        conditions.append(AudioFeatures.key == key.strip())
    if errors:
        conditions.append(
            text(
                "EXISTS (SELECT 1 FROM track_error te "
                "WHERE te.video_id = track.video_id)"
            )
        )
    if instrumental:
        # whisper transcripts are often false positives: tracks whose only
        # lyrics are whisper drafts count as instrumental ("no text")
        conditions.append(
            or_(
                Lyrics.source == "whisper",
                and_(
                    Lyrics.track_id.is_(None),
                    or_(
                        AudioFeatures.has_vocals == False,  # noqa: E712
                        and_(
                            AudioFeatures.has_vocals.is_(None),
                            AudioFeatures.vocal_ratio
                            < settings.lyrics_min_vocal,  # type: ignore[operator]
                        ),
                    ),
                ),
            )
        )
    if language:
        # the language filter ignores whisper transcripts as well
        conditions.append(
            and_(Lyrics.language == language, Lyrics.source != "whisper")
        )
    if mood:
        mood = mood.strip().lower()
        if mood not in stats_svc.MOODS:
            raise HTTPException(422, f"unknown mood: {mood}")
        with Session(engine) as mood_session:
            mood_ids = _top_mood_ids(mood_session, mood)
        if not mood_ids:
            return {"total": 0, "page": page, "per_page": per_page, "tracks": []}
        conditions.append(Track.video_id.in_(mood_ids))

    first_listen = func.min(Listen.listened_at).label("first_listen")
    last_listen = func.max(Listen.listened_at).label("last_listen")
    sort_col = {
        "play_count": Track.play_count,
        "first_listen": first_listen,
        "last_listen": last_listen,
        "duration": Track.duration,
        "tempo": AudioFeatures.tempo,
        "energy": AudioFeatures.energy,
        "danceability": AudioFeatures.danceability,
        "acousticness": AudioFeatures.acousticness,
    }[sort]
    direction = sort_col.desc() if order == "desc" else sort_col.asc()

    with Session(engine) as session:
        total = session.exec(
            select(func.count())
            .select_from(Track)
            .outerjoin(AudioFeatures, AudioFeatures.track_id == Track.video_id)
            .outerjoin(Lyrics, Lyrics.track_id == Track.video_id)
            .where(*conditions)
        ).one()
        rows = session.exec(
            select(Track, first_listen, last_listen, AudioFeatures, Lyrics)
            .outerjoin(Listen, Listen.track_id == Track.video_id)
            .outerjoin(AudioFeatures, AudioFeatures.track_id == Track.video_id)
            .outerjoin(Lyrics, Lyrics.track_id == Track.video_id)
            .where(*conditions)
            .group_by(Track.video_id)
            .order_by(direction, Track.title.asc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        ).all()
        clusters = {c.id: c.name for c in session.exec(select(Cluster)).all()}
        tracks = []
        for t, fl, ll, f, ly in rows:
            item = {
                **_track_payload(t),
                "duration": t.duration,
                "cluster_id": t.cluster_id,
                "cluster_name": clusters.get(t.cluster_id, ""),
                "first_listen": _date_str(fl),
                "last_listen": _date_str(ll),
                "music_reason": t.music_reason,
                "language": ly.language if ly is not None else "",
                "sentiment": ly.sentiment if ly is not None else None,
            }
            if f is not None:
                item.update(
                    {
                        "tempo": _f(f.tempo, 1),
                        "energy": _f(f.energy),
                        "danceability": _f(f.danceability),
                        "acousticness": _f(f.acousticness),
                        "brightness": _f(f.brightness),
                        "key": f.key,
                        "loudness": _f(f.loudness, 1),
                        "dynamics": _f(f.dynamics),
                        "percussive": _f(f.percussive),
                        "mood_happy": _f(f.mood_happy, 3),
                        "mood_sad": _f(f.mood_sad, 3),
                        "mood_relaxed": _f(f.mood_relaxed, 3),
                        "mood_aggressive": _f(f.mood_aggressive, 3),
                        "mood_electronic": _f(f.mood_electronic, 3),
                        "mood_acoustic": _f(f.mood_acoustic, 3),
                        "mood_party": _f(f.mood_party, 3),
                        "mood_epic": _f(f.mood_epic, 3),
                        "mood_dark": _f(f.mood_dark, 3),
                        "mood_romantic": _f(f.mood_romantic, 3),
                        "mood_atmospheric": _f(f.mood_atmospheric, 3),
                        "features_source": f.source,
                        "vocal_ratio": _f(f.vocal_ratio, 3),
                        "has_vocals": f.has_vocals,
                    }
                )
                if f.tags:
                    try:
                        parsed = _json.loads(f.tags)
                        item["genres"] = [
                            g["name"] for g in parsed.get("genres", [])
                        ]
                        item["instruments"] = [
                            g["name"] for g in parsed.get("instruments", [])
                        ]
                    except (ValueError, TypeError, KeyError):
                        pass
            tracks.append(item)
        # flag rows that currently have a processing error (page-local query)
        page_ids = [t.video_id for t, *_ in rows]
        err_ids: set[str] = set()
        if page_ids:
            err_ids = set(
                session.exec(
                    select(TrackError.video_id).where(  # type: ignore[arg-type]
                        TrackError.video_id.in_(page_ids)  # type: ignore[union-attr]
                    )
                ).all()
            )
        for item in tracks:
            item["has_error"] = item["video_id"] in err_ids
        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "tracks": tracks,
        }


@app.get("/api/tracks/{video_id}")
def api_track_detail(video_id: str) -> dict:
    import json as _json

    from app.services.topics import dominant_topic

    with Session(engine) as session:
        track = session.get(Track, video_id)
        if track is None:
            raise HTTPException(404, "Track not found")
        fl = session.exec(
            select(func.min(Listen.listened_at), func.max(Listen.listened_at)).where(
                Listen.track_id == video_id
            )
        ).one()
        f = session.get(AudioFeatures, video_id)
        ly = session.get(Lyrics, video_id)
        cluster_name = ""
        if track.cluster_id is not None:
            cluster = session.get(Cluster, track.cluster_id)
            if cluster is not None:
                cluster_name = cluster.name
        item = {
            **_track_payload(track),
            "duration": track.duration,
            "cluster_id": track.cluster_id,
            "cluster_name": cluster_name,
            "first_listen": _date_str(fl[0]),
            "last_listen": _date_str(fl[1]),
            "music_reason": track.music_reason,
            "language": ly.language if ly is not None else "",
            "sentiment": ly.sentiment if ly is not None else None,
            "topic": dominant_topic(ly.topics) if ly is not None else "",
            "has_lyrics": ly is not None and bool(ly.text),
            "genre_scores": [],
            "instrument_scores": [],
            "errors": errors_svc.track_errors(video_id),
        }
        if f is not None:
            item.update(
                {
                    "tempo": _f(f.tempo, 1),
                    "energy": _f(f.energy),
                    "danceability": _f(f.danceability),
                    "acousticness": _f(f.acousticness),
                    "brightness": _f(f.brightness),
                    "key": f.key,
                    "loudness": _f(f.loudness, 1),
                    "dynamics": _f(f.dynamics),
                    "percussive": _f(f.percussive),
                    "mood_happy": _f(f.mood_happy, 3),
                    "mood_sad": _f(f.mood_sad, 3),
                    "mood_relaxed": _f(f.mood_relaxed, 3),
                    "mood_aggressive": _f(f.mood_aggressive, 3),
                    "mood_electronic": _f(f.mood_electronic, 3),
                    "mood_acoustic": _f(f.mood_acoustic, 3),
                    "mood_party": _f(f.mood_party, 3),
                    "mood_epic": _f(f.mood_epic, 3),
                    "mood_dark": _f(f.mood_dark, 3),
                    "mood_romantic": _f(f.mood_romantic, 3),
                    "mood_atmospheric": _f(f.mood_atmospheric, 3),
                    "features_source": f.source,
                    "vocal_ratio": _f(f.vocal_ratio, 3),
                    "has_vocals": f.has_vocals,
                }
            )
            if f.tags:
                try:
                    parsed = _json.loads(f.tags)
                    item["genre_scores"] = [
                        {"name": g["name"], "score": g.get("score", 0.0)}
                        for g in parsed.get("genres", [])
                    ]
                    item["instrument_scores"] = [
                        {"name": g["name"], "score": g.get("score", 0.0)}
                        for g in parsed.get("instruments", [])
                    ]
                except (ValueError, TypeError, KeyError):
                    pass
        item["ytm"] = ytm_svc.meta_for_track(video_id, track.title)
        return item


@app.get("/api/clusters")
def api_clusters() -> list[dict]:
    with Session(engine) as session:
        clusters = session.exec(
            select(Cluster).order_by(Cluster.size.desc())
        ).all()
        return [
            {"id": c.id, "name": c.name, "size": c.size} for c in clusters
        ]


@app.post("/api/tracks/{video_id}/analyze")
def api_track_analyze(video_id: str) -> dict:
    """On-demand analysis of one track (button in the track card)."""
    with Session(engine) as session:
        if session.get(Track, video_id) is None:
            raise HTTPException(404, "Track not found")
    threading.Thread(
        target=analyze_track_now,
        args=(video_id,),
        daemon=True,
        name=f"analyze-one-{video_id}",
    ).start()
    return {"ok": True, "status": "started"}


@app.get("/api/tracks/{video_id}/analyze-status")
def api_track_analyze_status(video_id: str) -> dict:
    return analyze_one_status(video_id)


@app.post("/api/tracks/{video_id}/classify")
def api_classify_track(video_id: str, is_music: bool = Body(..., embed=True)) -> dict:
    with Session(engine) as session:
        track = session.get(Track, video_id)
        if track is None:
            raise HTTPException(404, "Track not found")
        track.is_music = is_music
        track.music_reason = "manual"
        session.add(track)
        session.commit()
        return {"ok": True, "video_id": video_id, "is_music": is_music}


@app.post("/api/channels/hide")
def api_hide_channel(channel: str = Body(..., embed=True)) -> dict:
    channel = channel.strip()
    if not channel:
        raise HTTPException(400, "Empty channel name")
    with Session(engine) as session:
        tracks = session.exec(
            select(Track).where(
                Track.channel == channel, Track.is_music == True  # noqa: E712
            )
        ).all()
        for t in tracks:
            t.is_music = False
            t.music_reason = "manual-not-music"
            session.add(t)
        session.commit()
        return {"ok": True, "channel": channel, "hidden": len(tracks)}


GENRE = {
    "Blues": "blues", "Classical": "classical", "Electronic": "electronic",
    "Folk, World, & Country": "folk", "Funk / Soul": "funk/soul",
    "Hip Hop": "hip-hop", "Jazz": "jazz", "Latin": "latin",
    "Non-Music": "non-music", "Pop": "pop", "Reggae": "reggae",
    "Rock": "rock", "Stage & Screen": "soundtrack",
    "Ambient": "ambient", "House": "house", "Techno": "techno",
    "Trance": "trance", "Drum n Bass": "dnb", "Breakbeat": "breakbeat",
    "Dubstep": "dubstep", "Synth-pop": "synth-pop", "Electro": "electro",
    "Deep House": "deep house", "Tech House": "tech house", "Electro House": "electro house",
    "Experimental": "experimental", "New Age": "new age", "Downtempo": "downtempo",
    "IDM": "idm", "Industrial": "industrial", "Indie Rock": "indie rock",
    "Alternative Rock": "alt. rock", "Punk": "punk", "Metal": "metal",
    "Heavy Metal": "metal", "Death Metal": "death metal", "Black Metal": "black metal",
    "Hard Rock": "hard rock", "Prog. Rock": "prog rock", "Psychedelic Rock": "psychedelic",
    "Hip-Hop": "hip-hop", "Trap": "trap", "Boom Bap": "boom bap",
    "R&B": "r&b", "Soul": "soul", "Funk": "funk", "Disco": "disco",
    "Ballad": "ballad", "Beatdown": "beatdown", "Hardcore": "hardcore",
    "Hard Techno": "hard techno", "Bassline": "bassline", "Club": "club",
    "Dance": "dance", "Eurodance": "eurodance", "Chillwave": "chillwave",
    "Vaporwave": "vaporwave", "Lo-Fi": "lo-fi", "Noise": "noise",
    "Soundtrack": "soundtrack", "Score": "film score", "Theme": "theme",
    "Musical": "musical", "Bossa Nova": "bossa nova", "Jazz-Funk": "jazz-funk",
    "Swing": "swing", "Bluegrass": "bluegrass", "Country": "country",
    "Ska": "ska", "Reggaeton": "reggaeton", "Dub": "dub",
    "Modern Classical": "modern classical", "Neo-Classical": "neo-classical",
    "Leftfield": "leftfield", "Glitch": "glitch", "Footwork": "footwork",
    "Garage House": "garage house", "UK Garage": "uk garage",
    "Future Jazz": "future jazz", "Nu Jazz": "nu jazz", "Tribal": "tribal",
}


@app.get("/api/genres")
def api_genres() -> list[dict]:
    """Top genres from the actual tags stored in the DB (for the home filter)."""
    import json as _json

    with Session(engine) as session:
        rows = session.exec(
            select(AudioFeatures.tags).where(  # type: ignore[arg-type]
                AudioFeatures.tags != ""
            )
        ).all()
    counts: dict[str, int] = {}
    for tj in rows:
        try:
            for g in _json.loads(tj).get("genres", []):
                counts[g["name"]] = counts.get(g["name"], 0) + 1
        except (ValueError, TypeError, KeyError):
            continue
    result = [
        {
            "name": name,
            "name_ru": GENRE.get(name, name),
            "count": n,
        }
        for name, n in sorted(counts.items(), key=lambda x: -x[1])[:40]
        if n >= 3
    ]
    return result


@app.get("/api/languages")
def api_languages() -> list[dict]:
    """Lyrics languages present in the DB with track counts (tracks filter).

    Whisper transcripts are excluded: they are drafts, not real lyrics,
    so they must not appear in the language filter.
    """
    with Session(engine) as session:
        rows = session.exec(
            select(Lyrics.language, func.count(Lyrics.track_id))
            .where(
                Lyrics.text != "",  # type: ignore[arg-type]
                Lyrics.source != "whisper",
            )
            .group_by(Lyrics.language)
        ).all()
    return [
        {"code": lang, "count": n}
        for lang, n in sorted(rows, key=lambda r: (-r[1], r[0]))
        if lang
    ]


@app.get("/api/errors")
def api_errors() -> list[dict]:
    """Current per-track processing errors (audio/lyrics), newest first."""
    return errors_svc.list_errors()


@app.get("/api/discoveries")
def api_discoveries(
    date_from: str | None = None,
    date_to: str | None = None,
    artists_limit: int = 8,
    tracks_limit: int = 8,
) -> dict:
    """New artists/tracks of the period (first listen inside it)."""
    d_from = _parse_date(date_from, "date_from")
    d_to = _parse_date(date_to, "date_to")
    if d_from and d_to and d_from > d_to:
        raise HTTPException(422, "date_from must be earlier than date_to")
    with Session(engine) as session:
        res = stats_svc.discoveries(
            session,
            d_from,
            d_to,
            artists_limit=max(1, min(artists_limit, 50)),
            tracks_limit=max(1, min(tracks_limit, 50)),
        )
        for it in res["top_new_tracks"]:
            it["info"] = _feature_info(session, it["video_id"])
        return res


@app.get("/api/mood-counts")
def api_mood_counts() -> list[dict]:
    """Track counts per dominant mood (tracks filter options).

    Same per-head-max normalization as the `mood` filter in /api/tracks;
    a track with tied dominant moods is counted for each of them, so the
    numbers always match what selecting the mood returns.
    """
    moods = stats_svc.MOODS
    cols = ", ".join(f"mood_{m}" for m in moods)
    with Session(engine) as session:
        rows = session.execute(
            text(
                "SELECT track_id, " + cols + " FROM audio_features "
                "WHERE source = 'audio'"
            )
        ).all()
    counts = [0] * len(moods)
    if rows:
        maxes = [
            max((r[i + 1] or 0.0) for r in rows) or 1.0
            for i in range(len(moods))
        ]
        for r in rows:
            vals = [(r[i + 1] or 0.0) / maxes[i] for i in range(len(moods))]
            top = max(vals)
            for i, v in enumerate(vals):
                if v == top:
                    counts[i] += 1
    return [{"name": m, "count": c} for m, c in zip(moods, counts)]


@app.get("/api/keys")
def api_keys() -> list[dict]:
    """Musical keys present in analyzed tracks, with counts (tracks filter)."""
    with Session(engine) as session:
        rows = session.exec(
            select(AudioFeatures.key, func.count(AudioFeatures.track_id))
            .join(Track, Track.video_id == AudioFeatures.track_id)  # type: ignore[call-arg]
            .where(
                AudioFeatures.key != "",  # type: ignore[arg-type]
                Track.is_music == True,  # noqa: E712
            )
            .group_by(AudioFeatures.key)
            .order_by(func.count(AudioFeatures.track_id).desc())
        ).all()
    return [{"key": k, "count": n} for k, n in rows if k]


@app.get("/api/tracks/{video_id}/lyrics")
def api_track_lyrics(video_id: str) -> dict:
    with Session(engine) as session:
        row = session.get(Lyrics, video_id)
        if row is None or not row.text:
            raise HTTPException(404, "Lyrics not found")
        return {
            "track_id": video_id,
            "text": row.text,
            "synced": row.synced,
            "source": row.source,
            "language": row.language,
            "sentiment": row.sentiment,
        }


@app.post("/api/jobs/{kind}/cancel")
def api_cancel_job(kind: str) -> dict:
    if kind not in jobs_svc.KINDS:
        raise HTTPException(404, "Unknown job type")
    ok = jobs_svc.request_cancel(kind)
    if not ok:
        raise HTTPException(409, "Job is not running")
    return {"ok": True, "kind": kind}


@app.get("/api/dashboard")
def api_dashboard(
    date_from: str | None = None, date_to: str | None = None, granularity: str = "month"
) -> dict:
    d_from = _parse_date(date_from, "date_from")
    d_to = _parse_date(date_to, "date_to")
    if d_from and d_to and d_from > d_to:
        raise HTTPException(422, "date_from must be earlier than date_to")
    if granularity not in ("month", "week"):
        raise HTTPException(422, "granularity must be month or week")
    with Session(engine) as session:
        genres, genre_coverage = stats_svc.genre_distribution(session, d_from, d_to)
        return {
            "totals": stats_svc.totals(session, d_from, d_to),
            "kpi": stats_svc.kpi(session, d_from, d_to),
            "genre_distribution": genres,
            "genre_coverage": genre_coverage,
            "avg_features": stats_svc.avg_features(session, d_from, d_to),
            "mood_profile": stats_svc.mood_profile(session, d_from, d_to),
            "by_key": stats_svc.by_key(session, d_from, d_to),
            "vocal_split": stats_svc.vocal_split(session, d_from, d_to),
            "language_distribution": stats_svc.language_distribution(
                session, d_from, d_to
            ),
            "mood_trend": stats_svc.mood_trend(
                session, d_from, d_to, granularity
            ),
            "by_hour": stats_svc.by_hour(session, d_from, d_to),
            "by_weekday": stats_svc.by_weekday(session, d_from, d_to),
            "timeline": (
                stats_svc.by_month(session, d_from, d_to)
                if granularity == "month"
                else stats_svc.by_week(session, d_from, d_to)
            ),
        }


@app.get("/api/artists")
def api_artists() -> list[dict]:
    with Session(engine) as session:
        result = stats_svc.artists(session)
    for item in result:
        item["genre"] = mb_svc.cached_genre(item["channel"])
    return result


@app.get("/api/artist")
def api_artist(name: str = "") -> dict:
    name = name.strip()
    if not name:
        raise HTTPException(400, "Empty artist name")
    with Session(engine) as session:
        summary = stats_svc.artist_summary(session, name)
        if summary is None:
            raise HTTPException(404, "Artist not found")
    # on demand: first call hits MusicBrainz (throttled), then it is cached
    summary["mb"] = mb_svc.artist_info(name)
    return summary


def _parse_date(value: str | None, name: str):
    if value is None or not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(422, f"{name} must be a date in YYYY-MM-DD format")


@app.get("/api/moods")
def api_moods() -> dict:
    with Session(engine) as session:
        clusters = session.exec(
            select(Cluster).order_by(Cluster.size.desc())
        ).all()
        cards = []
        for c in clusters:
            tracks = session.exec(
                select(Track)
                .where(Track.cluster_id == c.id)
                .order_by(Track.play_count.desc())
                .limit(15)
            ).all()
            cards.append(
                {
                    "cluster": {"id": c.id, "name": c.name, "size": c.size},
                    "tracks": [_track_payload(t) for t in tracks],
                }
            )
        totals = stats_svc.totals(session)
        return {
            "analyzed": totals["analyzed"],
            "cards": cards,
        }


@app.get("/api/recommendations")
def api_recommendations(track_id: str = "") -> dict:
    from app.services.artists import normalize_artist

    with Session(engine) as session:
        analyzed = session.exec(
            select(AudioFeatures).order_by(AudioFeatures.analyzed_at.desc())
        ).all()
        options = []
        for f in analyzed:
            t = session.get(Track, f.track_id)
            if t is not None:
                options.append({"track": _track_payload(t)})
        selected = None
        sim_artists: list[dict] | None = None
        lb_artists: list[dict] = []
        lb_error = ""
        if track_id:
            t = session.get(Track, track_id)
            if t is not None:
                selected = _track_payload(t)
            sim_artists = similar_artists(track_id)
            # global similar artists (ListenBrainz), enriched with the
            # user's own listening stats; on-demand + cached in lb_similar
            if t is not None:
                artist_name = t.artist_canonical or t.channel
                raw_lb, lb_error = lb_svc.similar_for_name(artist_name)
                if raw_lb:
                    canonical_plays: dict[str, int] = {}
                    rows = session.execute(
                        text(
                            "SELECT COALESCE(NULLIF(artist_canonical, ''), channel), "
                            "SUM(play_count) FROM track WHERE is_music = 1 "
                            "GROUP BY 1"
                        )
                    ).all()
                    canonical_plays = {r[0]: int(r[1] or 0) for r in rows if r[0]}
                    known = set(canonical_plays)
                    for a in raw_lb:
                        norm = normalize_artist(a["name"])
                        plays = canonical_plays.get(norm, 0)
                        lb_artists.append(
                            {
                                **a,
                                "plays": plays,
                                "in_history": norm in known,
                            }
                        )
        return {
            "options": options,
            "selected": selected,
            "similar_artists": sim_artists,
            "lb_artists": lb_artists,
            "lb_error": lb_error,
        }


@app.get("/api/recommendations/similar")
def api_recommendations_similar(
    track_id: str = "", offset: int = 0, limit: int = 6
) -> dict:
    if not track_id:
        return {"similar": [], "total": 0}
    sim = similar_tracks_v2(track_id, offset=offset, limit=limit)
    if sim is None:
        return {"similar": [], "total": 0}
    items, total = sim
    result = []
    with Session(engine) as session:
        for s in items:
            result.append(
                {
                    "track": _track_payload(s["track"]),
                    "distance": s["distance"],
                    "tempo": s["tempo"],
                    "match": s["match"],
                    "info": _feature_info(session, s["track"].video_id),
                }
            )
    return {"similar": result, "total": total}


@app.get("/api/recommendations/essentia")
def api_recommendations_essentia(
    track_id: str = "", offset: int = 0, limit: int = 6
) -> dict:
    with Session(engine) as session:
        if not track_id:
            return {"similar": [], "total": 0}
        sim = similar_tracks_essentia(track_id, offset=offset, limit=limit)
        if sim is None:
            return {"similar": [], "total": 0}
        items, total = sim
        result = []
        for s in items:
            t = session.get(Track, s["track"].video_id)
            if t is None:
                continue
            result.append(
                {
                    "track": {
                        "video_id": t.video_id,
                        "title": t.title,
                        "channel": t.channel,
                        "artist": t.artist_canonical or t.channel,
                        "is_music": t.is_music,
                        "play_count": t.play_count,
                    },
                    "distance": s["distance"],
                    "match": s["match"],
                    "info": _feature_info(session, t.video_id),
                }
            )
        return {"similar": result, "total": total}


@app.get("/api/tracks/{video_id}/youtube-similar")
def api_youtube_similar(video_id: str) -> dict:
    """YouTube-native recommendations ("radio" seeded by this track)."""
    if not ytm_svc.enabled():
        return {"enabled": False, "similar": []}
    with Session(engine) as session:
        track = session.get(Track, video_id)
        title = track.title if track is not None else ""
    items = ytm_svc.similar(video_id, title)
    with Session(engine) as session:
        seed_f = session.get(AudioFeatures, video_id)
        seed_analyzed = (
            seed_f is not None and seed_f.source == "audio" and bool(seed_f.tags)
        )
        for it in items:
            t = session.get(Track, it["video_id"])
            it["in_history"] = t is not None
            it["info"] = None
            if t is None:
                continue
            fl = session.exec(
                select(func.min(Listen.listened_at), func.max(Listen.listened_at)).where(
                    Listen.track_id == it["video_id"]
                )
            ).one()
            info = _feature_info(session, it["video_id"])
            info["play_count"] = t.play_count
            info["first_listen"] = _date_str(fl[0])
            info["last_listen"] = _date_str(fl[1])
            if seed_analyzed:
                m = pair_essentia_match(video_id, it["video_id"])
                if m is not None:
                    info["match"] = round(m * 100)
            it["info"] = info
    return {"enabled": True, "similar": items}


@app.get("/api/tracks/{video_id}/co-listened")
def api_co_listened(video_id: str, limit: int = 10) -> dict:
    """Tracks historically listened in the same sessions (co-occurrence)."""
    res = sessions_svc.co_listened(video_id, limit=max(1, min(limit, 50)))
    if res is None:
        return {"built": False, "items": [], "total": 0}
    with Session(engine) as session:
        for it in res["items"]:
            it["info"] = _feature_info(session, it["track"]["video_id"])
    return {"built": True, **res}


@app.get("/api/tracks/{video_id}/next")
def api_next_tracks(video_id: str, limit: int = 10) -> dict:
    """What usually follows this track in the user's history (Markov)."""
    res = sessions_svc.next_tracks(video_id, limit=max(1, min(limit, 50)))
    if res is None:
        return {"built": False, "items": [], "total": 0}
    with Session(engine) as session:
        for it in res["items"]:
            it["info"] = _feature_info(session, it["track"]["video_id"])
    return {"built": True, **res}


@app.get("/api/tracks/{video_id}/mixable")
def api_mixable(video_id: str, limit: int = 12) -> dict:
    """Harmonically mix-compatible tracks (Camelot wheel + BPM)."""
    res = mixing_svc.mixable(video_id, limit=max(1, min(limit, 50)))
    if res is None:
        return {"available": False, "items": [], "total": 0}
    with Session(engine) as session:
        for it in res["items"]:
            it["info"] = _feature_info(session, it["track"]["video_id"])
    return {"available": True, **res}


@app.get("/api/recommendations/context")
def api_recommendations_context(
    hour: int = -1,
    weekday: int = -1,
    limit: int = 12,
    date_from: str | None = None,
    date_to: str | None = None,
    tz: str = "",
) -> dict:
    """Tracks that fit the given (or current) time of day and weekday."""
    h = hour if 0 <= hour <= 23 else None
    wd = weekday if 0 <= weekday <= 6 else None
    d_from = _parse_date(date_from, "date_from")
    d_to = _parse_date(date_to, "date_to")
    if d_from and d_to and d_from > d_to:
        raise HTTPException(422, "date_from must be earlier than date_to")
    res = context_svc.for_now(
        h,
        wd,
        limit=max(1, min(limit, 100)),
        date_from=d_from,
        date_to=d_to,
        tz_name=tz,
    )
    with Session(engine) as session:
        for it in res["items"]:
            it["info"] = _feature_info(session, it["track"]["video_id"])
    return res




SETTINGS_FIELDS: list[dict] = [
    {
        "key": "youtube_api_key",
        "type": "str",
        "label": "YouTube API key",
        "hint": "YouTube Data API v3 key: the music filter uses it to detect video category and duration.",
    },
    {
        "key": "min_play_count",
        "type": "int",
        "label": "Minimum plays for analysis",
        "hint": "Tracks with fewer plays are skipped by the audio analysis and lyrics stages.",
    },
    {
        "key": "audio_analysis_limit",
        "type": "int",
        "label": "Audio analysis limit per run",
        "hint": "How many tracks to analyze per run (0 — all eligible).",
    },
    {
        "key": "analyze_full_max",
        "type": "int",
        "label": "Full analysis up to (seconds)",
        "hint": "Longer tracks are analyzed using a preview fragment.",
    },
    {
        "key": "audio_workers",
        "type": "int",
        "label": "Download threads",
        "hint": "Parallel audio downloads (bottleneck: network).",
    },
    {
        "key": "audio_workers_cached",
        "type": "int",
        "label": "Cached analysis threads",
        "hint": "Parallel analysis when audio is already downloaded (bottleneck: CPU).",
    },
    {
        "key": "audio_delete_after",
        "type": "bool",
        "label": "Delete audio after analysis",
        "hint": "Saves disk space, but re-analysis requires downloading again.",
    },
    {
        "key": "cluster_use_embedding",
        "type": "bool",
        "label": "Cluster in neural embedding space",
        "hint": "Use Discogs-EffNet embeddings (1280-d, cosine-like) instead of "
        "v2 features (timbre/rhythm/harmony). Re-run Clustering to apply.",
    },
    {
        "key": "lyrics_limit",
        "type": "int",
        "label": "Lyrics lookup limit per run",
        "hint": "How many tracks to check per run (0 — all eligible).",
    },
    {
        "key": "lyrics_min_vocal",
        "type": "float",
        "label": "Vocal threshold for lyrics",
        "hint": "Vocal score above which a track counts as vocal without a "
        "whisper spot-check (LRCLIB is searched regardless).",
    },
    {
        "key": "whisper_model",
        "type": "str",
        "label": "Whisper model",
        "hint": "faster-whisper size (tiny/base/small) for the words spot-check.",
    },
    {
        "key": "whisper_min_words",
        "type": "int",
        "label": "Whisper word threshold",
        "hint": "Recognized words in the fragment for the track to count as vocal.",
    },
    {
        "key": "audio_cookies_from_browser",
        "type": "str",
        "label": "Browser for cookies",
        "hint": "yt-dlp takes cookies from this browser (chrome, firefox, brave…; empty — don't use). Empty also enables a manual data/cookies.txt (WSL).",
    },
    {
        "key": "audio_cookies_keyring",
        "type": "str",
        "label": "Password keyring",
        "hint": "Linux only: keyring used to decrypt cookies (basictext, gnomekeyring, kwallet). Ignored on macOS/Windows.",
    },
    {
        "key": "mb_enabled",
        "type": "bool",
        "label": "MusicBrainz artist info",
        "hint": "Fetch artist genres/tags from MusicBrainz (artist page, artists list, recommendations).",
    },
    {
        "key": "mb_cache_days",
        "type": "int",
        "label": "MusicBrainz cache (days)",
        "hint": "How long artist info is kept; \"not found\" rows are retried after 3 days.",
    },
    {
        "key": "mb_prefill_limit",
        "type": "int",
        "label": "MB prefill: top artists per run",
        "hint": "How many top artists the \"Artist genres\" job fetches per run (0 — all).",
    },
]


def _coerce_setting(field: dict, value) -> object:
    kind = field["type"]
    try:
        if kind == "bool":
            coerced = (
                value
                if isinstance(value, bool)
                else str(value).strip().lower()
                in ("1", "true", "yes", "y", "on")
            )
        elif kind == "int":
            coerced = int(value)
        elif kind == "float":
            coerced = float(value)
        else:
            coerced = str(value).strip()
    except (TypeError, ValueError):
        raise HTTPException(422, f"Invalid value for \"{field['label']}\"")
    if field["key"] == "min_play_count" and coerced < 1:
        raise HTTPException(422, "Minimum plays must be at least 1")
    return coerced


def _env_repr(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _update_env_file(updates: dict[str, str]) -> None:
    """Edits existing .env keys in place (case-insensitive), drops
    duplicates of updated keys, and appends new ones at the end."""
    env_path = Path(".env")
    lines = (
        env_path.read_text(encoding="utf-8").splitlines()
        if env_path.exists()
        else []
    )
    lowered = {k.lower() for k in updates}
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        kl = key.lower()
        if kl not in lowered:
            out.append(line)
            continue
        if kl in seen:
            continue
        seen.add(kl)
        val = next(v for k, v in updates.items() if k.lower() == kl)
        out.append(f"{key}={val}")
    for key, val in updates.items():
        if key.lower() not in seen:
            out.append(f"{key}={val}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


@app.get("/api/settings")
def api_settings() -> dict:
    return {
        "fields": [
            {**f, "value": getattr(settings, f["key"])}
            for f in SETTINGS_FIELDS
        ]
    }


@app.post("/api/settings")
def api_save_settings(values: dict = Body(...)) -> dict:
    by_key = {f["key"]: f for f in SETTINGS_FIELDS}
    updates: dict[str, str] = {}
    for key, value in values.items():
        field = by_key.get(key)
        if field is None:
            raise HTTPException(422, f"Unknown setting: {key}")
        coerced = _coerce_setting(field, value)
        setattr(settings, field["key"], coerced)
        updates[key] = _env_repr(coerced)
    if updates:
        _update_env_file(updates)
    return {"ok": True, "saved": sorted(updates)}


if DIST_DIR.is_dir():
    app.mount(
        "/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets"
    )


@app.get("/{full_path:path}")
def spa(full_path: str):
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(404, f"Unknown API route: /{full_path}")
    if DIST_DIR.is_dir():
        dist_root = DIST_DIR.resolve()
        candidate = (DIST_DIR / full_path).resolve()
        if (
            full_path
            and candidate.is_file()
            and candidate.is_relative_to(dist_root)
        ):
            return FileResponse(candidate)
        index = DIST_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
    raise HTTPException(404, "Not Found")
