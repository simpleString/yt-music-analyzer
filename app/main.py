import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.config import settings
from app.db import engine, init_db
from app.models import AudioFeatures, Cluster, Job, Listen, Lyrics, Track
from app.parsers.takeout import load_history_file
from app.services import jobs as jobs_svc
from app.services.audio import run_audio_analysis
from app.services.clustering import run_clustering
from app.services.importer import run_import
from app.services.lyrics import run_lyrics
from app.services.music_filter import run_filter
from app.services.recommend import (
    mb_for_track,
    similar_artists,
    similar_tracks,
    similar_tracks_v2,
)
from app.services import stats as stats_svc

DIST_DIR = Path(__file__).resolve().parent.parent / "dist"

_workers: dict[str, threading.Thread] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


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
        "play_count": t.play_count,
    }


def _job_payload(job: Job) -> dict:
    return {
        "kind": job.kind,
        "status": job.status,
        "total": job.total,
        "done": job.done,
        "detail": job.detail,
        "error": job.error,
    }


def _root_history() -> list[Path]:
    return sorted(
        (p for p in Path(".").glob("*.json") if p.stat().st_size > 100_000),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _state_payload(session: Session) -> dict:
    totals = stats_svc.totals(session)
    job_rows = session.exec(select(Job).order_by(Job.id)).all()
    latest: dict[str, Job] = {}
    for j in job_rows:
        latest[j.kind] = j
    roots = _root_history()
    return {
        "totals": totals,
        "jobs": [
            _job_payload(latest[k]) for k in jobs_svc.KINDS if k in latest
        ],
        "has_api_key": bool(settings.youtube_api_key.strip()),
        "audio_limit": settings.audio_analysis_limit,
        "root_history_exists": bool(roots),
        "root_json_name": roots[0].name if roots else "",
    }


@app.get("/api/state")
def api_state() -> dict:
    with Session(engine) as session:
        return _state_payload(session)


@app.post("/api/import")
async def api_import(
    file: UploadFile | None = File(None), path: str = Form("")
) -> dict:
    target = ""
    if file is not None and file.filename:
        settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        target = str(settings.uploads_dir / "history.json")
        Path(target).write_bytes(await file.read())
    elif path.strip():
        target = path.strip()
    if not target or not Path(target).exists():
        raise HTTPException(
            400,
            "Файл не найден. Загрузите JSON истории или укажите корректный путь.",
        )
    try:
        load_history_file(target)
    except Exception:
        raise HTTPException(
            400,
            "Не удалось разобрать JSON. Нужен файл «История просмотров "
            "YouTube» из Google Takeout.",
        )
    _spawn("import", lambda stop: run_import(target, stop))
    return {"ok": True}


@app.post("/api/pipeline/filter")
def api_pipeline_filter() -> dict:
    _spawn("filter", run_filter)
    return {"ok": True}


@app.post("/api/pipeline/audio")
def api_pipeline_audio() -> dict:
    _spawn("audio", run_audio_analysis)
    return {"ok": True}


@app.post("/api/pipeline/clusters")
def api_pipeline_clusters() -> dict:
    _spawn("clusters", run_clustering)
    return {"ok": True}


@app.post("/api/pipeline/lyrics")
def api_pipeline_lyrics() -> dict:
    _spawn("lyrics", run_lyrics)
    return {"ok": True}


def _date_str(v) -> str | None:
    if v is None:
        return None
    return v[:10] if isinstance(v, str) else v.date().isoformat()


def _f(v: float | None, nd: int = 2) -> float | None:
    return round(v, nd) if v is not None else None


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
    instrumental: bool = False,
) -> dict:
    import json as _json

    per_page = max(1, min(per_page, 500))
    page = max(1, page)
    if sort not in ("play_count", "first_listen", "last_listen"):
        sort = "play_count"
    if order not in ("asc", "desc"):
        order = "desc"
    conditions = [Track.is_music == (not hidden)]  # noqa: E712
    term = q.strip().lower()
    if term:
        like = f"%{term}%"
        conditions.append(
            or_(
                func.lower(Track.title).like(like),
                func.lower(Track.channel).like(like),
            )
        )
    if cluster_id is not None:
        conditions.append(Track.cluster_id == cluster_id)
    if genre:
        conditions.append(
            AudioFeatures.tags.like(f'%"{genre}"%')  # type: ignore[union-attr]
        )
    if instrumental:
        conditions.append(
            (AudioFeatures.vocal_ratio < settings.lyrics_min_vocal)  # type: ignore[operator]
        )
    if language:
        conditions.append(Lyrics.language == language)

    first_listen = func.min(Listen.listened_at).label("first_listen")
    last_listen = func.max(Listen.listened_at).label("last_listen")
    sort_col = {
        "play_count": Track.play_count,
        "first_listen": first_listen,
        "last_listen": last_listen,
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
                        "mood_epic": _f(f.mood_epic, 3),
                        "mood_dark": _f(f.mood_dark, 3),
                        "mood_romantic": _f(f.mood_romantic, 3),
                        "mood_atmospheric": _f(f.mood_atmospheric, 3),
                        "features_source": f.source,
                        "vocal_ratio": _f(f.vocal_ratio, 3),
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
        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "tracks": tracks,
        }


