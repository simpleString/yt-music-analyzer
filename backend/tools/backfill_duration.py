"""One-off backfill of Track.duration from cached audio files.

Duration used to come only from the YouTube API; analysis now saves
it, but already-analyzed tracks were left without it.
Usage: .venv/bin/python tools/backfill_duration.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import librosa
from sqlalchemy import text

from app.db import engine
from sqlmodel import Session


def main() -> None:
    with Session(engine) as session:
        rows = session.execute(
            text(
                "SELECT t.video_id FROM track t "
                "JOIN audio_features f ON f.track_id = t.video_id "
                "WHERE t.is_music = 1 AND (t.duration IS NULL OR t.duration = 0)"
            )
        ).all()
        ids = [r[0] for r in rows]
        print(f"analyzed tracks without duration: {len(ids)}")
        done = missing = 0
        for tid in ids:
            path = None
            for ext in (".wav", ".webm", ".m4a", ".opus", ".mp4"):
                p = Path("data/audio") / f"{tid}{ext}"
                if p.exists():
                    path = p
                    break
            if path is None:
                missing += 1
                continue
            try:
                dur = float(librosa.get_duration(path=str(path)))
            except Exception:
                missing += 1
                continue
            if dur <= 0:
                missing += 1
                continue
            session.execute(
                text("UPDATE track SET duration = :d WHERE video_id = :id"),
                {"d": round(dur, 1), "id": tid},
            )
            done += 1
            if done % 500 == 0:
                session.commit()
                print(f"  {done} updated…")
        session.commit()
        print(f"done: updated {done}, missing file/failed: {missing}")


if __name__ == "__main__":
    main()
