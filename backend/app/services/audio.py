import json
import subprocess
import threading
import time
from concurrent.futures import (
    FIRST_COMPLETED,
    CancelledError as FuturesCancelledError,
    ThreadPoolExecutor,
    wait,
)
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import librosa
import numpy as np
import yt_dlp
from sqlalchemy import func
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.models import AppMeta, AudioFeatures, Track
from app.services import jobs
from app.services import essentia_feats, essentia_tags
from app.services.clustering import MOOD_COLS

SR = 22050
ANALYZE_SECONDS = 120.0
LONG_PREVIEW_SECONDS = 180.0
MIN_SECONDS = 5.0
HPSS_WINDOW = 30.0
FEAT_VERSION = 6
MAX_WORKERS = 4
MAX_CACHED_WORKERS = 16
RETRY_SLEEPS = (5.0, 15.0, 30.0)
ABORT_NET_ERRORS = 10
BOT_BACKOFF_AFTER = 3      # consecutive bot checks before download pauses kick in
BOT_PAUSE_STEP = 30.0      # first pause and escalation step, seconds
BOT_PAUSE_MAX = 600.0      # pause ceiling
BOT_ABORT_CONSEC = 12      # streak even with pauses — stop the job
COOKIE_MAX_AGE = 6 * 3600  # re-download cookies.txt older than this
POT_URL = "http://127.0.0.1:4416/ping"
POT_SERVER_JS = settings.data_dir / "tools" / "bgutil-pot-server" / "build" / "main.js"

NETWORK_ERROR_MARKERS = (
    "ssl",
    "record_layer",
    "connection",
    "timed out",
    "timeout",
    "reset",
    "network",
    "temporarily unavailable",
    "http error 403",
    "http 403",
    "http error 429",
    "http 429",
    "too many requests",
)

_pot_process: subprocess.Popen | None = None


