import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.config import settings
from app.db import engine, init_db
from app.models import AudioFeatures, Cluster, Job, Track
from app.parsers.takeout import load_history_file
from app.services import jobs
from app.services.audio import run_audio_analysis
from app.services.clustering import run_clustering
from app.services.importer import run_import
from app.services.music_filter import run_filter
from app.services.recommend import mb_for_track, similar_tracks
from app.services import stats as stats_svc

APP_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=APP_DIR / "templates")

_workers: dict[str, threading.Thread] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="yt-music-analyzer", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


def _spawn(kind: str, target) -> None:
    t = threading.Thread(target=target, daemon=True, name=f"stage-{kind}")
    _workers[kind] = t
    t.start()


def _base_ctx(session: Session) -> dict:
    totals = stats_svc.totals(session)
    job_rows = session.exec(select(Job).order_by(Job.id)).all()
    latest: dict[str, Job] = {}
    for j in job_rows:
        latest[j.kind] = j
    return {
        "totals": totals,
        "jobs": [latest[k] for k in jobs.KINDS if k in latest],
        "has_api_key": bool(settings.youtube_api_key.strip()),
        "audio_limit": settings.audio_analysis_limit,
    }


def _root_history() -> list[Path]:
    return sorted(
        (p for p in Path(".").glob("*.json") if p.stat().st_size > 100_000),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


@app.get("/")
def index(request: Request):
    with Session(engine) as session:
        ctx = _base_ctx(session)
        roots = _root_history()
        ctx["root_history_exists"] = bool(roots)
        ctx["root_json_name"] = roots[0].name if roots else ""
        return templates.TemplateResponse(request, "index.html", ctx)


@app.post("/import")
async def do_import(
    file: UploadFile | None = File(None), path: str = Form("")
):
    target = ""
    if file is not None and file.filename:
        settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        target = str(settings.uploads_dir / "history.json")
        content = await file.read()
        Path(target).write_bytes(content)
    elif path.strip():
        target = path.strip()
    if not target or not Path(target).exists():
        return RedirectResponse("/?err=file", status_code=303)
    try:
        load_history_file(target)
    except Exception:
        return RedirectResponse("/?err=parse", status_code=303)
    _spawn("import", lambda: run_import(target))
    return RedirectResponse("/", status_code=303)


@app.post("/filter-music")
def do_filter():
    _spawn("filter", run_filter)
    return RedirectResponse("/", status_code=303)


@app.post("/analyze-audio")
def do_audio():
    _spawn("audio", run_audio_analysis)
    return RedirectResponse("/", status_code=303)


@app.post("/cluster-music")
def do_clusters():
    _spawn("clusters", run_clustering)
    return RedirectResponse("/", status_code=303)


@app.get("/partials/jobs")
def partial_jobs(request: Request):
    with Session(engine) as session:
        ctx = _base_ctx(session)
        return templates.TemplateResponse(request, "partials/jobs.html", ctx)


@app.get("/dashboard")
def dashboard(request: Request):
    with Session(engine) as session:
        ctx = _base_ctx(session)
        ctx.update(
            {
                "top_artists": stats_svc.top_artists(session),
                "top_tracks": stats_svc.top_tracks(session),
                "by_hour": stats_svc.by_hour(session),
                "by_weekday": stats_svc.by_weekday(session),
                "by_month": stats_svc.by_month(session),
            }
        )
        return templates.TemplateResponse(request, "dashboard.html", ctx)


@app.get("/moods")
def moods(request: Request):
    with Session(engine) as session:
        ctx = _base_ctx(session)
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
            cards.append({"cluster": c, "tracks": tracks})
        ctx["cards"] = cards
        n_audio = session.exec(
            select(AudioFeatures.track_id).where(  # type: ignore[arg-type]
                AudioFeatures.source == "audio"
            )
        ).all()
        ctx["meta_only"] = totals_audio(ctx) and not n_audio
        return templates.TemplateResponse(request, "moods.html", ctx)


def totals_audio(ctx: dict) -> bool:
    return ctx["totals"]["analyzed"] > 0


@app.get("/recommendations")
def recommendations(request: Request, track_id: str = ""):
    with Session(engine) as session:
        ctx = _base_ctx(session)
        analyzed = session.exec(
            select(AudioFeatures).order_by(AudioFeatures.analyzed_at.desc())
        ).all()
        options = []
        for f in analyzed:
            t = session.get(Track, f.track_id)
            if t is not None:
                options.append({"track": t, "features": f})
        ctx["options"] = options
        ctx["selected_id"] = track_id
        similar: list[dict] = []
        mb_artists: list[dict] = []
        mb_error = ""
        mood_name = ""
        selected = None
        if track_id:
            selected = session.get(Track, track_id)
            similar = similar_tracks(track_id)
            mb_artists, mb_error, mood_name = mb_for_track(track_id)
        ctx.update(
            {
                "selected": selected,
                "similar": similar,
                "mb_artists": mb_artists,
                "mb_error": mb_error,
                "mood_name": mood_name,
            }
        )
        return templates.TemplateResponse(request, "recommendations.html", ctx)
