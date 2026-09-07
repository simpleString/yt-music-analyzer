"""Whisper spot-check: does the track audio contain actual words?

Used by the lyrics job when LRCLIB found nothing and the vocal score is
in the uncertain band. A short fragment is cut from the cached audio and
transcribed with faster-whisper (CPU, int8); a sufficient number of
recognized words means the track has vocals. The verdict is cached in
audio_features.has_vocals, the rough transcript is stored as a fallback
Lyrics row (source='whisper').
"""

import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from app.config import settings

_local = threading.local()


def _model():
    """Thread-local faster-whisper model (loaded on first use)."""
    model = getattr(_local, "model", None)
    if model is None:
        from faster_whisper import WhisperModel

        model = WhisperModel(
            settings.whisper_model or "base",
            device="cpu",
            compute_type="int8",
            download_root=str(settings.data_dir / "models"),
        )
        _local.model = model
    return model


def _find_audio(video_id: str) -> Path | None:
    from app.services.audio import _find_cached

    return _find_cached(video_id)


def _cut_fragment(path: Path, duration: float | None) -> Path | None:
    """~45 s mono 16 kHz wav from the middle of the track (temp file)."""
    clip = max(10, settings.whisper_clip_seconds)
    start = 0.0
    if duration and duration > clip * 2:
        start = max(0.0, duration * 0.35)
    tmpdir = Path(tempfile.mkdtemp(prefix="vocals-"))
    out = tmpdir / "clip.wav"
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", f"{start:.1f}", "-t", str(clip),
                "-i", str(path),
                "-ac", "1", "-ar", "16000",
                str(out),
            ],
            capture_output=True,
            timeout=120,
            check=True,
        )
    except (subprocess.SubprocessError, OSError):
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None
    return out


def check_words(video_id: str, duration: float | None = None) -> dict | None:
    """Transcribe a fragment; None = no cached audio or transcription failed.

    Returns {"words": int, "text": str, "language": str, "lang_prob": float}.
    """
    path = _find_audio(video_id)
    if path is None:
        return None
    wav = _cut_fragment(path, duration)
    if wav is None:
        return None
    try:
        model = _model()
        # no vad_filter: Silero VAD treats singing over loud music as
        # non-speech and drops every segment; the word-count threshold
        # below filters instrumentals instead
        segments, info = model.transcribe(str(wav), beam_size=1)
        texts: list[str] = []
        for seg in segments:
            text = (seg.text or "").strip()
            if text:
                texts.append(text)
        joined = "\n".join(texts)
        return {
            "words": len(joined.split()),
            "text": joined,
            "language": info.language or "",
            "lang_prob": float(getattr(info, "language_probability", 0.0) or 0.0),
        }
    except Exception:  # noqa: BLE001 — a broken model/file must not kill the job
        return None
    finally:
        shutil.rmtree(wav.parent, ignore_errors=True)