def _pot_running() -> bool:
    try:
        return httpx.get(POT_URL, timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def ensure_pot_server() -> str:
    if _pot_running():
        return "POT server already running"
    if not POT_SERVER_JS.exists():
        return "POT server not found (data/tools/bgutil-pot-server)"
    global _pot_process
    _pot_process = subprocess.Popen(
        ["node", str(POT_SERVER_JS)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(15):
        if _pot_running():
            return "POT server started"
        time.sleep(1)
    return "POT server failed to start"


def _find_cached(video_id: str) -> Path | None:
    """Looks for the track audio in local cache (prefers a ready wav)."""
    existing = [
        p
        for p in settings.audio_dir.glob(f"{video_id}.*")
        if p.suffix in (".webm", ".m4a", ".opus", ".ogg", ".mp3", ".mkv", ".mp4", ".wav")
    ]
    existing.sort(key=lambda p: p.suffix != ".wav")  # ready wav — no conversion needed
    no_ext = settings.audio_dir / video_id
    if existing:
        return existing[0]
    if no_ext.exists() and no_ext.stat().st_size > 10_000:
        return no_ext
    return None


UNAVAILABLE_KEY = "audio_unavailable"
UNAVAILABLE_TTL = 30  # days until retry

_cookiefile: Path | None = None
_cookiefile_lock = threading.Lock()

_bot_lock = threading.Lock()
_bot_pause_until = 0.0


def _bot_escalate(consec: int) -> float:
    """Download pause after a streak of bot checks (exponential)."""
    global _bot_pause_until
    pause = min(
        BOT_PAUSE_STEP * 2 ** max(0, consec - BOT_BACKOFF_AFTER),
        BOT_PAUSE_MAX,
    )
    with _bot_lock:
        _bot_pause_until = max(_bot_pause_until, time.monotonic() + pause)
    return pause


def _bot_pause_remain() -> float:
    with _bot_lock:
        return max(0.0, _bot_pause_until - time.monotonic())


def _bot_wait(stop: threading.Event, abort: threading.Event) -> None:
    """Download worker waits out the pause (bot throttling)."""
    while not stop.is_set() and not abort.is_set():
        remain = _bot_pause_remain()
        if remain <= 0:
            return
        time.sleep(min(remain, 2.0))


def _prepare_cookies() -> str:
    global _cookiefile
    if not settings.audio_cookies_from_browser:
        return ""
    with _cookiefile_lock:
        path = settings.data_dir / "cookies.txt"
        had = _cookiefile is not None and path.exists()
        if had and time.time() - path.stat().st_mtime < COOKIE_MAX_AGE:
            return ""
        try:
            jar = yt_dlp.cookies.extract_cookies_from_browser(
                settings.audio_cookies_from_browser,
                keyring=settings.audio_cookies_keyring or None,
            )
            jar.save(str(path), ignore_discard=True, ignore_expires=True)
            _cookiefile = path
            return "cookies updated" if had else "cookies cached"
        except Exception as exc:  # noqa: BLE001
            # an old file beats none: on failure keep it as is
            if not had:
                _cookiefile = None
            return f"cookies failed ({str(exc)[:60]})"


def _load_unavailable() -> dict[str, str]:
    with Session(engine) as session:
        row = session.get(AppMeta, UNAVAILABLE_KEY)
    try:
        data = json.loads(row.value) if row else {}
    except Exception:  # noqa: BLE001
        data = {}
    return data if isinstance(data, dict) else {}


def _save_unavailable(data: dict[str, str]) -> None:
    with Session(engine) as session:
        row = session.get(AppMeta, UNAVAILABLE_KEY)
        if row is None:
            row = AppMeta(key=UNAVAILABLE_KEY, value=json.dumps(data))
        else:
            row.value = json.dumps(data)
        session.add(row)
        session.commit()


def _is_unavailable(unav: dict[str, str], vid: str) -> bool:
    stamp = unav.get(vid)
    if not stamp:
        return False
    try:
        return date.fromisoformat(stamp) > date.today() - timedelta(
            days=UNAVAILABLE_TTL
        )
    except ValueError:
        return False


def reset_unavailable() -> int:
    """Forgets the 'marked unavailable' cache so the audio job retries
    those videos. Returns how many marks were cleared."""
    unav = _load_unavailable()
    if not unav:
        return 0
    n = len(unav)
    _save_unavailable({})
    return n


def _classify_dl_error(err: str) -> str:
    low = err.lower()
    if "video unavailable" in low or "this video is not available" in low:
        return "dead"
    if "sign in to confirm" in low or "not a bot" in low:
        return "bot"
    return "other"


def download_audio(video_id: str) -> tuple[Path | None, str]:
    settings.audio_dir.mkdir(parents=True, exist_ok=True)
    cached = _find_cached(video_id)
    if cached is not None:
        return cached, ""
    outtmpl = str(settings.audio_dir / f"{video_id}.%(ext)s")
    opts: dict = {
        "format": "ba[protocol=sabr]/worstaudio/worst",
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 2,
        "socket_timeout": 30,
        "js_runtimes": {"node": {}},
        # no player_client pin: the web client returns no formats at all
        # for some videos (SABR-only experiment) — default clients fall
        # back to https/dash/hls audio
        "extractor_args": {
            "youtube": {
                "formats": ["duplicate"],
            }
        },
    }
    if _cookiefile is not None and _cookiefile.exists():
        opts["cookiefile"] = str(_cookiefile)
    elif settings.audio_cookies_from_browser:
        opts["cookiesfrombrowser"] = (
            settings.audio_cookies_from_browser,
            None,
            None,
            settings.audio_cookies_keyring or None,
        )
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    except yt_dlp.utils.DownloadError as exc:
        return None, str(exc)[:200]
    files = list(settings.audio_dir.glob(f"{video_id}.*"))
    no_ext = settings.audio_dir / video_id
    if no_ext.exists() and no_ext.stat().st_size > 10_000:
        files.append(no_ext)
    return (files[0], "") if files else (None, "file not created")


def _load_audio(path: Path, duration_cap: float | None = None) -> tuple[np.ndarray, int]:
    kwargs: dict = {"sr": SR, "mono": True}
    if duration_cap is not None:
        kwargs["duration"] = duration_cap
    try:
        y, sr = librosa.load(str(path), **kwargs)
    except Exception:
        wav = path.with_suffix(".wav")
        if wav == path:
            # already a wav that librosa cannot read — broken file, no
            # point converting in place: re-raise so it gets deleted
            # and re-downloaded
            raise
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(path), "-ac", "1", "-ar", str(SR), str(wav)],
            capture_output=True,
            timeout=120,
            check=True,
        )
        y, sr = librosa.load(str(wav), **kwargs)
    return y, sr


def _tempo_score(cand: float, onset_env: np.ndarray, sr: int) -> float:
    """BPM candidate score: autocorrelation of the onset envelope at
    multiple lags (1..4) + a soft log-normal prior toward human tempo.

    A doubled (too fast) hypothesis only matches even lags, while the
    true tempo matches all of them.
    """
    n = len(onset_env)
    fps = sr / 512.0  # onset_strength frames per second (hop=512)

    def ac(lag: int) -> float:
        if lag <= 1 or lag >= n - 1:
            return -np.inf
        a = onset_env[: n - lag]
        b = onset_env[lag:]
        denom = np.sqrt(float((a * a).sum()) * float((b * b).sum()))
        if denom <= 0:
            return -np.inf
        return float((a * b).sum()) / denom

    lag = int(round((60.0 / cand) * fps))
    if lag <= 1:
        return -np.inf
    vals = [v for k in (1, 2, 3, 4) if np.isfinite(v := ac(lag * k))]
    if len(vals) < 2:
        return -np.inf
    # base lag outweighs multiples: multiples are more likely to
    # match by chance for a too-fast hypothesis
    combined = 0.6 * vals[0] + 0.4 * float(np.mean(vals[1:]))
    prior = np.exp(-((np.log(cand / 115.0) / 0.7) ** 2))
    return combined + 0.10 * float(prior)


def _tempo_conf(bpm: float, onset_env: np.ndarray, sr: int) -> float:
    """Confidence of the autocorr BPM estimate, normalized to 0..1."""
    return float(np.clip(_tempo_score(bpm, onset_env, sr), 0.0, 1.0))


def _refine_tempo(tempo: float, onset_env: np.ndarray, sr: int) -> float:
    """Fixes octave tempo errors via onset-envelope autocorrelation.

    Candidates (×0.5, ×2, ×2/3, ×3/2, ×3, ×1/3) are scored with
    _tempo_score; an alternative must win by a margin, otherwise
    the original estimate wins.
    """
    candidates = {round(tempo, 1)}
    for factor in (0.5, 2.0, 2.0 / 3.0, 3.0 / 2.0, 3.0, 1.0 / 3.0):
        candidates.add(round(tempo * factor, 1))

    best_t, best_score = tempo, _tempo_score(tempo, onset_env, sr)
    for cand in candidates:
        if not 30.0 <= cand <= 260.0:
            continue
        s = _tempo_score(cand, onset_env, sr)
        if s > best_score + 0.02:
            best_score, best_t = s, cand
    return float(best_t)


def _resolve_tempo(ek: dict, onset_env: np.ndarray, sr: int) -> float:
    """Final BPM: cross-check multifeature against TempoCNN.

    If they agree (gap ≤20%) — take multifeature; if they diverge —
    trust the one with higher confidence (TempoCNN has its own,
    multifeature gets the autocorrelation score). Outside 60–190 —
    octave auto-correction.
    """
    multi = float(ek["bpm_multi"]) if ek.get("bpm_multi") else 0.0
    cnn = float(ek["bpm_cnn"]) if ek.get("bpm_cnn") else 0.0
    if multi > 0 and cnn > 0:
        if abs(multi - cnn) / max(multi, cnn) <= 0.20:
            bpm = multi
        else:
            bpm = (
                multi
                if _tempo_conf(multi, onset_env, sr) >= ek["cnn_conf"]
                else cnn
            )
    elif multi > 0 or cnn > 0:
        bpm = multi or cnn
    else:
        # both model votes missing: grid search on the onset envelope
        grid = np.arange(40.0, 220.0, 0.5)
        scores = [_tempo_score(float(c), onset_env, sr) for c in grid]
        bpm = float(grid[int(np.argmax(scores))])
    if not 60.0 <= bpm <= 190.0:
        bpm = _refine_tempo(bpm, onset_env, sr)
    return float(bpm)


def analyze_audio(path: Path) -> dict:
    # full track up to analyze_full_max, longer ones — preview
    try:
        probe = librosa.get_duration(path=str(path))
    except Exception:  # librosa/libsndfile can't read the container — find out after loading
        probe = None
    cap = None if probe is None or probe <= settings.analyze_full_max else LONG_PREVIEW_SECONDS
    y, sr = _load_audio(path, duration_cap=cap)
    duration = len(y) / sr
    if duration < MIN_SECONDS:
        raise ValueError("audio too short")
    # full file duration: probe is exact; if it failed to read —
    # we loaded without a cap, so duration is the full length
    file_duration = float(probe) if probe is not None else duration

    # onset envelope for BPM cross-check and octave auto-correction
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)

    # Essentia: rhythm (multifeature + TempoCNN), key, dynamics
    audio44 = librosa.resample(y, orig_sr=sr, target_sr=44100)
    y16 = librosa.resample(y, orig_sr=sr, target_sr=16000)[: 16000 * 60]
    ek = essentia_feats.extract_rhythm_key(audio44, y16)
    del audio44
    tempo = _resolve_tempo(ek, onset_env, sr)
    key, mode_conf = ek["key"], ek["strength"]
    loudness = ek["loudness"]
    # energy from the dB scale: -45 dB → 0, 0 dB → 1 (no clipping at the top)
    energy = float(np.clip((loudness + 45.0) / 45.0, 0.0, 1.0))

    # v2: timbre, harmony, mix density (for clustering), percussiveness
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    contrast = librosa.feature.spectral_contrast(y=y, sr=sr)
    mfcc_vec = np.concatenate([mfcc.mean(axis=1), mfcc.std(axis=1)])
    chroma_vec = chroma.mean(axis=1)
    contrast_vec = contrast.mean(axis=1)

    mid = len(y) // 2
    half = int(HPSS_WINDOW * sr / 2)
    y_win = y[max(0, mid - half) : mid + half]
    if len(y_win) < SR * 5:
        y_win = y
    y_harm, y_perc = librosa.effects.hpss(y_win)
    p_e = float(np.sqrt((y_perc * y_perc).mean()))
    h_e = float(np.sqrt((y_harm * y_harm).mean()))
    percussive = float(p_e / (p_e + h_e + 1e-9))

    # Essentia (Discogs-EffNet + heads): genres, styles, instruments,
    # moods, vocals, danceability/acousticness/brightness (models),
    # 1280-dim embedding
    tags = essentia_tags.analyze(y16)

    return {
        "tempo": round(tempo, 1),
        "energy": round(energy, 3),
        "danceability": tags["danceability"],
        "acousticness": tags["acousticness"],
        "brightness": tags["brightness"],
        "key": key,
        "mode_conf": round(mode_conf, 3),
        "analyzed_duration": round(duration, 1),
        "file_duration": round(file_duration, 1),
        "mfcc": json.dumps([round(float(v), 4) for v in mfcc_vec]),
        "chroma": json.dumps([round(float(v), 4) for v in chroma_vec]),
        "contrast": json.dumps([round(float(v), 4) for v in contrast_vec]),
        "dynamics": round(float(np.clip(ek["dynamics"], 0.0, 60.0)), 3),
        "loudness": round(loudness, 1),
        "percussive": round(percussive, 3),
        "tags": json.dumps(tags, ensure_ascii=False, default=float),
        "vocal_ratio": tags["vocal_ratio"],
        "embedding": tags["embedding"],
    }


