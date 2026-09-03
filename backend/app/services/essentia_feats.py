"""Ритм, тональность и динамика через Essentia (C++ алгоритмы и модели).

- RhythmExtractor2013(method="multifeature") — устойчивый к октавным
  ошибкам BPM;
- TensorflowPredictTempoCNN (модель deeptemp) — второй, независимый
  голос по темпу с собственной уверенностью;
- KeyExtractor (tuning + HPCP + профили) — тональность;
- DynamicComplexity — громкость (дБ) и динамический диапазон.

Алгоритмы ожидают: rhythm/key/dynamics — моно 44.1 кГц float32,
TempoCNN — моно 16 кГц float32. Ошибки инференса пробрасываются выше —
тихих заглушек нет.
"""

import os
import threading

import numpy as np

from app.config import settings

# глушим INFO/WARNING-спам TensorFlow про CUDA-перебор (до загрузки TF)
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import essentia

# INFO-канал essentia (MusicExtractorSVM, загрузка моделей) — в мусор
essentia.log.infoActive = False

MODELS_DIR = settings.data_dir / "models"
TEMPO_CNN_PB = "deeptemp-k16-3"
TEMPO_ZOO = "https://essentia.upf.edu/models/tempo/tempocnn"

_local = threading.local()


def ensure_models(progress_cb=None, should_stop=None) -> None:
    """Скачивает модель TempoCNN при отсутствии; ошибка — исключение."""
    if should_stop is not None and should_stop():
        return
    path = MODELS_DIR / f"{TEMPO_CNN_PB}.pb"
    if path.exists() and path.stat().st_size > 0:
        return
    from app.services.essentia_tags import download_model_file

    url = f"{TEMPO_ZOO}/{TEMPO_CNN_PB}.pb"
    if progress_cb is not None:
        progress_cb(f"скачивание модели {TEMPO_CNN_PB}.pb")
    download_model_file(url, path)


def _algorithms() -> dict:
    """Тред-локальные инстансы (инстансы essentia не потокобезопасны)."""
    if getattr(_local, "a", None) is not None:
        return _local.a
    from essentia.standard import (
        DynamicComplexity,
        KeyExtractor,
        RhythmExtractor2013,
        TensorflowPredictTempoCNN,
    )

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
    """BPM (multifeature + TempoCNN), тональность и динамика трека.

    audio44 — моно 44.1 кГц; y16 — моно 16 кГц (для TempoCNN).
    Ошибки пробрасываются выше с именем алгоритма.
    """
    a = _algorithms()
    audio44 = np.ascontiguousarray(audio44, dtype=np.float32)
    y16 = np.ascontiguousarray(y16, dtype=np.float32)

    try:
        bpm = a["rhythm"](audio44)[0]
        bpm_multi = float(np.atleast_1d(bpm)[0])
    except Exception as exc:
        raise RuntimeError(
            f"essentia: RhythmExtractor2013 не сработал: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    try:
        cnn_out = np.atleast_1d(np.asarray(a["tempocnn"](y16)).flatten())
        bpm_cnn = float(cnn_out[0])
        cnn_conf = float(cnn_out[1]) if cnn_out.size > 1 else 0.5
    except Exception as exc:
        raise RuntimeError(
            f"essentia: TempoCNN не сработал: {type(exc).__name__}: {exc}"
        ) from exc

    try:
        key, scale, strength = a["key"](audio44)
    except Exception as exc:
        raise RuntimeError(
            f"essentia: KeyExtractor не сработал: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    try:
        dyn, loudness = a["dynamics"](audio44)
    except Exception as exc:
        raise RuntimeError(
            f"essentia: DynamicComplexity не сработал: "
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
