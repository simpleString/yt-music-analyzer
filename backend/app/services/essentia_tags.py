"""Track tagging with Essentia models (Discogs-EffNet + heads).

Architecture:
- Discogs-EffNet (TensorflowPredictEffnetDiscogs): two outputs —
  PartitionedCall:0 = activations of 400 Discogs styles (genres),
  PartitionedCall:1 = 1280 embeddings (input for the heads)
- Heads on embeddings (TensorflowPredict2D):
  voice_instrumental — vocal/instrumental (calibrated probability),
  mtg_jamendo_instrument — 40 instrument classes,
  mtg_jamendo_moodtheme — 56 mood/theme tags (raw tags + 4 moods),
  danceability — danceability,
  mood_happy/sad/relaxed/aggressive/electronic/acoustic/party — moods,
  nsynth_bright_dark — brightness/darkness of sound.

ensure_models() downloads missing .pb/.json from essentia.upf.edu;
a missing model is an error (no fallback heuristics).

analyze() result format:
{"genres": [{name, score}] (top-3),
 "styles": {style: score} (top-20, ≥0.02),
 "instruments": [{name, score}] (all ≥0.05),
 "moods": {mood_*: 0..1} (11: 7 model heads + 4 moodtheme),
 "moodtags": {tag: score} (≥0.05),
 "vocal_ratio": 0..1,
 "embedding": base64(float16[1280])}
"""

import base64
import json
import os
import threading
from pathlib import Path

import numpy as np

from app.config import settings

# silence TensorFlow INFO/WARNING spam about CUDA probing (before TF import)
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import essentia

essentia.log.infoActive = False

MODELS_DIR = settings.data_dir / "models"
DISCOGS_PB = "discogs-effnet-bs64-1"
ZOO_BASE = "https://essentia.upf.edu/models/classification-heads"

# head → catalog in the model zoo (file name = {task}-discogs-effnet-1)
HEADS = [
    "voice_instrumental",
    "mtg_jamendo_instrument",
    "mtg_jamendo_moodtheme",
    "danceability",
    "mood_happy",
    "mood_sad",
    "mood_relaxed",
    "mood_aggressive",
    "mood_acoustic",
    "mood_electronic",
    "mood_party",
    "nsynth_bright_dark",
]

# score thresholds for weak tags
GENRE_MIN_SCORE = 0.05
INSTRUMENT_MIN_SCORE = 0.05
STYLE_MIN_SCORE = 0.02
MOODTAG_MIN_SCORE = 0.05
STYLES_TOP_N = 20

# moods from dedicated model heads (direct probabilities)
MODEL_MOODS = [
    "mood_happy",
    "mood_sad",
    "mood_relaxed",
    "mood_aggressive",
    "mood_electronic",
    "mood_acoustic",
    "mood_party",
]

