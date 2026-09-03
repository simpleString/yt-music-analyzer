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
from app.services import essentia_feats, essentia_tags

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


def _find_cached(video_id: str) -> Path | None:
    """Ищет аудио трека в локальном кэше (предпочтение готовому wav)."""
    existing = [
        p
        for p in settings.audio_dir.glob(f"{video_id}.*")
        if p.suffix in (".webm", ".m4a", ".opus", ".ogg", ".mp3", ".mkv", ".mp4", ".wav")
    ]
    existing.sort(key=lambda p: p.suffix != ".wav")  # готовый wav — без конвертации
    no_ext = settings.audio_dir / video_id
    if existing:
        return existing[0]
    if no_ext.exists() and no_ext.stat().st_size > 10_000:
        return no_ext
    return None


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
    no_ext = settings.audio_dir / video_id
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


def _tempo_score(cand: float, onset_env: np.ndarray, sr: int) -> float:
    """Скор кандидата BPM: автокорреляция onset-огибающей на кратных
    лагах (1..4) + мягкий лог-нормальный приоритет человеческому темпу.

    У вдвое завышенной гипотезы совпадают только чётные лаги, у
    настоящего темпа — все.
    """
    n = len(onset_env)
    fps = sr / 512.0  # кадров onset_strength в секунде (hop=512)

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
    # базовый лаг весомее кратных: у кратных лагов больше шансов
    # случайно совпасть для слишком быстрой гипотезы
    combined = 0.6 * vals[0] + 0.4 * float(np.mean(vals[1:]))
    prior = np.exp(-((np.log(cand / 115.0) / 0.7) ** 2))
    return combined + 0.10 * float(prior)


def _tempo_conf(bpm: float, onset_env: np.ndarray, sr: int) -> float:
    """Уверенность autocorr-оценки BPM, нормированная в 0..1."""
    return float(np.clip(_tempo_score(bpm, onset_env, sr), 0.0, 1.0))


