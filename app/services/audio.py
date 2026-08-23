import subprocess
import time
from pathlib import Path

import httpx
import librosa
import numpy as np
import yt_dlp
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.models import AudioFeatures, Track
from app.services import jobs

SR = 22050
ANALYZE_SECONDS = 120.0
MIN_SECONDS = 5.0
POT_URL = "http://127.0.0.1:4416/ping"
POT_SERVER_JS = settings.data_dir / "tools" / "bgutil-pot-server" / "build" / "main.js"

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


def _load_audio(path: Path) -> tuple[np.ndarray, int]:
    try:
        y, sr = librosa.load(str(path), sr=SR, mono=True, duration=ANALYZE_SECONDS)
    except Exception:
        wav = path.with_suffix(".wav")
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(path), "-ac", "1", "-ar", str(SR), str(wav)],
            capture_output=True,
            timeout=120,
            check=True,
        )
        y, sr = librosa.load(str(wav), sr=SR, mono=True, duration=ANALYZE_SECONDS)
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


def analyze_audio(path: Path) -> dict:
    y, sr = _load_audio(path)
    duration = len(y) / sr
    if duration < MIN_SECONDS:
        raise ValueError("аудио слишком короткое")

    rms = float(librosa.feature.rms(y=y).mean())
    centroid = float(librosa.feature.spectral_centroid(y=y, sr=sr).mean())
    flatness = float(librosa.feature.spectral_flatness(y=y).mean())
    zcr = float(librosa.feature.zero_crossing_rate(y=y).mean())
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, units="time")
    onset_rate = float(len(onsets) / duration)
    tempo, beats = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
    tempo = float(np.atleast_1d(tempo)[0])
    beat_times = librosa.frames_to_time(beats, sr=sr)
    ibi = np.diff(beat_times)
    if len(ibi) > 2 and float(ibi.mean()) > 0:
        ibi_cv = float(ibi.std() / ibi.mean())
    else:
        ibi_cv = 1.5
    beat_regularity = 1.0 / (1.0 + 3.0 * ibi_cv)
    tempo_window = float(np.exp(-(((tempo - 115.0) / 35.0) ** 2)))

    key, mode_conf = detect_key(y, sr)

    energy = float(np.clip(rms * 5.5, 0.0, 1.0))
    danceability = float(
        np.clip(0.65 * beat_regularity + 0.5 * tempo_window, 0.0, 1.0)
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
    }


def run_audio_analysis() -> None:
    try:
        if not jobs.start_job("audio"):
            return
        limit = settings.audio_analysis_limit
        pot_note = ensure_pot_server()
        with Session(engine) as session:
            stmt = (
                select(Track)
                .where(Track.is_music == True)  # noqa: E712
                .order_by(Track.play_count.desc())
            )
            tracks = session.exec(stmt).all()
            already = len(
                session.exec(
                    select(AudioFeatures.track_id).where(  # type: ignore[arg-type]
                        AudioFeatures.source == "audio"
                    )
                ).all()
            )
            candidates = [
                t
                for t in tracks
                if (f := session.get(AudioFeatures, t.video_id)) is None
                or f.source != "audio"
            ]
            if limit > 0:
                candidates = candidates[:limit]

        total = len(candidates)
        jobs.progress(
            "audio",
            0,
            total,
            f"{pot_note}; к анализу: {total} (уже проанализировано: {already})"
            if total
            else f"{pot_note}; нет треков для анализа",
        )

        ok = failed = 0
        last_error = ""
        for i, track in enumerate(candidates):
            path, dl_error = download_audio(track.video_id)
            if path is None:
                failed += 1
                last_error = dl_error
                jobs.progress(
                    "audio",
                    i + 1,
                    total,
                    f"{ok} готово, {failed} ошибок; последний: {track.title[:40]} — {dl_error[:80]}",
                )
                continue
            try:
                feats = analyze_audio(path)
            except Exception:
                failed += 1
                jobs.progress(
                    "audio",
                    i + 1,
                    total,
                    f"{ok} готово, {failed} ошибок; последний: ошибка анализа {track.title[:40]}",
                )
                continue
            finally:
                if settings.audio_delete_after:
                    for p in settings.audio_dir.glob(f"{track.video_id}.*"):
                        p.unlink(missing_ok=True)
            with Session(engine) as session:
                row = session.get(AudioFeatures, track.video_id)
                if row is None:
                    row = AudioFeatures(track_id=track.video_id)
                row.source = "audio"
                row.tempo = feats["tempo"]
                row.energy = feats["energy"]
                row.danceability = feats["danceability"]
                row.acousticness = feats["acousticness"]
                row.brightness = feats["brightness"]
                row.key = feats["key"]
                row.mode_conf = feats["mode_conf"]
                session.add(row)
                session.commit()
            ok += 1
            jobs.progress(
                "audio",
                i + 1,
                total,
                f"{ok} готово, {failed} ошибок; последний: {track.title[:50]} "
                f"({feats['tempo']:.0f} BPM, {feats['key']})",
            )

        suffix_note = f"; последняя ошибка: {last_error[:150]}" if last_error else ""
        jobs.finish_job(
            "audio",
            detail=f"проанализировано {ok}, ошибок {failed} (всего в БД: {already + ok}){suffix_note}",
        )
    except Exception as exc:  # noqa: BLE001
        jobs.fail_job("audio", f"{type(exc).__name__}: {exc}")
        raise
