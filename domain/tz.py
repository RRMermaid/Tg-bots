import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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
