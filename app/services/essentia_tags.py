"""Тегирование треков моделями Essentia (полная замена YAMNet).

Архитектура:
- Discogs-EffNet (TensorflowPredictEffnetDiscogs): два выхода —
  PartitionedCall:0 = активации 400 стилей Discogs (жанры),
  PartitionedCall:1 = эмбеддинги 1280 (вход для голов)
- Головы на эмбеддингах (TensorflowPredict2D):
  voice_instrumental — вокал/инструментал (калиброванная вероятность),
  mtg_jamendo_instrument — 40 инструментальных классов,
  mtg_jamendo_moodtheme — 56 mood/theme тегов → наши 8 настроений.

Формат результата совпадает со старым tags-json:
{"genres": [{name, score}], "instruments": [{name, score}],
 "moods": {mood_*: 0..1}, "vocal_ratio": 0..1}
"""

import json
import threading

import numpy as np

from app.config import settings

MODELS_DIR = settings.data_dir / "models"
DISCOGS_PB = "discogs-effnet-bs64-1.pb"

# порог отсечения слабых тегов (сигмоиды jamendo-голов, softmax discogs)
GENRE_MIN_SCORE = 0.05
INSTRUMENT_MIN_SCORE = 0.10

# moodtheme-теги → наши 8 настроений (каждый тег в одной группе)
MOOD_MAP = {
    "mood_happy": (
        "happy", "fun", "funny", "positive", "hopeful", "cool", "summer",
        "uplifting", "upbeat",
    ),
    "mood_sad": ("sad", "melancholic", "emotional", "ballad"),
    "mood_relaxed": (
        "relaxing", "calm", "soft", "meditative", "slow", "background",
    ),
    "mood_aggressive": ("heavy", "fast", "energetic", "sport", "party"),
    "mood_epic": (
        "epic", "dramatic", "powerful", "action", "trailer", "adventure",
        "motivational", "inspiring",
    ),
    "mood_dark": ("dark", "deep"),
    "mood_romantic": ("romantic", "love", "sexy"),
    "mood_atmospheric": (
        "soundscape", "dream", "space", "nature", "melodic",
    ),
}

# человекочитаемые имена инструментов jamendo
INSTRUMENT_NAMES = {
    "accordion": "Accordion", "acousticbassguitar": "Acoustic bass guitar",
    "acousticguitar": "Acoustic guitar", "bass": "Bass", "beat": "Beat",
    "bell": "Bell", "bongo": "Bongo", "brass": "Brass", "cello": "Cello",
    "clarinet": "Clarinet", "classicalguitar": "Classical guitar",
    "computer": "Computer", "doublebass": "Double bass",
    "drummachine": "Drum machine", "drums": "Drums",
    "electricguitar": "Electric guitar", "electricpiano": "Electric piano",
    "flute": "Flute", "guitar": "Guitar", "harmonica": "Harmonica",
    "harp": "Harp", "horn": "Horn", "keyboard": "Keyboard", "oboe": "Oboe",
    "orchestra": "Orchestra", "organ": "Organ", "pad": "Pad",
    "percussion": "Percussion", "piano": "Piano", "pipeorgan": "Pipe organ",
    "rhodes": "Rhodes", "sampler": "Sampler", "saxophone": "Saxophone",
    "strings": "Strings", "synthesizer": "Synthesizer",
    "trombone": "Trombone", "trumpet": "Trumpet", "viola": "Viola",
    "violin": "Violin", "voice": "Voice",
}

_local = threading.local()


def _algorithms() -> dict:
    """Тред-локальные инстансы (инференс не потокобезопасен)."""
    if getattr(_local, "algos", None) is not None:
        return _local.algos
    import os

    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    from essentia.standard import TensorflowPredict2D, TensorflowPredictEffnetDiscogs

    with open(MODELS_DIR / DISCOGS_PB.replace(".pb", ".json")) as f:
        meta = json.load(f)
    styles = meta["classes"]

    def head(name):
        with open(MODELS_DIR / f"{name}-discogs-effnet-1.json") as f:
            m = json.load(f)
        alg = TensorflowPredict2D(
            graphFilename=str(MODELS_DIR / f"{name}-discogs-effnet-1.pb"),
            input=m["schema"]["inputs"][0]["name"],
            output=m["schema"]["outputs"][0]["name"],
        )
        return alg, m["classes"]

    voice_alg, voice_classes = head("voice_instrumental")
    inst_alg, inst_classes = head("mtg_jamendo_instrument")
    mood_alg, mood_classes = head("mtg_jamendo_moodtheme")
    _local.algos = {
        "act": TensorflowPredictEffnetDiscogs(
            graphFilename=str(MODELS_DIR / DISCOGS_PB),
            output="PartitionedCall",
        ),
        "emb": TensorflowPredictEffnetDiscogs(
            graphFilename=str(MODELS_DIR / DISCOGS_PB),
            output="PartitionedCall:1",
        ),
        "styles": styles,
        "voice": (voice_alg, voice_classes),
        "inst": (inst_alg, inst_classes),
        "mood": (mood_alg, mood_classes),
    }
    return _local.algos


def prettify_style(style: str) -> str:
    """«Electronic---House» → «Electronic · House»."""
    return " · ".join(p.strip() for p in style.split("---") if p.strip())


def analyze(y16: np.ndarray) -> dict | None:
    """Теги трека по сигналу 16 кГц (моно, float).

    Возвращает словарь для AudioFeatures.tags (json) + vocal_ratio,
    None — если модели недоступны.
    """
    try:
        a = _algorithms()
    except Exception:
        return None
    audio = np.ascontiguousarray(y16, dtype=np.float32)

    activations = np.asarray(a["act"](audio)).mean(axis=0)
    embeddings = np.asarray(a["emb"](audio))

    voice_alg, voice_classes = a["voice"]
    v_pred = np.asarray(voice_alg(embeddings)).mean(axis=0)
    v = dict(zip(voice_classes, v_pred))

    inst_alg, inst_classes = a["inst"]
    i_pred = np.asarray(inst_alg(embeddings)).mean(axis=0)
    inst = dict(zip(inst_classes, i_pred))

    mood_alg, mood_classes = a["mood"]
    m_pred = np.asarray(mood_alg(embeddings)).mean(axis=0)
    theme = dict(zip(mood_classes, m_pred))

    genres = [
        {"name": prettify_style(a["styles"][i]), "score": round(float(s), 3)}
        for i, s in sorted(
            enumerate(activations), key=lambda x: -x[1]
        )[:3]
        if float(s) >= GENRE_MIN_SCORE
    ]
    instruments = [
        {"name": INSTRUMENT_NAMES.get(n, n), "score": round(float(s), 3)}
        for n, s in sorted(inst.items(), key=lambda x: -x[1])[:5]
        if float(s) >= INSTRUMENT_MIN_SCORE
    ]

    # 8 настроений: сумма тегов группы, нормировка на максимум
    moods_raw = {
        mood: sum(float(theme.get(t, 0.0)) for t in tags)
        for mood, tags in MOOD_MAP.items()
    }
    top = max(moods_raw.values(), default=0.0)
    moods = (
        {k: round(v / top, 3) for k, v in moods_raw.items()} if top > 0 else {}
    )

    return {
        "genres": genres,
        "instruments": instruments,
        "moods": moods,
        "vocal_ratio": round(float(v.get("voice", 0.0)), 3),
    }
