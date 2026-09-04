"""Recompute tags/moods/embeddings from cached audio (Essentia).

Updates: tags (genres, styles, instruments, moods, moodtags),
vocal_ratio, embedding, danceability/acousticness/brightness (models),
the 11 mood_* columns. Audio is not re-downloaded — taken from
data/audio.

Usage: .venv/bin/python tools/retag_essentia.py [threads]
Track errors are collected and printed as a summary; exit code 1 on errors.
"""

import base64
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlmodel import Session

from app.db import engine
from app.services import essentia_feats, essentia_tags
from app.services.recommend import MOOD_COLS

MOOD_UPDATE = ", ".join(f"{c} = :{c}" for c in MOOD_COLS)
PARAMS = {c: f":{c}" for c in MOOD_COLS}


def main() -> int:
    essentia_tags.ensure_models()
    essentia_feats.ensure_models()
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    with Session(engine) as session:
        rows = session.execute(
            text(
                "SELECT f.track_id FROM audio_features f "
                "JOIN track t ON t.video_id = f.track_id "
                "WHERE f.source = 'audio' AND t.is_music = 1"
            )
        ).all()
        ids = [r[0] for r in rows]
    print(f"tracks to recompute: {len(ids)}")

    from essentia.standard import MonoLoader

    def work(tid: str):
        wav = Path("data/audio") / f"{tid}.wav"
        if not wav.exists():
            return tid, FileNotFoundError("no cached audio")
        try:
            audio = MonoLoader(
                filename=str(wav), sampleRate=16000, resampleQuality=4
            )()
            return tid, essentia_tags.analyze(audio[: 16000 * 60])
        except Exception as exc:  # noqa: BLE001
            return tid, exc

    done = errors = 0
    error_list: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        with Session(engine) as session:
            for tid, result in pool.map(work, ids):
                if isinstance(result, Exception):
                    errors += 1
                    error_list.append(f"{tid}: {type(result).__name__}: {result}")
                    continue
                mood_params = {
                    c: float(result["moods"].get(c, 0.0)) for c in MOOD_COLS
                }
                session.execute(
                    text(
                        "UPDATE audio_features SET tags = :tags, "
                        "vocal_ratio = :vr, embedding = :emb, "
                        "danceability = :dance, acousticness = :acoustic, "
                        "brightness = :bright, feat_version = 6, "
                        + MOOD_UPDATE
                        + " WHERE track_id = :tid"
                    ),
                    {
                        "tags": json.dumps(
                            result, ensure_ascii=False, default=float
                        ),
                        "vr": result["vocal_ratio"],
                        "emb": result["embedding"],
                        "dance": result["danceability"],
                        "acoustic": result["acousticness"],
                        "bright": result["brightness"],
                        "tid": tid,
                        **mood_params,
                    },
                )
                done += 1
                if done % 100 == 0:
                    session.commit()
                    print(f"  {done} recomputed ({errors} errors)…")
            session.commit()

    print(f"done: {done}, errors: {errors}")
    if error_list:
        print("errors:")
        for line in error_list:
            print(f"  {line}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
