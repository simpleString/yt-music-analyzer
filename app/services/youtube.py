import math
import re

import httpx
from sqlmodel import Session

from app.config import settings
from app.services.jobs import get_meta, quota_key, set_meta

API_URL = "https://www.googleapis.com/youtube/v3/videos"
BATCH = 50

DUR_RE = re.compile(
    r"^P(?:(?P<d>\d+)D)?T?(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?$"
)


def parse_iso_duration(value: str) -> float | None:
    m = DUR_RE.match(value or "")
    if not m:
        return None
    d = {k: int(v) for k, v in m.groupdict().items() if v}
    return d.get("d", 0) * 86400 + d.get("h", 0) * 3600 + d.get("m", 0) * 60 + d.get("s", 0)


def has_api_key() -> bool:
    return bool(settings.youtube_api_key.strip())


def quota_left(session: Session) -> int:
    used = int(get_meta(session, quota_key()) or 0)
    return settings.youtube_daily_quota - used


def fetch_videos_details(video_ids: list[str]) -> dict[str, dict]:
    """videos.list батчами по 50 ID. Возвращает {video_id: {duration, category_id, channel, title}}."""
    result: dict[str, dict] = {}
    if not has_api_key():
        return result
    with httpx.Client(timeout=20) as client:
        for i in range(0, len(video_ids), BATCH):
            chunk = video_ids[i : i + BATCH]
            with Session() as session:
                if quota_left(session) <= 100:
                    break
                used = int(get_meta(session, quota_key()) or 0)
                set_meta(session, quota_key(), str(used + 1))
                session.commit()
            try:
                resp = client.get(
                    API_URL,
                    params={
                        "key": settings.youtube_api_key,
                        "part": "snippet,contentDetails",
                        "id": ",".join(chunk),
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
            except (httpx.HTTPError, ValueError):
                continue
            for item in payload.get("items", []):
                dur = parse_iso_duration(
                    item.get("contentDetails", {}).get("duration", "")
                )
                snippet = item.get("snippet", {})
                result[item["id"]] = {
                    "duration": dur,
                    "category_id": _to_int(snippet.get("categoryId")),
                    "channel": snippet.get("channelTitle", ""),
                    "title": snippet.get("title", ""),
                }
    return result


def _to_int(v: object) -> int | None:
    try:
        return int(v) if v is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def duration_minutes_ok(seconds: float | None) -> bool:
    if seconds is None:
        return False
    return math.isnan(seconds) is False and 60 <= seconds <= 600
