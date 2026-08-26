import json
import subprocess
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import httpx
import librosa
import numpy as np
import yt_dlp
from sqlalchemy import func
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.models import AudioFeatures, Track
from app.services import jobs

SR = 22050
ANALYZE_SECONDS = 120.0
LONG_PREVIEW_SECONDS = 180.0
MIN_SECONDS = 5.0
HPSS_WINDOW = 30.0
FEAT_VERSION = 3
MAX_WORKERS = 4
RETRY_SLEEPS = (5.0, 15.0, 30.0)
ABORT_NET_ERRORS = 10
POT_URL = "http://127.0.0.1:4416/ping"
POT_SERVER_JS = settings.data_dir / "tools" / "bgutil-pot-server" / "build" / "main.js"

# --- YAMNet (AudioSet, 521 класс): жанры, инструменты, вокал ---
YAMNET_DIR = settings.data_dir / "models"
YAMNET_FILES = ("model.onnx", "model.data", "yamnet_class_map.csv")
YAMNET_URL = "https://huggingface.co/anchor-flux/yamnet-onnx/resolve/main"

YAMNET_GENRES = (
    "Rock music", "Pop music", "Hip hop music", "Electronic music",
    "Heavy metal", "Jazz", "Classical music", "Country music", "Reggae",
    "Rhythm and blues", "Folk music", "Punk rock", "Disco", "Techno",
    "House music", "Drum and bass", "Funk", "Soul music", "Ambient music",
    "Trance music", "Electronic dance music", "Dance music",
    "Soundtrack music", "Video game music", "Independent music",
    "New-age music", "Ska", "Swing music", "Opera", "Bluegrass",
    "Flamenco", "Gospel music", "Rock and roll", "Vocal music",
)
YAMNET_INSTRUMENTS = (
    "Guitar", "Electric guitar", "Acoustic guitar", "Bass guitar", "Piano",
    "Electric piano", "Drum kit", "Drum machine", "Drum", "Percussion",
    "Snare drum", "Synthesizer", "Keyboard (musical)", "Organ",
    "Hammond organ", "Electronic organ", "Violin, fiddle", "Cello",
    "Double bass", "Brass instrument", "Trumpet", "Trombone", "Saxophone",
    "Flute", "Clarinet", "Harp", "Banjo", "Ukulele", "Harmonica",
    "Marimba, xylophone", "Harpsichord", "Mallet percussion",
)
YAMNET_VOCAL = (
    "Singing", "Choir", "Rapping", "Vocal music", "Synthetic singing",
    "A capella", "Humming", "Child singing", "Yodeling",
)

_yamnet_session = None
_yamnet_names: list[str] | None = None


def ensure_yamnet() -> bool:
    """Загружает ONNX-модель и классмап при первом обращении (однократно)."""
    global _yamnet_session, _yamnet_names
    if _yamnet_session is not None:
        return True
    if not all((YAMNET_DIR / f).exists() for f in YAMNET_FILES):
        try:
            YAMNET_DIR.mkdir(parents=True, exist_ok=True)
            with httpx.Client(timeout=180, follow_redirects=True) as client:
                for fname in YAMNET_FILES:
                    resp = client.get(f"{YAMNET_URL}/{fname}")
                    resp.raise_for_status()
                    (YAMNET_DIR / fname).write_bytes(resp.content)
        except Exception:
            return False
    if not YAMNET_DIR.joinpath("model.onnx").exists():
        return False
    try:
        import csv as _csv

        import onnxruntime as ort

        _yamnet_session = ort.InferenceSession(
            str(YAMNET_DIR / "model.onnx"), providers=["CPUExecutionProvider"]
        )
        with open(YAMNET_DIR / "yamnet_class_map.csv") as fh:
            _yamnet_names = [r["display_name"] for r in _csv.DictReader(fh)]
        return True
    except Exception:
        _yamnet_session = None
        return False