def _is_network_error(msg: str) -> bool:
    m = (msg or "").lower()
    return any(k in m for k in NETWORK_ERROR_MARKERS)


def download_audio_retried(
    video_id: str, stop: threading.Event | None = None
) -> tuple[Path | None, str]:
    """Download with retries (network errors only): attempts every 5/15/30 s."""
    last = ""
    for sleep_s in (0.0,) + RETRY_SLEEPS:
        if stop is not None and stop.is_set():
            return None, "cancelled by user"
        if sleep_s:
            time.sleep(sleep_s)
        path, err = download_audio(video_id)
        if path is not None:
            return path, ""
        last = err
        if not _is_network_error(err):
            return None, err
    return None, last


def _analyze_file(video_id: str, path: Path) -> tuple[dict | None, str]:
    """Analyze a single audio file; a corrupt cache file is deleted for re-download."""
    try:
        return analyze_audio(path), ""
    except Exception as exc:  # noqa: BLE001
        msg = f"{type(exc).__name__}: {exc}"
        # corrupt/empty cache: delete so the next run re-downloads
        if (
            "LibsndfileError" in msg
            or "audio too short" in msg
            or "NoBackendError" in msg
            or "CalledProcessError" in msg
        ):
            for p in settings.audio_dir.glob(f"{video_id}.*"):
                p.unlink(missing_ok=True)
            if path.exists() and path.suffix == "":
                path.unlink(missing_ok=True)
        return None, msg


