"""Одноразовый пересчёт YAMNet tags/vocal_ratio по кэшированным wav.

Причина: старая формула (sigmoid от среднего логитов) занижала долю
вокала почти до нуля, из-за чего lyrics-джоб не находил кандидатов.
Запуск: .venv/bin/python tools/retag_vocal.py
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import librosa
import numpy as np

from app.db import engine
from app.services.audio import ensure_yamnet, yamnet_tags
from sqlalchemy import text
from sqlmodel import Session


def main() -> None:
    if not ensure_yamnet():
        print("YAMNet недоступен")
        return
    with Session(engine) as session:
        rows = session.execute(
            text(
                "SELECT f.track_id FROM audio_features f "
                "JOIN track t ON t.video_id = f.track_id "
                "WHERE f.source = 'audio' AND t.is_music = 1"
            )
        ).all()
        ids = [r[0] for r in rows]
    print(f"треков к пересчёту: {len(ids)}")

    def work(tid: str):
        wav = Path("data/audio") / f"{tid}.wav"
        if not wav.exists():
            return None
        try:
            y, sr = librosa.load(wav, sr=None, mono=True)
            y16 = librosa.resample(y, orig_sr=sr, target_sr=16000)[: 16000 * 60]
            return tid, yamnet_tags(y16)
        except Exception:
            return None

    done = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        with Session(engine) as session:
            for res in pool.map(work, ids):
                if res is None:
                    continue
                tid, tags = res
                if not tags:
                    continue
                session.execute(
                    text(
                        "UPDATE audio_features SET tags = :tags, "
                        "vocal_ratio = :vr WHERE track_id = :tid"
                    ),
                    {
                        "tags": json.dumps(tags, ensure_ascii=False),
                        "vr": tags["vocal_ratio"],
                        "tid": tid,
                    },
                )
                done += 1
                if done % 200 == 0:
                    session.commit()
                    print(f"  {done} пересчитано…")
            session.commit()
    print(f"готово: {done}")


if __name__ == "__main__":
    main()
