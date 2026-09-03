"""Пересчёт тегов/настроений/эмбеддингов по кэшированному аудио (Essentia).

Обновляет: tags (жанры, стили, инструменты, настроения, moodtags),
vocal_ratio, embedding, danceability/acousticness/brightness (модели),
11 колонок mood_*. Аудио не перекачивается — берётся из data/audio.

Запуск: .venv/bin/python tools/retag_essentia.py [потоки]
Ошибки треков собираются и выводятся сводкой; exit-код 1 при ошибках.
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
    print(f"треков к пересчёту: {len(ids)}")

    from essentia.standard import MonoLoader

    def work(tid: str):
        wav = Path("data/audio") / f"{tid}.wav"
        if not wav.exists():
            return tid, FileNotFoundError("нет кэшированного аудио")
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
                    print(f"  {done} пересчитано (ошибок: {errors})…")
            session.commit()

    print(f"готово: {done}, ошибок: {errors}")
    if error_list:
        print("ошибки:")
        for line in error_list:
            print(f"  {line}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
