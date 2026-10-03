"""Parse timestamps and validate AI output before it reaches SQL."""
import math
import re
from datetime import timedelta
from config import MAX_MEALS_PER_MESSAGE, MAX_MESSAGE_CHARS, MAX_MEAL_CHARS
from domain.tz import user_timezone

PORTION_RE = re.compile(
    r"(?:\b\d+(?:[.,]\d+)?\s*(?:г|гр|кг|мл|л|шт|штук[аи]?|лож(?:ка|ки|ек)|"
    r"ст\.\s*л\.?|ч\.\s*л\.?|стакан(?:а|ов)?|чашк(?:а|и|ек)|кус(?:ок|ка|ков)|"
    r"тарелк(?:а|и|у)|порци(?:я|и|ю)|пачк(?:а|и|у)|половин(?:а|у|ы))\b|"
    r"\b(?:лож(?:ка|ки|ек)|тарелк(?:а|и|у)|стакан|чашка|кусок|порция|половина)\b)", re.I)


def has_portion_detail(text: str) -> bool:
    """A calorie total or an explicit count/household measure is enough to estimate."""
    if re.search(r"\d+(?:[.,]\d+)?\s*(?:ккал|калорий|kcal)\b",text,re.I):
        return True
    if PORTION_RE.search(text):
        return True
    # Countable foods: "2 яйца", "один банан". The timestamp is already removed.
    return bool(re.search(r"\b(?:\d+(?:[.,]\d+)?|один|одна|одно|два|две|три|четыре|половина)\s+[а-яё]",text,re.I))


def meal_reminder_minutes(raw: str, meal_kind: str) -> int:
    if meal_kind in ("soup","eggs","light") or re.search(r"\b(?:суп|яйц|омлет)",raw,re.I):
        return 120
    return 180

def split_meals(text: str, received_at, profile: dict) -> list[dict]:
    text = text.strip()
    if not text or len(text) > MAX_MESSAGE_CHARS:
        raise ValueError("Напиши до 4000 символов в одном сообщении.")
    if received_at.tzinfo is None:
        raise ValueError("Message timestamp must be aware")
    local = received_at.astimezone(user_timezone(profile))
    yesterday = bool(re.match(r"^вчера\b", text, re.I))
    text = re.sub(r"^вчера\s*", "", text, flags=re.I)
    day = local.date() - timedelta(days=int(yesterday))
    matches = list(re.finditer(r"(?<!\d)(\d{1,2})[:\-](\d{2})(?!\d)", text))
    if len(matches) > MAX_MEALS_PER_MESSAGE:
        raise ValueError("Пришли не больше 8 приёмов пищи за раз.")
    if matches and text[:matches[0].start()].strip(" ,.;\n"):
        raise ValueError("Начни запись со времени: 09:00 яйца, 13:00 гречка.")
    parts = []
    if not matches:
        if yesterday:
            raise ValueError("Для вчерашней записи укажи время: вчера 21:00 ужин.")
        parts = [{"time": local, "raw": text}]
    for i, match in enumerate(matches):
        hh, mm = int(match[1]), int(match[2])
        if hh > 23 or mm > 59:
            raise ValueError("Время должно быть от 00:00 до 23:59.")
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        raw = text[match.end():end].strip(" ,.;\n")
        stamp = local.replace(year=day.year, month=day.month, day=day.day,
                              hour=hh, minute=mm, second=0, microsecond=0)
        if stamp > local + timedelta(minutes=10):
            raise ValueError("Это время ещё не наступило. Для вчерашней еды добавь «вчера».")
        parts.append({"time": stamp, "raw": raw})
    if any(not p["raw"] or len(p["raw"]) > MAX_MEAL_CHARS for p in parts):
        raise ValueError("Добавь описание еды, до 1500 символов на приём.")
    return parts

def number(value, maximum, allow_none=False):
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Nutrition values must be numbers")
    if not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError("Invalid nutrition value")
    return round(value, 1)

def validate_nutrition(data: dict) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("is_food"), bool):
        raise ValueError("Missing food classification")
    if not data["is_food"]:
        return {"is_food": False}
    result = {
        "is_food": True, "calories": round(number(data.get("calories"), 20000)),
        "protein_g": number(data.get("protein_g"), 2000, True),
        "fat_g": number(data.get("fat_g"), 2000, True),
        "carbs_g": number(data.get("carbs_g"), 5000, True),
        "meal_kind": str(data.get("meal_kind", "meal"))[:30],
        "estimated": True, "items": [],
        "assumptions": str(data.get("assumptions") or "")[:300],
        "needs_clarification": bool(data.get("needs_clarification",False)),
        "clarification_question": str(data.get("clarification_question") or "")[:300],
        "comment": str(data.get("comment") or "")[:300],
    }
    items = data.get("items")
    if not isinstance(items, list) or len(items) > 20:
        raise ValueError("Invalid ingredients")
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            raise ValueError("Invalid ingredient")
        result["items"].append({
            "name": item["name"].strip().lower()[:80],
            "grams": number(item.get("grams"), 10000, True),
        })
    result["reminder_minutes"] = meal_reminder_minutes("",result["meal_kind"])
    return result

def manual_nutrition(text: str):
    if re.search(r"-\s*\d+\s*(?:ккал|kcal)", text, re.I):
        raise ValueError("Калории не могут быть отрицательными.")
    match = re.search(r"(?<![\d-])(\d+(?:[.,]\d+)?)\s*(?:ккал|калорий|kcal)\b", text, re.I)
    if not match:
        return None
    # Negative values and multiple calorie totals are ambiguous: ask for clarification.
    if re.search(r"-\s*\d+\s*(?:ккал|kcal)", text, re.I):
        raise ValueError("Калории не могут быть отрицательными.")
    calories = round(number(float(match[1].replace(",", ".")), 20000))
    return {"is_food": True, "calories": calories, "protein_g": None,
            "fat_g": None, "carbs_g": None, "items": [], "meal_kind": "manual",
            "estimated": False, "assumptions": "Калории указаны вручную; БЖУ неизвестны.",
            "needs_clarification":False,"clarification_question":"",
            "comment":"Калории указаны вручную, поэтому состав КБЖУ пока не рассчитан.",
            "reminder_minutes":180}