def _download_and_analyze(
    video_id: str, abort: threading.Event, stop: threading.Event
) -> tuple[str, dict | None, str]:
    """Worker: download + analysis without DB writes (thread-safe).

    Returns (status, features, error): ok | skipped | dl-error | an-error.
    """
    if abort.is_set() or stop.is_set():
        return "skipped", None, ""
    _bot_wait(stop, abort)
    if abort.is_set() or stop.is_set():
        return "skipped", None, ""
    path, dl_error = download_audio_retried(video_id, stop)
    if path is None:
        if stop.is_set():
            return "skipped", None, ""
        return "dl-error", None, dl_error
    feats, err = _analyze_file(video_id, path)
    if feats is None:
        return "an-error", None, err
    return "ok", feats, ""


def _process_track(
    video_id: str,
    abort: threading.Event,
    stop: threading.Event,
    dl_sem: threading.Semaphore,
) -> tuple[str, dict | None, str, bool]:
    """Worker processing a single track.

    Audio in cache → analyze right away (parallelism: audio_workers_cached);
    otherwise → download (parallelism capped by the audio_workers semaphore).

    Returns (status, features, error, was_cached).
    """
    if abort.is_set() or stop.is_set():
        return "skipped", None, "", False
    cached = _find_cached(video_id)
    if cached is not None:
        feats, err = _analyze_file(video_id, cached)
        if feats is None:
            return "an-error", None, err, True
        return "ok", feats, "", True
    with dl_sem:
        status, feats, err = _download_and_analyze(video_id, abort, stop)
        return status, feats, err, False


