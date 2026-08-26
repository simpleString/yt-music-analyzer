"""Одноразовый пересчёт tags/vocal_ratio по кэшированным wav (Essentia).

Заменяет старые YAMNet-теги: жанры (Discogs 400 стилей), инструменты
(Jamendo), настроения (moodtheme), вокал (калиброванная вероятность).
Запуск: .venv/bin/python tools/retag_essentia.py [потоки]
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlmodel import Session

from app.db import engine
from app.services.essentia_tags import analyze


def main() -> None:
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
    print(f"треков к пересчёту: {len(ids)}")

    from essentia.standard import MonoLoader

    def work(tid: str):
        wav = Path("data/audio") / f"{tid}.wav"
        if not wav.exists():
            return None
        try:
            audio = MonoLoader(
                filename=str(wav), sampleRate=16000, resampleQuality=4
            )()
            return tid, analyze(audio[: 16000 * 60])
        except Exception as exc:  # noqa: BLE001
            return tid, exc

    done = errors = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        with Session(engine) as session:
            for res in pool.map(work, ids):
                if res is None:
                    continue
                tid, tags = res
                if isinstance(tags, Exception) or not tags:
                    errors += 1
                    continue
                session.execute(
                    text(
                        "UPDATE audio_features SET tags = :tags, "
                        "vocal_ratio = :vr WHERE track_id = :tid"
                    ),
                    {
                        "tags": json.dumps(
                            tags, ensure_ascii=False, default=float
                        ),
                        "vr": tags["vocal_ratio"],
                        "tid": tid,
                    },
                )
                done += 1
                if done % 100 == 0:
                    session.commit()
                    print(f"  {done} пересчитано (ошибок: {errors})…")
            session.commit()
    print(f"готово: {done}, ошибок/пропусков: {errors}")


if __name__ == "__main__":
    main()