def yamnet_tags(y16: np.ndarray) -> dict | None:
    """Теги трека по сигналу 16 кГц: жанры, инструменты, вокал, mood-скоры."""
    if not ensure_yamnet():
        return None
    names = _yamnet_names or []
    idx = {n: i for i, n in enumerate(names)}
    if len(y16) < 16000:
        y16 = np.pad(y16, (0, 16000 - len(y16)))
    S = np.abs(librosa.stft(y16, n_fft=512, hop_length=160, win_length=400))
    mel = librosa.feature.melspectrogram(
        S=S, sr=16000, n_mels=64, fmin=125, fmax=7500, htk=True, norm=None
    )
    logmel = np.log(mel + 0.001)
    scores: list[np.ndarray] = []
    for i in range(0, max(1, logmel.shape[1] - 95), 48):
        patch = logmel[:, i : i + 96].T.astype(np.float32)[None, None]
        scores.append(_yamnet_session.run(None, {"audio": patch})[0][0])
    if not scores:
        return None
    probs = 1.0 / (1.0 + np.exp(-np.mean(scores, axis=0)))

    def top(pool: tuple[str, ...], k: int) -> list[dict]:
        scored = [(n, float(probs[idx[n]])) for n in pool if n in idx]
        scored.sort(key=lambda x: -x[1])
        return [{"name": n, "score": round(s, 3)} for n, s in scored[:k]]

    vocal = max((float(probs[idx[n]]) for n in YAMNET_VOCAL if n in idx), default=0.0)
    moods = {
        n: round(float(probs[idx[n]]), 3)
        for n in ("Happy music", "Sad music", "Tender music", "Exciting music", "Scary music")
        if n in idx
    }
    return {
        "genres": top(YAMNET_GENRES, 3),
        "instruments": top(YAMNET_INSTRUMENTS, 4),
        "moods": moods,
        "vocal_ratio": round(min(vocal, 1.0), 3),
    }


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
        return "POT-сервер уже запущен"
    if not POT_SERVER_JS.exists():
        return "POT-сервер не найден (data/tools/bgutil-pot-server)"
    global _pot_process
    _pot_process = subprocess.Popen(
        ["node", str(POT_SERVER_JS)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(15):
        if _pot_running():
            return "POT-сервер запущен"
        time.sleep(1)
    return "POT-сервер не поднялся"

KK_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def download_audio(video_id: str) -> tuple[Path | None, str]:
    settings.audio_dir.mkdir(parents=True, exist_ok=True)
    existing = [
        p
        for p in settings.audio_dir.glob(f"{video_id}.*")
        if p.suffix in (".webm", ".m4a", ".opus", ".ogg", ".mp3", ".mkv", ".mp4", ".wav")
    ]
    existing.sort(key=lambda p: p.suffix != ".wav")  # готовый wav — без конвертации
    no_ext = settings.audio_dir / video_id
    if existing:
        return existing[0], ""
    if no_ext.exists() and no_ext.stat().st_size > 10_000:
        return no_ext, ""
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
        "extractor_args": {
            "youtube": {
                "formats": ["duplicate"],
                "player_client": ["web"],
                "webpage_client": "web",
            }
        },
    }
    if settings.audio_cookies_from_browser:
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
    if no_ext.exists() and no_ext.stat().st_size > 10_000:
        files.append(no_ext)
    return (files[0], "") if files else (None, "файл не создан")


def _load_audio(path: Path, duration_cap: float | None = None) -> tuple[np.ndarray, int]:
    kwargs: dict = {"sr": SR, "mono": True}
    if duration_cap is not None:
        kwargs["duration"] = duration_cap
    try:
        y, sr = librosa.load(str(path), **kwargs)
    except Exception:
        wav = path.with_suffix(".wav")
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(path), "-ac", "1", "-ar", str(SR), str(wav)],
            capture_output=True,
            timeout=120,
            check=True,
        )
        y, sr = librosa.load(str(wav), **kwargs)
    return y, sr