def _refine_tempo(tempo: float, onset_env: np.ndarray, sr: int) -> float:
    """Чинит октавные ошибки темпа по автокорреляции onset-огибающей.

    Кандидаты (×0.5, ×2, ×2/3, ×3/2, ×3, ×1/3) оцениваются через
    _tempo_score; альтернатива должна выиграть с запасом, иначе
    побеждает исходная оценка.
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
    """Итоговый BPM: кросс-чек multifeature против TempoCNN.

    Согласны (расхождение ≤20%) — берём multifeature; расходятся —
    верим тому, у кого выше уверенность (у TempoCNN своя, у
    multifeature — автокорреляционный скор). Вне диапазона 60–190 —
    октавная автокоррекция.
    """
    multi = ek["bpm_multi"]
    cnn = ek["bpm_cnn"]
    if multi <= 0 or cnn <= 0:
        bpm = multi or cnn
    elif abs(multi - cnn) / max(multi, cnn) <= 0.20:
        bpm = multi
    else:
        bpm = (
            multi
            if _tempo_conf(multi, onset_env, sr) >= ek["cnn_conf"]
            else cnn
        )
    if not 60.0 <= bpm <= 190.0:
        bpm = _refine_tempo(bpm, onset_env, sr)
    return float(bpm)


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
    # полная длительность файла: probe точен; если не прочитался —
    # загружали без cap, значит duration и есть полная длина
    file_duration = float(probe) if probe is not None else duration

    # onset-огибающая для кросс-чека и октавной автокоррекции BPM
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)

    # Essentia: ритм (multifeature + TempoCNN), тональность, динамика
    audio44 = librosa.resample(y, orig_sr=sr, target_sr=44100)
    y16 = librosa.resample(y, orig_sr=sr, target_sr=16000)[: 16000 * 60]
    ek = essentia_feats.extract_rhythm_key(audio44, y16)
    del audio44
    tempo = _resolve_tempo(ek, onset_env, sr)
    key, mode_conf = ek["key"], ek["strength"]
    loudness = ek["loudness"]
    # энергия из дБ-шкалы: -45 дБ → 0, 0 дБ → 1 (без клипа в потолок)
    energy = float(np.clip((loudness + 45.0) / 45.0, 0.0, 1.0))

    # v2: тембр, гармония, плотность микса (для кластеризации), перкуссивность
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

    # Essentia (Discogs-EffNet + головы): жанры, стили, инструменты,
    # настроения, вокал, danceability/acousticness/brightness (модели),
    # эмбеддинг 1280
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


def _analyze_file(video_id: str, path: Path) -> tuple[dict | None, str]:
    """Анализ одного аудиофайла; битый кэш удаляется для перекачки."""
    try:
        return analyze_audio(path), ""
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
        return None, msg


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
    """Воркер обработки одного трека.

    Аудио в кэше → анализ сразу (параллелизм audio_workers_cached);
    нет → скачивание (параллелизм ограничен семафором audio_workers).

    Возвращает (статус, фичи, ошибка, был_в_кэше).
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
        session.add(row)
        # длительность трека из реального аудио, если ещё неизвестна
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
        jobs.progress("audio", 0, 0, f"{pot_note}; проверка моделей Essentia…")
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
            jobs.stop_job("audio", "остановлено пользователем (на проверке моделей)")
            return
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
        n_cached = sum(1 for vid, _ in candidates if _find_cached(vid) is not None)
        # живые остатки: уменьшаются по мере обработки
        cached_left = n_cached
        download_left = total - n_cached

        def counts_prefix() -> str:
            return (
                f"[осталось: кэш {cached_left} · скачка {download_left}] "
            )

        jobs.progress(
            "audio",
            0,
            total,
            f"{pot_note}; воркеров: анализ {cached_workers} / скачивание "
            f"{workers}; {counts_prefix()}к анализу: {total} "
            f"(уже проанализировано: {already})"
            if total
            else f"{pot_note}; нет треков для анализа",
        )

        ok = failed = skipped = 0
        last_error = ""
        consecutive_net = 0
        aborted = False
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
                last_note = "в работе…"
                while pending:
                    # кросс-процессная отмена: флаг в БД → локальные события
                    if not stop.is_set() and jobs.should_stop("audio", stop):
                        stop.set()
                        abort.set()
                        # стоящие в очереди задачи отменяются мгновенно —
                        # не ждём, пока каждый трек начнёт и увидит флаг
                        for f in list(pending):
                            f.cancel()
                    completed, pending = wait(
                        pending, return_when=FIRST_COMPLETED, timeout=5.0
                    )
                    if not completed:
                        # heartbeat: треки ещё считаются, джоба жива
                        jobs.progress(
                            "audio",
                            done_count,
                            total,
                            f"{counts_prefix()}{last_note} "
                            f"(в полёте: {len(pending)})",
                        )
                        continue
                    for fut in completed:
                        vid, title = futures[fut]
                        try:
                            status, feats, err, from_cache = fut.result()
                        except FuturesCancelledError:
                            # отменены при остановке: не ошибка
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
                            _save_features(vid, feats)
                            ok += 1
                            note = (
                                f"{ok} готово, {failed} ошибок; последний: "
                                f"{title[:50]} "
                                f"({feats['tempo']:.0f} BPM, {feats['key']})"
                            )
                        elif status == "skipped":
                            skipped += 1
                            if stop.is_set() or abort.is_set():
                                note = (
                                    f"{ok} готово, {failed} ошибок; "
                                    "остановлено пользователем"
                                )
                            else:
                                failed += 1
                                note = (
                                    f"{ok} готово, {failed} ошибок; пропуск "
                                    "после серии сетевых ошибок"
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
                        last_note = note
                        jobs.progress(
                            "audio", done_count, total, counts_prefix() + note
                        )

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
