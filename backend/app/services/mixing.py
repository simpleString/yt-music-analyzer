"""Harmonic mixing: Camelot-wheel compatible tracks + BPM matching.

AudioFeatures.key stores the Essentia KeyExtractor verdict as
"<pitch> <scale>" (e.g. "C major", "Eb minor") with mode_conf in
[0..1]. A pair is mix-compatible when:

- both keys are confident (mode_conf >= MIX_KEY_CONF), and
- the Camelot codes match exactly (same key / relative major-minor)
  or are adjacent on the wheel (±1 number, same letter), and
- tempos are within ±6%, or one is double/half the other.

The result powers the "Mix-compatible" card on the track page (DJ-style
ordering: same key first, then energy-up, energy-down, relative).
"""

import re

from sqlalchemy import text
from sqlmodel import Session

from app.config import settings
from app.db import engine
from app.models import Track

# pitch name -> chromatic index 0..11 (sharps and flats both accepted)
_PITCH = {
    "C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5,
    "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9, "A#": 10,
    "BB": 10, "B": 11,
}

# Camelot wheel: major keys -> (number, "B"), minor -> (number, "A")
_CAMELOT_MAJOR = {
    0: 8, 1: 3, 2: 10, 3: 5, 4: 12, 5: 7, 6: 2, 7: 9, 8: 4, 9: 11,
    10: 6, 11: 1,
}
_CAMELOT_MINOR = {
    0: 5, 1: 12, 2: 7, 3: 2, 4: 9, 5: 4, 6: 11, 7: 6, 8: 1, 9: 8,
    10: 3, 11: 10,
}

TEMPO_TOLERANCE = 0.06  # ±6 %, plus double/half-time matches

_KEY_RE = re.compile(r"^([A-G](?:#|b)?)\s+(major|minor)$", re.IGNORECASE)


def parse_key(key: str) -> tuple[int, bool] | None:
    """"<pitch> <scale>" -> (chromatic index, is_major); None if unparsable."""
    m = _KEY_RE.match((key or "").strip())
    if not m:
        return None
    raw = m.group(1)
    # "Eb" -> "EB", "C#" -> "C#" — matching the _PITCH table keys
    pitch = raw[0].upper() + (raw[1].upper() if len(raw) == 2 else "")
    idx = _PITCH.get(pitch)
    if idx is None:
        return None
    return idx, m.group(2).lower() == "major"


def camelot(idx: int, is_major: bool) -> tuple[int, str]:
    num = (_CAMELOT_MAJOR if is_major else _CAMELOT_MINOR)[idx]
    return num, "B" if is_major else "A"


def key_relation(a: tuple[int, str], b: tuple[int, str]) -> str | None:
    """Camelot relation of two (number, letter) codes; None if incompatible.

    same        — identical code (same key)
    relative    — same number, other letter (relative major/minor)
    energy-up   — +1 number, same letter (clockwise on the wheel)
    energy-down — −1 number, same letter
    """
    num_a, let_a = a
    num_b, let_b = b
    if num_a == num_b:
        return "same" if let_a == let_b else "relative"
    if let_a == let_b:
        diff = (num_b - num_a) % 12
        if diff == 1:
            return "energy-up"
        if diff == 11:
            return "energy-down"
    return None


def tempo_relation(cur: float, other: float) -> tuple[bool, float]:
    """(compatible, signed delta) — delta in [-1..1], 0 = same tempo.

    Compatible: within ±6 %, or a clean double/half-time match.
    """
    if cur <= 0 or other <= 0:
        return False, 0.0
    ratio = other / cur
    for factor in (1.0, 2.0, 0.5):
        delta = (ratio - factor) / factor
        if abs(delta) <= TEMPO_TOLERANCE:
            return True, delta
    return False, 0.0


_RELATION_RANK = {"same": 0, "energy-up": 1, "energy-down": 2, "relative": 3}


def mixable(track_id: str, limit: int = 12) -> dict | None:
    """Mix-compatible tracks for the seed.

    Returns {"seed": {...}, "items": [...]} or None — the seed has no
    confident key (or no tempo), so nothing to match against.
    """
    conf_gate = settings.mix_key_conf
    with Session(engine) as session:
        seed_f = session.execute(
            text(
                "SELECT track_id, key, mode_conf, tempo FROM audio_features "
                "WHERE track_id = :t AND source = 'audio'"
            ),
            {"t": track_id},
        ).first()
        if seed_f is None:
            return None
        _, seed_key, seed_conf, seed_tempo = seed_f
        parsed = parse_key(seed_key or "")
        if (
            parsed is None
            or seed_conf is None
            or seed_conf < conf_gate
            or not seed_tempo
        ):
            return None
        seed_idx, seed_major = parsed
        seed_code = camelot(seed_idx, seed_major)
        seed_t = session.get(Track, track_id)
        if seed_t is None:
            return None

        rows = session.execute(
            text(
                "SELECT track_id, key, mode_conf, tempo FROM audio_features "
                "WHERE source = 'audio' AND track_id != :t "
                "AND key != '' AND tempo > 0"
            ),
            {"t": track_id},
        ).all()

        items = []
        for other_id, other_key, other_conf, other_tempo in rows:
            if other_conf is None or other_conf < conf_gate:
                continue
            op = parse_key(other_key or "")
            if op is None:
                continue
            ok, delta = tempo_relation(float(seed_tempo), float(other_tempo))
            if not ok:
                continue
            rel = key_relation(seed_code, camelot(*op))
            if rel is None:
                continue
            t = session.get(Track, other_id)
            if t is None:
                continue
            num, let = camelot(*op)
            items.append(
                {
                    "track": {
                        "video_id": t.video_id,
                        "title": t.title,
                        "channel": t.channel,
                        "artist": t.artist_canonical or t.channel,
                        "play_count": t.play_count,
                    },
                    "key": other_key,
                    "camelot": f"{num}{let}",
                    "tempo": round(float(other_tempo), 1),
                    "tempo_delta": round(delta, 3),
                    "relation": rel,
                    "_rank": _RELATION_RANK[rel],
                    "_abs_delta": abs(delta),
                }
            )
        items.sort(key=lambda x: (x["_rank"], x["_abs_delta"]))
        for it in items:
            del it["_rank"], it["_abs_delta"]
        return {
            "seed": {
                "key": seed_key,
                "camelot": f"{seed_code[0]}{seed_code[1]}",
                "tempo": round(float(seed_tempo), 1),
            },
            "items": items[:limit],
            "total": len(items),
        }