def detect_key(y: np.ndarray, sr: int) -> tuple[str, float]:
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)
    best = (-2.0, 0, "major")
    for shift in range(12):
        for profile, mode in ((KK_MAJ, "major"), (KK_MIN, "minor")):
            rotated = np.roll(profile, shift)
            r = float(np.corrcoef(chroma, rotated)[0, 1])
            if np.isnan(r):
                continue
            if r > best[0]:
                best = (r, shift, mode)
    conf = float(np.clip(best[0], 0.0, 1.0))
    return f"{NOTE_NAMES[best[1]]} {best[2]}", conf


def _refine_tempo(tempo: float, onset_env: np.ndarray, sr: int) -> float:
    """Чинит октавные ошибки beat tracking по автокорреляции onset-огибающей.

    Альтернатива должна выиграть с запасом (×1.12) — иначе полутона темпа
    побеждают из-за периодичности бита на 2× лаге.
    """
    candidates = {round(tempo, 1)}
    for factor in (0.5, 2.0, 2.0 / 3.0, 3.0 / 2.0):
        candidates.add(round(tempo * factor, 1))

    def score(cand: float) -> float:
        period = 60.0 / cand
        lag = int(period * sr / 512)  # hop = 512 у onset_strength
        if lag <= 1 or lag >= len(onset_env) - 1:
            return -np.inf
        a = onset_env[: len(onset_env) - lag]
        b = onset_env[lag:]
        denom = np.sqrt(float((a * a).sum()) * float((b * b).sum()))
        if denom <= 0:
            return -np.inf
        autocorr = float((a * b).sum()) / denom
        # мягкий приоритет человеческому диапазону темпа
        prior = np.exp(-(((cand - 120.0) / 70.0) ** 2))
        return autocorr + 0.08 * prior

    base = score(tempo)
    best_t, best_score = tempo, base
    for cand in candidates:
        if not 40.0 <= cand <= 250.0:
            continue
        s = score(cand)
        if s > best_score and (cand == tempo or s > base * 1.12):
            best_score, best_t = s, cand
    return float(best_t)


