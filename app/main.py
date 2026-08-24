import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

from app.config import settings
from app.db import engine, init_db
from app.models import AudioFeatures, Cluster, Job, Track
from app.parsers.takeout import load_history_file
from app.services import jobs as jobs_svc
from app.services.audio import run_audio_analysis
from app.services.clustering import run_clustering
from app.services.importer import run_import
from app.services.music_filter import run_filter
from app.services.recommend import mb_for_track, similar_tracks
from app.services import stats as stats_svc

DIST_DIR = Path(__file__).resolve().parent.parent / "dist"

_workers: dict[str, threading.Thread] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="yt-music-analyzer", lifespan=lifespan)


def _spawn(kind: str, target) -> None:
    t = threading.Thread(target=target, daemon=True, name=f"stage-{kind}")
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
    _spawn("import", lambda: run_import(target))
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
        n_audio = session.exec(
            select(AudioFeatures.track_id).where(  # type: ignore[arg-type]
                AudioFeatures.source == "audio"
            )
        ).all()
        return {
            "meta_only": totals["analyzed"] > 0 and not n_audio,
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
        if track_id:
            t = session.get(Track, track_id)
            if t is not None:
                selected = _track_payload(t)
            similar = [
                {
                    "track": _track_payload(s["track"]),
                    "distance": s["distance"],
                    "tempo": s["tempo"],
                }
                for s in similar_tracks(track_id)
            ]
            mb_artists, mb_error, mood_name = mb_for_track(track_id)
        return {
            "options": options,
            "selected": selected,
            "similar": similar,
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