def _apply_mood_columns(row: AudioFeatures, tags_json: str) -> None:
    """Fill the mood_* columns from the Essentia tags — the same values
    the clustering stage (compute_moods) derives. Done at analysis time
    so the track card shows correct moods without waiting for a
    clustering re-run."""
    if not tags_json:
        return
    try:
        moods = json.loads(tags_json).get("moods") or {}
    except (ValueError, TypeError):
        return
    for col in MOOD_COLS:
        if moods.get(col) is not None:
            setattr(row, col, round(float(moods[col]), 3))


def _save_features(track_id: str, feats: dict) -> None:
    with Session(engine) as session:
        row = session.get(AudioFeatures, track_id)
        if row is None:
            row = AudioFeatures(track_id=track_id)
        row.source = "audio"
        row.tempo = feats["tempo"]
        row.energy = feats["energy"]
        row.danceability = feats["danceability"]
        row.acousticness = feats["acousticness"]
        row.brightness = feats["brightness"]
        row.key = feats["key"]
        row.mode_conf = feats["mode_conf"]
        row.mfcc = feats["mfcc"]
        row.chroma = feats["chroma"]
        row.contrast = feats["contrast"]
        row.dynamics = feats["dynamics"]
        row.loudness = feats["loudness"]
        row.percussive = feats["percussive"]
        row.tags = feats["tags"]
        row.vocal_ratio = feats["vocal_ratio"]
        row.embedding = feats.get("embedding", "")
        row.feat_version = FEAT_VERSION
        _apply_mood_columns(row, feats["tags"])
        session.add(row)
        # track duration from real audio, if not yet known
        track = session.get(Track, track_id)
        if track is not None and not track.duration and feats.get("file_duration"):
            track.duration = feats["file_duration"]
            session.add(track)
        session.commit()


