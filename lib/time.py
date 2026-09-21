from datetime import datetime, timedelta, timezone

WIB_OFFSET = timedelta(hours=7)

WIB_TZ = timezone(WIB_OFFSET, name="Asia/Jakarta")


def wib_now() -> datetime:
    """Current naive datetime in WIB (UTC+7)."""
    return (datetime.now(WIB_TZ)).replace(tzinfo=None)


def to_wib(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(WIB_TZ).replace(tzinfo=None)
    return dt + WIB_OFFSET