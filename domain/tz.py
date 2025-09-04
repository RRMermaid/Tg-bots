import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

def get_user_offset(user: dict) -> timedelta:
    """Возвращает смещение пользователя в виде timedelta.
    Если в данных нет tz_offset, вернёт timedelta(0)."""
    minutes = 0
    if user:
        minutes = user.get("tz_offset") or 0
    return timedelta(minutes=minutes)

def parse_tz(text: str):
    t = (text or "").strip()
    if "/" in t:
        try:
            return ZoneInfo(t)
        except Exception:
            pass
    m = re.fullmatch(r'(?:UTC|GMT)?\s*([+-]?\d{1,2})', t, re.I)
    if m:
        try:
            off = int(m.group(1))
            return timezone(timedelta(hours=off))
        except Exception:
            pass
    return None

def now_local(tzinfo):
    return datetime.now(tzinfo or timezone.utc)