def analyze_audio(path: Path) -> dict:
    # полный трек до analyze_full_max, длиннее — превью
    try:
        probe = librosa.get_duration(path=str(path))
    except Exception:  # librosa/libsndfile не читает контейнер — узнаем после загрузки
        probe = None
    cap = None if probe is None or probe <= settings.analyze_full_max else LONG_PREVIEW_SECONDS
    y, sr = _load_audio(path, duration_cap=cap)
    duration = len(y) / sr
    if duration < MIN_SECONDS:
        raise ValueError("аудио слишком короткое")

    rms_frame = librosa.feature.rms(y=y)
    rms = float(rms_frame.mean())
    centroid = float(librosa.feature.spectral_centroid(y=y, sr=sr).mean())
    flatness = float(librosa.feature.spectral_flatness(y=y).mean())
    zcr = float(librosa.feature.zero_crossing_rate(y=y).mean())
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, units="time")
    onset_rate = float(len(onsets) / duration)
    tempo, beats = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
    tempo = float(np.atleast_1d(tempo)[0])
    tempo = _refine_tempo(tempo, onset_env, sr)
    beat_times = librosa.frames_to_time(beats, sr=sr)
    ibi = np.diff(beat_times)
    if len(ibi) > 2 and float(ibi.mean()) > 0:
        ibi_cv = float(ibi.std() / ibi.mean())
    else:
        ibi_cv = 1.5
    beat_regularity = 1.0 / (1.0 + 3.0 * ibi_cv)
    tempo_window = float(np.exp(-(((tempo - 115.0) / 35.0) ** 2)))

    key, mode_conf = detect_key(y, sr)

    # v2: тембр, гармония, плотность микса, динамика, громкость, перкуссивность
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    contrast = librosa.feature.spectral_contrast(y=y, sr=sr)
    mfcc_vec = np.concatenate([mfcc.mean(axis=1), mfcc.std(axis=1)])
    chroma_vec = chroma.mean(axis=1)
    contrast_vec = contrast.mean(axis=1)
    dynamics = float(np.clip(rms_frame.std() / (rms + 1e-9), 0.0, 4.0))
    loudness = float(20.0 * np.log10(rms + 1e-9))

    mid = len(y) // 2
    half = int(HPSS_WINDOW * sr / 2)
    y_win = y[max(0, mid - half) : mid + half]
    if len(y_win) < SR * 5:
        y_win = y
    y_harm, y_perc = librosa.effects.hpss(y_win)
    p_e = float(np.sqrt((y_perc * y_perc).mean()))
    h_e = float(np.sqrt((y_harm * y_harm).mean()))
    percussive = float(p_e / (p_e + h_e + 1e-9))

    # YAMNet: жанры, инструменты, вокал (на 16 кГц, первые 60 с)
    y16 = librosa.resample(y, orig_sr=sr, target_sr=16000)[: 16000 * 60]
    tags = yamnet_tags(y16)

    # энергия из дБ-шкалы: -45 дБ → 0, 0 дБ → 1 (без клипа в потолок)
    energy = float(np.clip((loudness + 45.0) / 45.0, 0.0, 1.0))
    danceability = float(
        np.clip(0.8 * beat_regularity + 0.2 * tempo_window, 0.0, 1.0)
    )
    acousticness = float(
        np.clip(0.9 - 2.5 * flatness, 0.0, 1.0) * np.clip(1.2 - zcr / 0.15, 0.0, 1.0)
    )
    brightness = float(np.clip(centroid / 4000.0, 0.0, 1.0))

    return {
        "tempo": round(tempo, 1),
        "energy": round(energy, 3),
        "danceability": round(danceability, 3),
        "acousticness": round(acousticness, 3),
        "brightness": round(brightness, 3),
        "onset_rate": onset_rate,
        "key": key,
        "mode_conf": round(mode_conf, 3),
        "analyzed_duration": round(duration, 1),
        "mfcc": json.dumps([round(float(v), 4) for v in mfcc_vec]),
        "chroma": json.dumps([round(float(v), 4) for v in chroma_vec]),
        "contrast": json.dumps([round(float(v), 4) for v in contrast_vec]),
        "dynamics": round(dynamics, 3),
        "loudness": round(loudness, 1),
        "percussive": round(percussive, 3),
        "tags": json.dumps(tags, ensure_ascii=False) if tags else "",
        "vocal_ratio": tags["vocal_ratio"] if tags else None,
    }


def _is_network_error(msg: str) -> bool:
    m = (msg or "").lower()
    return any(k in m for k in NETWORK_ERROR_MARKERS)


def download_audio_retried(
    video_id: str, stop: threading.Event | None = None
) -> tuple[Path | None, str]:
    """Скачивание с ретраями (только сетевые ошибки): попытки через 5/15/30 с."""
    last = ""
    for sleep_s in (0.0,) + RETRY_SLEEPS:
        if stop is not None and stop.is_set():
            return None, "отменено пользователем"
        if sleep_s:
            time.sleep(sleep_s)
        path, err = download_audio(video_id)
        if path is not None:
            return path, ""
        last = err
        if not _is_network_error(err):
            return None, err
    return None, last


def _download_and_analyze(
    video_id: str, abort: threading.Event, stop: threading.Event
) -> tuple[str, dict | None, str]:
    """Воркер: скачивание + анализ без записи в БД (потокобезопасно).

    Возвращает (статус, фичи, ошибка): ok | skipped | dl-error | an-error.
    """
    if abort.is_set() or stop.is_set():
        return "skipped", None, ""
    path, dl_error = download_audio_retried(video_id, stop)
    if path is None:
        if stop.is_set():
            return "skipped", None, ""
        return "dl-error", None, dl_error
    try:
        feats = analyze_audio(path)
    except Exception as exc:  # noqa: BLE001
        msg = f"{type(exc).__name__}: {exc}"
        # битый/пустой кэш: удаляем, чтобы следующий запуск перекачал
        if (
            "LibsndfileError" in msg
            or "аудио слишком короткое" in msg
            or "NoBackendError" in msg
        ):
            for p in settings.audio_dir.glob(f"{video_id}.*"):
                p.unlink(missing_ok=True)
            if path.exists() and path.suffix == "":
                path.unlink(missing_ok=True)
        return "an-error", None, msg
    return "ok", feats, ""


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
        row.feat_version = FEAT_VERSION
        session.add(row)
        session.commit()


