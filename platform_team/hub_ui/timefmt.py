# Adapted from https://github.com/gonsoomoon-ml/ai-governance-hub hub/timefmt.py at commit 02035ca (MIT-0)
"""Screen times: a time AWS or a job gives (a datetime, or an ISO string) in the zone the screen shows
(HUB_UI_TZ, default Asia/Seoul), as MM/DD HH:MM:SS."""
from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_ZONE = "Asia/Seoul"


def zone(name: str) -> tzinfo:
    """Zone name -> tzinfo; UTC for a name it does not know, so a page never fails on it."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return UTC


def fmt_ts(value: datetime | str | None, zone_name: str) -> str:
    """A time -> 'MM/DD HH:MM:SS' in the zone. Empty stays empty; a string it cannot read is returned as it is.
    A time without a zone is read as UTC."""
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(zone(zone_name)).strftime("%m/%d %H:%M:%S")
