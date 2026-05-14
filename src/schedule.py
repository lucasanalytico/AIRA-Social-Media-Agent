"""SGT-aware schedule slot computation.

Server runs UTC; all user-facing times are Asia/Singapore.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

SGT = ZoneInfo("Asia/Singapore")
UTC = ZoneInfo("UTC")


def now_sgt() -> datetime:
    return datetime.now(SGT)


def slot_now() -> datetime:
    return datetime.now(UTC)


def slot_tonight_7pm() -> datetime:
    """7pm SGT today. If past 7pm SGT already, rolls to tomorrow 7pm."""
    n = now_sgt()
    target = n.replace(hour=19, minute=0, second=0, microsecond=0)
    if target <= n:
        target += timedelta(days=1)
    return target.astimezone(UTC)


def slot_tomorrow_9am() -> datetime:
    """9am SGT tomorrow."""
    n = now_sgt()
    target = (n + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    return target.astimezone(UTC)


def format_sgt(dt_utc: datetime) -> str:
    return dt_utc.astimezone(SGT).strftime("%a %d %b %Y, %I:%M %p SGT")