@app.get("/api/clusters")
def api_clusters() -> list[dict]:
    with Session(engine) as session:
        clusters = session.exec(
            select(Cluster).order_by(Cluster.size.desc())
        ).all()
        return [
            {"id": c.id, "name": c.name, "size": c.size} for c in clusters
        ]


@app.post("/api/tracks/{video_id}/classify")
def api_classify_track(video_id: str, is_music: bool = Body(..., embed=True)) -> dict:
    with Session(engine) as session:
        track = session.get(Track, video_id)
        if track is None:
            raise HTTPException(404, "Трек не найден")
        track.is_music = is_music
        track.music_reason = "manual"
        session.add(track)
        session.commit()
        return {"ok": True, "video_id": video_id, "is_music": is_music}


@app.post("/api/channels/hide")
def api_hide_channel(channel: str = Body(..., embed=True)) -> dict:
    channel = channel.strip()
    if not channel:
        raise HTTPException(400, "Пустое имя канала")
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


@app.get("/api/tracks/{video_id}/lyrics")
def api_track_lyrics(video_id: str) -> dict:
    with Session(engine) as session:
        row = session.get(Lyrics, video_id)
        if row is None or not row.text:
            raise HTTPException(404, "Текст не найден")
        return {
            "track_id": video_id,
            "text": row.text,
            "synced": row.synced,
            "language": row.language,
            "sentiment": row.sentiment,
        }


@app.post("/api/jobs/{kind}/cancel")
def api_cancel_job(kind: str) -> dict:
    if kind not in jobs_svc.KINDS:
        raise HTTPException(404, "Неизвестный тип задания")
    ok = jobs_svc.request_cancel(kind)
    if not ok:
        raise HTTPException(409, "Задание не выполняется")
    return {"ok": True, "kind": kind}


@app.get("/api/dashboard")
def api_dashboard() -> dict:
    with Session(engine) as session:
        return {
            "totals": stats_svc.totals(session),
            "top_artists": stats_svc.top_artists(session),
            "top_tracks": stats_svc.top_tracks(session),
            "by_hour": stats_svc.by_hour(session),
            "by_weekday": stats_svc.by_weekday(session),
            "by_month": stats_svc.by_month(session),
        }


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
        similar: list[dict] = []
        mb_artists: list[dict] = []
        mb_error = ""
        mood_name = ""
        sim_artists: list[dict] | None = None
        if track_id:
            t = session.get(Track, track_id)
            if t is not None:
                selected = _track_payload(t)
            v2 = similar_tracks_v2(track_id)
            if v2 is not None:
                similar = [
                    {
                        "track": _track_payload(s["track"]),
                        "distance": s["distance"],
                        "tempo": s["tempo"],
                        "match": s["match"],
                    }
                    for s in v2
                ]
            else:
                similar = [
                    {
                        "track": _track_payload(s["track"]),
                        "distance": s["distance"],
                        "tempo": s["tempo"],
                        "match": "",
                    }
                    for s in similar_tracks(track_id)
                ]
            sim_artists = similar_artists(track_id)
            mb_artists, mb_error, mood_name = mb_for_track(track_id)
        return {
            "options": options,
            "selected": selected,
            "similar": similar,
            "similar_artists": sim_artists,
            "mb_artists": mb_artists,
            "mb_error": mb_error,
            "mood_name": mood_name,
        }


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