def run_audio_analysis(stop: threading.Event | None = None) -> None:
    try:
        if not jobs.start_job("audio"):
            return
        stop = stop if stop is not None else threading.Event()
        limit = settings.audio_analysis_limit
        workers = max(1, min(settings.audio_workers, MAX_WORKERS))
        pot_note = ensure_pot_server()
        with Session(engine) as session:
            stmt = (
                select(Track)
                .where(Track.is_music == True)  # noqa: E712
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

        total = len(candidates)
        jobs.progress(
            "audio",
            0,
            total,
            f"{pot_note}; воркеров: {workers}; к анализу: {total} "
            f"(уже проанализировано: {already})"
            if total
            else f"{pot_note}; нет треков для анализа",
        )

        ok = failed = skipped = 0
        last_error = ""
        consecutive_net = 0
        aborted = False
        abort = threading.Event()

        if total:
            with ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="audio"
            ) as pool:
                futures = {
                    pool.submit(_download_and_analyze, vid, abort, stop): (
                        vid,
                        title,
                    )
                    for vid, title in candidates
                }
                pending = set(futures)
                done_count = 0
                while pending:
                    # кросс-процессная отмена: флаг в БД → локальные события
                    if not stop.is_set() and jobs.should_stop("audio", stop):
                        stop.set()
                        abort.set()
                    completed, pending = wait(
                        pending, return_when=FIRST_COMPLETED, timeout=5.0
                    )
                    for fut in completed:
                        vid, title = futures[fut]
                        status, feats, err = fut.result()
                        done_count += 1
                        note = ""
                        if status == "ok":
                            consecutive_net = 0
                            _save_features(vid, feats)
                            ok += 1
                            note = (
                                f"{ok} готово, {failed} ошибок; последний: "
                                f"{title[:50]} "
                                f"({feats['tempo']:.0f} BPM, {feats['key']})"
                            )
                        elif status == "skipped":
                            skipped += 1
                            failed += 1
                            note = (
                                f"{ok} готово, {failed} ошибок; пропуск после "
                                "серии сетевых ошибок"
                            )
                        elif status == "dl-error":
                            failed += 1
                            last_error = err
                            if _is_network_error(err):
                                consecutive_net += 1
                                if (
                                    consecutive_net >= ABORT_NET_ERRORS
                                    and not abort.is_set()
                                ):
                                    abort.set()
                                    aborted = True
                            note = (
                                f"{ok} готово, {failed} ошибок; последний: "
                                f"{title[:40]} — {err[:80]}"
                            )
                        else:
                            failed += 1
                            last_error = err or "ошибка анализа"
                            note = (
                                f"{ok} готово, {failed} ошибок; последний: "
                                f"ошибка анализа {title[:40]} — {err[:60]}"
                            )
                        if settings.audio_delete_after:
                            for p in settings.audio_dir.glob(f"{vid}.*"):
                                p.unlink(missing_ok=True)
                        jobs.progress("audio", done_count, total, note)

        detail = (
            f"проанализировано {ok}, ошибок {failed}, пропущено {skipped} "
            f"(всего в БД: {already + ok}; воркеров: {workers})"
        )
        if jobs.should_stop("audio", stop):
            jobs.stop_job("audio", detail=f"{detail}; остановлено пользователем")
            return
        if aborted:
            detail += (
                f"; остановлено: {ABORT_NET_ERRORS} сетевых ошибок подряд — "
                "YouTube троттлит IP, повторите запуск позже"
            )
        if last_error:
            detail += f"; последняя ошибка: {last_error[:150]}"
        jobs.finish_job("audio", detail=detail)
    except Exception as exc:  # noqa: BLE001
        jobs.fail_job("audio", f"{type(exc).__name__}: {exc}")
        raise
