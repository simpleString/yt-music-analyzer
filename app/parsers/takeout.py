import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

VIDEO_ID_RE = re.compile(r"[?&]v=([\w-]{11})")
WATCH_PREFIX_RE = re.compile(r"^(Просмотрено видео|Watched)\s*")
GONE_MARKERS = ("недоступна", "unavailable")


@dataclass(slots=True)
class RawListen:
    video_id: str
    title: str
    channel: str
    header: str
    listened_at: datetime


def parse_watch_history(data: list[dict], tz_name: str) -> list[RawListen]:
    tz = ZoneInfo(tz_name)
    entries: list[RawListen] = []
    for item in data:
        m = VIDEO_ID_RE.search(item.get("titleUrl") or "")
        if not m:
            continue
        raw_title = item.get("title") or ""
        if not WATCH_PREFIX_RE.match(raw_title):
            continue
        title = WATCH_PREFIX_RE.sub("", raw_title).strip()
        if not title or any(marker in title.lower() for marker in GONE_MARKERS):
            continue
        subs = item.get("subtitles") or []
        channel = subs[0].get("name", "") if subs else ""
        raw_time = item.get("time")
        if not raw_time:
            continue
        try:
            dt = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        except ValueError:
            continue
        listened_at = dt.astimezone(tz).replace(tzinfo=None)
        entries.append(
            RawListen(
                video_id=m.group(1),
                title=title,
                channel=channel,
                header=item.get("header") or "YouTube",
                listened_at=listened_at,
            )
        )

    print(entries)
    return entries


def load_history_file(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Ожидался JSON-список записей истории")
    return data
