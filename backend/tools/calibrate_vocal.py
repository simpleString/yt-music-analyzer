"""Calibration report for the vocal score (threshold selection helper).

Ground truth: tracks whose lyrics were found on LRCLIB are positive
(they definitely have words). For both groups (with/without lyrics) the
script prints the distribution of the combined vocal score
(max of the voice_instrumental head and the Jamendo "Voice" instrument)
and precision/recall over a threshold grid.

Usage: uv run python tools/calibrate_vocal.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlmodel import Session

from app.db import engine


def voice_from_tags(tags_json: str) -> float:
    try:
        data = json.loads(tags_json or "")
    except (ValueError, TypeError):
        return 0.0
    for inst in data.get("instruments", []):
        if str(inst.get("name", "")).lower() == "voice":
            return float(inst.get("score", 0.0))
    return 0.0


def main() -> None:
    with Session(engine) as session:
        rows = session.execute(
            text(
                "SELECT f.vocal_ratio, f.tags, l.track_id IS NOT NULL "
                "FROM audio_features f "
                "JOIN track t ON t.video_id = f.track_id "
                "LEFT JOIN lyrics l ON l.track_id = f.track_id AND l.text != '' "
                "WHERE f.source = 'audio' AND t.is_music = 1"
            )
        ).all()

    pos: list[float] = []  # lyrics found on LRCLIB
    neg: list[float] = []  # no lyrics known
    for vocal_ratio, tags, has_lyrics in rows:
        score = max(
            float(vocal_ratio or 0.0), voice_from_tags(tags or "")
        )
        (pos if has_lyrics else neg).append(score)

    if not pos:
        print("no positives yet (no LRCLIB lyrics) — run the lyrics job first")
        return

    def hist(scores: list[float]) -> str:
        buckets = [0] * 10
        for s in scores:
            buckets[min(9, int(s * 10))] += 1
        return " ".join(f"{b / len(scores):4.0%}" for b in buckets)

    print(f"tracks: {len(pos)} with lyrics, {len(neg)} without")
    print("score buckets 0.0–1.0 (share):")
    print("  with lyrics:   ", hist(pos))
    print("  without lyrics:", hist(neg))

    print("\nthreshold  recall(positives ≥ t)  share of negatives ≥ t")
    best = 0.0
    for t in range(5, 100, 5):
        thr = t / 100
        rec = sum(s >= thr for s in pos) / len(pos)
        fp = sum(s >= thr for s in neg) / len(neg) if neg else 0.0
        mark = ""
        if rec >= 0.95 and thr > best:
            best = thr
            mark = "  ← keeps ≥95% of positives"
        print(f"  {thr:4.2f}      {rec:6.1%}                {fp:6.1%}{mark}")
    print(f"\nsuggested lyrics_min_vocal: {best:.2f} (whisper double-checks below it)")


if __name__ == "__main__":
    main()
