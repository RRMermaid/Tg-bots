"""User clocks are independent of the operating system clock/timezone."""
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
CITY_ZONES = {
    "тюмень": "Asia/Yekaterinburg", "екатеринбург": "Asia/Yekaterinburg",
    "челябинск": "Asia/Yekaterinburg", "уфа": "Asia/Yekaterinburg",
    "пермь": "Asia/Yekaterinburg", "курган": "Asia/Yekaterinburg",
    "москва": "Europe/Moscow", "санкт-петербург": "Europe/Moscow",
    "санкт петербург": "Europe/Moscow", "казань": "Europe/Moscow",
    "нижний новгород": "Europe/Moscow", "ростов-на-дону": "Europe/Moscow",
    "воронеж": "Europe/Moscow", "краснодар": "Europe/Moscow",
    "самара": "Europe/Samara", "ижевск": "Europe/Samara",
    "саратов": "Europe/Saratov", "астрахань": "Europe/Astrakhan",
    "волгоград": "Europe/Volgograd", "омск": "Asia/Omsk",
    "новосибирск": "Asia/Novosibirsk", "барнаул": "Asia/Barnaul",
    "томск": "Asia/Tomsk", "кемерово": "Asia/Novokuznetsk",
    "красноярск": "Asia/Krasnoyarsk", "иркутск": "Asia/Irkutsk",
    "чита": "Asia/Chita", "якутск": "Asia/Yakutsk",
    "хабаровск": "Asia/Vladivostok", "владивосток": "Asia/Vladivostok",
    "магадан": "Asia/Magadan", "петропавловск-камчатский": "Asia/Kamchatka",
    "калининград": "Europe/Kaliningrad",
}

def parse_tz(text: str):
    cleaned = re.sub(r"^г\.?\s*","",text.strip(),flags=re.I)
    value = CITY_ZONES.get(cleaned.lower(), cleaned)
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        pass
    match = re.fullmatch(r"(?:UTC|GMT)\s*([+-])(\d{1,2})(?::(\d{2}))?", value, re.I)
    if not match:
        return None
    hours, minutes = int(match[2]), int(match[3] or 0)
    if hours > 14 or minutes > 59 or (hours == 14 and minutes):
        return None
    total = (hours * 60 + minutes) * (1 if match[1] == "+" else -1)
    return timezone(timedelta(minutes=total))

def timezone_name(tz) -> str:
    if isinstance(tz, ZoneInfo):
        return tz.key
    offset = int(tz.utcoffset(None).total_seconds() / 60)
    return f"UTC{'+' if offset >= 0 else '-'}{abs(offset)//60:02d}:{abs(offset)%60:02d}"

def user_timezone(user: dict):
    if user.get("timezone"):
        result = parse_tz(user["timezone"])
        if result is None:
            raise ValueError("Invalid saved timezone")
        return result
    # Legacy records remain readable, but reminders require an explicit timezone.
    return timezone(timedelta(minutes=int(user.get("tz_offset") or 0)))

def now_local(tz=None):
    if isinstance(tz, dict):
        tz = user_timezone(tz)
    return datetime.now(tz or UTC)

def day_bounds(day, user: dict):
    tz = user_timezone(user)
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)

def parse_clock(text: str) -> str:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text.strip())
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        raise ValueError("Use HH:MM")
    return f"{int(match[1]):02d}:{int(match[2]):02d}"
