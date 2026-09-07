"""Rhythm, key, and dynamics via Essentia (C++ algorithms and models).

- RhythmExtractor2013(method="multifeature") — BPM robust to octave
  errors;
- TensorflowPredictTempoCNN (deeptemp model) — a second, independent
  tempo vote with its own confidence;
- KeyExtractor (tuning + HPCP + profiles) — musical key;
- DynamicComplexity — loudness (dB) and dynamic range.

The algorithms expect: rhythm/key/dynamics — mono 44.1 kHz float32,
TempoCNN — mono 16 kHz float32. Inference errors are propagated up —
no silent fallbacks.
"""

import os
import threading

import numpy as np

from app.config import settings

# silence TensorFlow INFO/WARNING spam about CUDA probing (before TF is loaded)
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import essentia

# essentia INFO channel (MusicExtractorSVM, model loading) — discarded
essentia.log.infoActive = False

MODELS_DIR = settings.data_dir / "models"
TEMPO_CNN_PB = "deeptemp-k16-3"
TEMPO_ZOO = "https://essentia.upf.edu/models/tempo/tempocnn"

_local = threading.local()


def ensure_models(progress_cb=None, should_stop=None) -> None:
    """Downloads the TempoCNN model if missing; on failure, raises."""
    if should_stop is not None and should_stop():
        return
    path = MODELS_DIR / f"{TEMPO_CNN_PB}.pb"
    if path.exists() and path.stat().st_size > 0:
        return
    from app.services.essentia_tags import download_model_file

    url = f"{TEMPO_ZOO}/{TEMPO_CNN_PB}.pb"
    if progress_cb is not None:
        progress_cb(f"downloading model {TEMPO_CNN_PB}.pb")
    download_model_file(url, path)


def _algorithms() -> dict:
    """Thread-local instances (essentia instances are not thread-safe)."""
    if getattr(_local, "a", None) is not None:
        return _local.a
    from essentia.standard import (
        DynamicComplexity,
        KeyExtractor,
        RhythmExtractor2013,
    )

    try:
        from essentia.standard import TensorflowPredictTempoCNN
    except ImportError as exc:
        raise RuntimeError(
            "essentia-tensorflow is shadowed by the plain essentia wheel "
            "(happens on a fresh venv); it is repaired automatically by "
            "dev.sh/start.sh, or run: uv pip install --reinstall-package "
            "essentia-tensorflow essentia-tensorflow"
        ) from exc

    ensure_models()
    _local.a = {
        "rhythm": RhythmExtractor2013(method="multifeature"),
        "tempocnn": TensorflowPredictTempoCNN(
            graphFilename=str(MODELS_DIR / f"{TEMPO_CNN_PB}.pb")
        ),
        "key": KeyExtractor(),
        "dynamics": DynamicComplexity(),
    }
    return _local.a


def extract_rhythm_key(audio44: np.ndarray, y16: np.ndarray) -> dict:
    """Track BPM (multifeature + TempoCNN), key, and dynamics.

    audio44 — mono 44.1 kHz; y16 — mono 16 kHz (for TempoCNN).
    NaN/Inf samples (broken decodes) are replaced with silence.
    RhythmExtractor2013 may throw on beatless/noisy material — its vote
    is skipped then (tempo falls back to TempoCNN + onset
    autocorrelation); the remaining failures propagate with the
    algorithm name.
    """
    a = _algorithms()
    audio44 = np.nan_to_num(np.ascontiguousarray(audio44, dtype=np.float32))
    y16 = np.nan_to_num(np.ascontiguousarray(y16, dtype=np.float32))

    bpm_multi = None
    try:
        bpm = a["rhythm"](audio44)[0]
        bpm_multi = float(np.atleast_1d(bpm)[0])
    except Exception as exc:
        import sys

        print(
            f"essentia: RhythmExtractor2013 failed "
            f"({type(exc).__name__}: {exc}); skipping the multi-feature "
            f"tempo vote",
            file=sys.stderr,
        )

    try:
        cnn_out = np.atleast_1d(np.asarray(a["tempocnn"](y16)).flatten())
        bpm_cnn = float(cnn_out[0])
        cnn_conf = float(cnn_out[1]) if cnn_out.size > 1 else 0.5
    except Exception as exc:
        raise RuntimeError(
            f"essentia: TempoCNN failed: {type(exc).__name__}: {exc}"
        ) from exc

    try:
        key, scale, strength = a["key"](audio44)
    except Exception as exc:
        raise RuntimeError(
            f"essentia: KeyExtractor failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    try:
        dyn, loudness = a["dynamics"](audio44)
    except Exception as exc:
        raise RuntimeError(
            f"essentia: DynamicComplexity failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    return {
        "bpm_multi": bpm_multi,
        "bpm_cnn": bpm_cnn,
        "cnn_conf": float(np.clip(cnn_conf, 0.0, 1.0)),
        "key": f"{key} {scale}",
        "strength": float(np.clip(float(strength), 0.0, 1.0)),
        "dynamics": float(dyn),
        "loudness": float(loudness),
    }