# moods from moodtheme tags (no dedicated models): the mean probability
# of the group's tags — absolute intensity 0..1
THEME_MOODS = {
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

# human-readable jamendo instrument names
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


def download_model_file(url: str, dest: Path) -> None:
    """Downloads a model file; raises on failure."""
    import httpx

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = httpx.get(url, timeout=120, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"essentia: failed to download {url}: {type(exc).__name__}"
        ) from exc
    dest.write_bytes(resp.content)


def ensure_models(progress_cb=None, should_stop=None) -> None:
    """Downloads missing backbone and heads; raises on failure.

    progress_cb(message) — progress report; should_stop() — cancellation
    check (stops between files; partially downloaded files resume next time).
    """
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    wanted = [(DISCOGS_PB, DISCOGS_PB)] + [
        (h, f"{h}-discogs-effnet-1") for h in HEADS
    ]
    for task, base in wanted:
        for ext in (".pb", ".json"):
            if should_stop is not None and should_stop():
                return
            path = MODELS_DIR / f"{base}{ext}"
            if path.exists() and path.stat().st_size > 0:
                continue
            url = f"{ZOO_BASE}/{task}/{base}{ext}"
            if progress_cb is not None:
                progress_cb(f"downloading model {base}{ext}")
            download_model_file(url, path)


def _positive_class(classes: list[str]) -> int:
    """Index of the "positive" class (not not_*/non_*)."""
    for i, c in enumerate(classes):
        low = c.lower()
        if not low.startswith(("not_", "non_", "un")) and low not in (
            "dark",
        ):
            return i
    return 0


def _algorithms() -> dict:
    """Thread-local instances (inference is not thread-safe)."""
    if getattr(_local, "algos", None) is not None:
        return _local.algos
    try:
        from essentia.standard import (
            TensorflowPredict2D,
            TensorflowPredictEffnetDiscogs,
        )
    except ImportError as exc:
        raise RuntimeError(
            "essentia-tensorflow is shadowed by the plain essentia wheel "
            "(happens on a fresh venv); it is repaired automatically by "
            "dev.sh/start.sh, or run: uv pip install --reinstall-package "
            "essentia-tensorflow essentia-tensorflow"
        ) from exc

    ensure_models()

    def head(name: str):
        meta_path = MODELS_DIR / f"{name}-discogs-effnet-1.json"
        with open(meta_path) as f:
            m = json.load(f)
        alg = TensorflowPredict2D(
            graphFilename=str(MODELS_DIR / f"{name}-discogs-effnet-1.pb"),
            input=m["schema"]["inputs"][0]["name"],
            output=m["schema"]["outputs"][0]["name"],
        )
        classes = [str(c) for c in m["classes"]]
        return alg, classes

    def _head_checked(name: str):
        try:
            return head(name)
        except Exception as exc:
            raise RuntimeError(
                f"essentia: head {name} failed to load: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    with open(MODELS_DIR / f"{DISCOGS_PB}.json") as f:
        styles = json.load(f)["classes"]

    algos: dict = {
        "act": TensorflowPredictEffnetDiscogs(
            graphFilename=str(MODELS_DIR / f"{DISCOGS_PB}.pb"),
            output="PartitionedCall",
        ),
        "emb": TensorflowPredictEffnetDiscogs(
            graphFilename=str(MODELS_DIR / f"{DISCOGS_PB}.pb"),
            output="PartitionedCall:1",
        ),
        "styles": styles,
    }
    for h in HEADS:
        algos[h] = _head_checked(h)
    _local.algos = algos
    return _local.algos


def prettify_style(style: str) -> str:
    """\"Electronic---House\" → \"Electronic · House\"."""
    return " · ".join(p.strip() for p in style.split("---") if p.strip())


def analyze(y16: np.ndarray) -> dict:
    """Full tag pack for a 16 kHz signal (mono, float).

    Any model/inference error propagates up — there are no silent
    fallbacks.
    """
    a = _algorithms()
    audio = np.ascontiguousarray(y16, dtype=np.float32)

    emb_raw = np.asarray(a["emb"](audio))  # (frames, 1280)
    embeddings = emb_raw if emb_raw.ndim == 2 else emb_raw[None, :]
    pooled = embeddings.mean(axis=0)
    activations = np.asarray(a["act"](audio)).mean(axis=0)

    def head_prob(name: str) -> tuple[float, dict[str, float]]:
        alg, classes = a[name]
        pred = np.asarray(alg(embeddings)).mean(axis=0)
        scores = {str(c): float(v) for c, v in zip(classes, pred)}
        return scores[classes[_positive_class(classes)]], scores

    vocal_alg, vocal_classes = a["voice_instrumental"]
    v_pred = np.asarray(vocal_alg(embeddings)).mean(axis=0)
    vocal_scores = {str(c): float(v) for c, v in zip(vocal_classes, v_pred)}
    vocal_ratio = vocal_scores.get("voice", next(iter(vocal_scores.values())))

    inst_alg, inst_classes = a["mtg_jamendo_instrument"]
    i_pred = np.asarray(inst_alg(embeddings)).mean(axis=0)
    inst = dict(zip(inst_classes, i_pred))

    theme_alg, theme_classes = a["mtg_jamendo_moodtheme"]
    m_pred = np.asarray(theme_alg(embeddings)).mean(axis=0)
    theme = {str(c): float(v) for c, v in zip(theme_classes, m_pred)}

    danceability, _ = head_prob("danceability")
    acoustic_prob, _ = head_prob("mood_acoustic")
    bright_scores = head_prob("nsynth_bright_dark")[1]

    genres = [
        {"name": prettify_style(a["styles"][i]), "score": round(float(s), 3)}
        for i, s in sorted(
            enumerate(activations), key=lambda x: -x[1]
        )[:3]
        if float(s) >= GENRE_MIN_SCORE
    ]
    styles = {
        prettify_style(a["styles"][i]): round(float(s), 3)
        for i, s in sorted(enumerate(activations), key=lambda x: -x[1])[
            :STYLES_TOP_N
        ]
        if float(s) >= STYLE_MIN_SCORE
    }
    instruments = [
        {"name": INSTRUMENT_NAMES.get(n, n), "score": round(float(s), 3)}
        for n, s in sorted(inst.items(), key=lambda x: -x[1])
        if float(s) >= INSTRUMENT_MIN_SCORE
    ]
    moodtags = {
        str(t): round(v, 3)
        for t, v in sorted(theme.items(), key=lambda x: -x[1])
        if v >= MOODTAG_MIN_SCORE
    }

    moods: dict[str, float] = {}
    for m in MODEL_MOODS:
        moods[m] = round(head_prob(m)[0], 3)
    for mood, tags in THEME_MOODS.items():
        vals = [theme.get(t, 0.0) for t in tags if t in theme]
        moods[mood] = round(float(np.mean(vals)) if vals else 0.0, 3)

    embedding = base64.b64encode(
        np.asarray(pooled, dtype=np.float16).tobytes()
    ).decode("ascii")

    return {
        "genres": genres,
        "styles": styles,
        "instruments": instruments,
        "moods": moods,
        "moodtags": moodtags,
        "vocal_ratio": round(float(vocal_ratio), 3),
        "danceability": round(float(danceability), 3),
        "acousticness": round(float(acoustic_prob), 3),
        "brightness": round(float(bright_scores.get("bright", 0.0)), 3),
        "embedding": embedding,
    }