def run_audio_analysis(stop: threading.Event | None = None) -> None:
    try:
        if not jobs.start_job("audio"):
            return
        stop = stop if stop is not None else threading.Event()
        limit = settings.audio_analysis_limit
        workers = max(1, min(settings.audio_workers, MAX_WORKERS))
        cached_workers = max(
            1, min(settings.audio_workers_cached, MAX_CACHED_WORKERS)
        )
        pot_note = ensure_pot_server()
        cookie_note = _prepare_cookies()
        if cookie_note:
            pot_note = f"{pot_note}; {cookie_note}"
        jobs.progress("audio", 0, 0, f"{pot_note}; checking Essentia models…")
        essentia_tags.ensure_models(
            progress_cb=lambda m: jobs.progress(
                "audio", 0, 0, f"{pot_note}; {m}"
            ),
            should_stop=lambda: jobs.should_stop("audio", stop),
        )
        essentia_feats.ensure_models(
            progress_cb=lambda m: jobs.progress(
                "audio", 0, 0, f"{pot_note}; {m}"
            ),
            should_stop=lambda: jobs.should_stop("audio", stop),
        )
        if jobs.should_stop("audio", stop):
            jobs.stop_job("audio", "stopped by user (during model check)")
            return
        with Session(engine) as session:
            stmt = (
                select(Track)
                .where(
                    Track.is_music == True,  # noqa: E712
                    Track.play_count >= settings.min_play_count,
                )
                .order_by(Track.play_count.desc())
            )
            tracks = session.exec(stmt).all()
            already = session.exec(
                select(func.count()).select_from(AudioFeatures).where(
                    AudioFeatures.source == "audio"
                )
            ).one()
            candidates = [
                (t.video_id, t.title)
                for t in tracks
                if (f := session.get(AudioFeatures, t.video_id)) is None
                or f.source != "audio"
                or f.feat_version < FEAT_VERSION
            ]
            if limit > 0:
                candidates = candidates[:limit]

        unav = _load_unavailable()
        dead_known = {
            vid for vid, _ in candidates if _is_unavailable(unav, vid)
        }
        if dead_known:
            candidates = [
                (v, t) for v, t in candidates if v not in dead_known
            ]
        dead_note = (
            f" ({len(dead_known)} marked unavailable)"
            if dead_known
            else ""
        )

        total = len(candidates)
        n_cached = sum(1 for vid, _ in candidates if _find_cached(vid) is not None)
        # live remainders: decrease as tracks are processed
        cached_left = n_cached
        download_left = total - n_cached

        def counts_prefix() -> str:
            return (
                f"[left: cache {cached_left} · download {download_left}] "
            )

        jobs.progress(
            "audio",
            0,
            total,
            f"{pot_note}; workers: analysis {cached_workers} / download "
            f"{workers}; {counts_prefix()}to analyze: {total} "
            f"(already analyzed: {already}){dead_note}"
            if total
            else f"{pot_note}; no tracks to analyze",
        )

        ok = failed = skipped = 0
        n_dead = n_bot = n_other = 0
        last_error = ""
        consecutive_net = 0
        consecutive_bot = 0
        aborted = False
        aborted_bot = False
        abort = threading.Event()
        dl_sem = threading.Semaphore(workers)

        if total:
            with ThreadPoolExecutor(
                max_workers=max(workers, cached_workers),
                thread_name_prefix="audio",
            ) as pool:
                futures = {
                    pool.submit(_process_track, vid, abort, stop, dl_sem): (
                        vid,
                        title,
                    )
                    for vid, title in candidates
                }
                pending = set(futures)
                done_count = 0
                last_note = "in progress…"
                while pending:
                    # cross-process cancel: DB flag → local events
                    if not stop.is_set() and jobs.should_stop("audio", stop):
                        stop.set()
                        abort.set()
                        # queued tasks are cancelled instantly —
                        # no waiting for each track to start and see the flag
                        for f in list(pending):
                            f.cancel()
                    completed, pending = wait(
                        pending, return_when=FIRST_COMPLETED, timeout=5.0
                    )
                    if not completed:
                        # heartbeat: tracks still counting, job is alive
                        bp = _bot_pause_remain()
                        extra = (
                            f"; download pause {int(bp)}s (bot checks)"
                            if bp > 0
                            else ""
                        )
                        jobs.progress(
                            "audio",
                            done_count,
                            total,
                            f"{counts_prefix()}{last_note}{extra} "
                            f"(in flight: {len(pending)})",
                        )
                        continue
                    for fut in completed:
                        vid, title = futures[fut]
                        try:
                            status, feats, err, from_cache = fut.result()
                        except FuturesCancelledError:
                            # cancelled on stop: not an error
                            done_count += 1
                            skipped += 1
                            continue
                        done_count += 1
                        if status != "skipped":
                            if from_cache:
                                cached_left -= 1
                            else:
                                download_left -= 1
                        note = ""
                        if status == "ok":
                            consecutive_net = 0
                            consecutive_bot = 0
                            _save_features(vid, feats)
                            ok += 1
                            note = (
                                f"{ok} done, {failed} errors; last: "
                                f"{title[:50]} "
                                f"({feats['tempo']:.0f} BPM, {feats['key']})"
                            )
                        elif status == "skipped":
                            skipped += 1
                            if stop.is_set() or abort.is_set():
                                note = (
                                    f"{ok} done, {failed} errors; "
                                    "stopped by user"
                                )
                            else:
                                failed += 1
                                note = (
                                    f"{ok} done, {failed} errors; skipped "
                                    "after a streak of network errors"
                                )
                        elif status == "dl-error":
                            failed += 1
                            last_error = err
                            kind = _classify_dl_error(err)
                            note = None
                            if kind == "dead":
                                n_dead += 1
                                unav[vid] = date.today().isoformat()
                            elif kind == "bot":
                                n_bot += 1
                                consecutive_bot += 1
                                if abort.is_set():
                                    pause = _bot_pause_remain()
                                else:
                                    pause = _bot_escalate(consecutive_bot)
                                    if consecutive_bot >= BOT_ABORT_CONSEC:
                                        abort.set()
                                        aborted_bot = True
                                note = (
                                    f"{ok} done, {failed} errors; last: "
                                    f"{title[:40]} — bot check, download "
                                    f"pause {int(pause)}s"
                                )
                            else:
                                n_other += 1
                            if _is_network_error(err):
                                consecutive_net += 1
                                if (
                                    consecutive_net >= ABORT_NET_ERRORS
                                    and not abort.is_set()
                                ):
                                    abort.set()
                                    aborted = True
                            if note is None:
                                note = (
                                    f"{ok} done, {failed} errors; last: "
                                    f"{title[:40]} — {err[:80]}"
                                )
                        else:
                            failed += 1
                            last_error = err or "analysis error"
                            note = (
                                f"{ok} done, {failed} errors; last: "
                                f"analysis error {title[:40]} — {err[:60]}"
                            )
                        if settings.audio_delete_after:
                            for p in settings.audio_dir.glob(f"{vid}.*"):
                                p.unlink(missing_ok=True)
                        last_note = note
                        jobs.progress(
                            "audio", done_count, total, counts_prefix() + note
                        )

        if n_dead:
            _save_unavailable(unav)
        parts = []
        if n_dead:
            parts.append(
                f"unavailable (deleted/geo): {n_dead} — marked, "
                f"retry in {UNAVAILABLE_TTL} days"
            )
        if n_bot:
            parts.append(
                f"bot checks: {n_bot} — check VPN/cookies"
            )
        if n_other:
            parts.append(f"other errors: {n_other}")
        detail = (
            f"analyzed {ok}, errors {failed}, skipped {skipped} "
            f"(total in DB: {already + ok}; workers: {workers})"
        )
        if parts:
            detail += "; " + "; ".join(parts)
        if jobs.should_stop("audio", stop):
            jobs.stop_job("audio", detail=f"{detail}; stopped by user")
            return
        if aborted:
            detail += (
                f"; stopped: {ABORT_NET_ERRORS} network errors in a row — "
                "YouTube is throttling the IP, run again later"
            )
        if aborted_bot:
            detail += (
                f"; stopped: {BOT_ABORT_CONSEC} bot checks in a row even "
                "after pauses — YouTube has limited the IP/session; wait "
                "30–60 min, switch VPN exit or refresh cookies"
            )
        if last_error:
            detail += f"; last error: {last_error[:150]}"
        jobs.finish_job("audio", detail=detail)
    except Exception as exc:  # noqa: BLE001
        jobs.fail_job("audio", f"{type(exc).__name__}: {exc}")
        raise


# --- on-demand analysis of a single track (button in the track card) ---

SINGLE_KEY_PREFIX = "analyze_one"
SINGLE_STALE_AFTER = timedelta(minutes=30)
# only one manual analysis at a time (downloads/models are shared state)
_single_lock = threading.Lock()


def _set_one_status(video_id: str, status: str, detail: str = "") -> None:
    with Session(engine) as session:
        session.merge(
            AppMeta(
                key=f"{SINGLE_KEY_PREFIX}:{video_id}",
                value=json.dumps(
                    {
                        "status": status,
                        "detail": detail,
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                ),
            )
        )
        session.commit()


def analyze_one_status(video_id: str) -> dict:
    """Manual analysis state for the track card UI: {} (never run),
    {status: running|done|error, detail}."""
    with Session(engine) as session:
        row = session.get(AppMeta, f"{SINGLE_KEY_PREFIX}:{video_id}")
    if row is None:
        return {}
    try:
        data = json.loads(row.value)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get("status") == "running":
        # the thread died with a server restart — do not spin forever
        try:
            started = datetime.fromisoformat(str(data.get("updated_at")))
            if datetime.utcnow() - started > SINGLE_STALE_AFTER:
                return {
                    "status": "error",
                    "detail": "analysis stalled (server restarted?)",
                }
        except (ValueError, TypeError):
            pass
    return data


def analyze_track_now(video_id: str) -> tuple[bool, str]:
    """Download (if needed) and analyze one track on demand.
    Runs in a background thread; the UI polls analyze_one_status()."""
    if not _single_lock.acquire(blocking=False):
        return False, "another manual analysis is already running"
    try:
        _set_one_status(video_id, "running")
        try:
            ensure_pot_server()
            _prepare_cookies()
            essentia_tags.ensure_models()
            essentia_feats.ensure_models()
            status, feats, err, _ = _process_track(
                video_id,
                threading.Event(),
                threading.Event(),
                threading.Semaphore(1),
            )
        except Exception as exc:  # noqa: BLE001
            detail = f"{type(exc).__name__}: {exc}"
            _set_one_status(video_id, "error", detail[:300])
            return False, detail
        if status == "ok":
            _save_features(video_id, feats)
            # prefetch YouTube Music data (album/year/thumbnail + native
            # "radio" similar) so the track card is complete right after
            # the analysis, without a manual visit
            try:
                from app.services import ytmusic

                with Session(engine) as session:
                    track = session.get(Track, video_id)
                    title = track.title if track is not None else ""
                ytmusic.similar(video_id, title)
            except Exception:  # noqa: BLE001
                # a bonus, not a part of the analysis result
                pass
            _set_one_status(video_id, "done")
            return True, ""
        detail = err or status
        if status == "dl-error" and _classify_dl_error(detail) == "dead":
            # same marking as the batch job: retry in UNAVAILABLE_TTL days
            unav = _load_unavailable()
            unav[video_id] = date.today().isoformat()
            _save_unavailable(unav)
        _set_one_status(video_id, "error", detail[:300])
        return False, detail
    finally:
        _single_lock.release()
