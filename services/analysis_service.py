"""Deterministic calculations use the diary; AI receives small summaries only."""
import logging
from collections import defaultdict
from itertools import combinations
from datetime import timedelta
from statistics import mean
import db
import config
from domain.tz import day_bounds, user_timezone
from prompts import EVENING_SYSTEM_PROMPT, build_evening_prompt
from services.openai_service import get_client
from services.storage import query

logger = logging.getLogger(__name__)

def day_summary(user_id, day, profile):
    start, end = day_bounds(day, profile)
    meals = db.load_meals(user_id, start, end)
    for meal in meals:
        meal["local_time"] = meal["time"].astimezone(user_timezone(profile)).strftime("%H:%M")
    totals = {"meals":len(meals),"water_ml":db.load_water(user_id,start,end)}
    for key in ("calories","protein","fat","carbs"):
        totals[key] = round(sum(m[key] or 0 for m in meals), 1)
        totals[key+"_missing"] = sum(m[key] is None for m in meals)
    gaps = [(b["time"]-a["time"]).total_seconds()/3600 for a,b in zip(meals,meals[1:])]
    totals["gaps_over_5h"] = sum(g > 5 for g in gaps)
    totals["average_gap_hours"] = round(mean(gaps),1) if gaps else None
    weights = db.get_weights(user_id,day-timedelta(days=1),day)
    return {"date":day.isoformat(),"totals":totals,"meals":meals,"weights":weights,
            "goal":profile.get("goal"),
            "target_weight":profile.get("target_weight"),
            "focus_areas":profile.get("focus_areas") or [],
            "limitations":profile.get("limitations"),
            "corridor":{"lower":profile.get("calorie_lower"),"upper":profile.get("calorie_upper")}}

def history_summary(user_id, end_day, profile, days=14):
    if not 1 <= days <= 28:
        raise ValueError("History windows must be bounded")
    start_day = end_day-timedelta(days=days-1)
    start, end = day_bounds(start_day,profile)[0], day_bounds(end_day,profile)[1]
    meals = db.load_meals(user_id,start,end)
    weights = db.get_weights(user_id,start_day,end_day)
    daily = defaultdict(list)
    tz = user_timezone(profile)
    for meal in meals:
        daily[meal["time"].astimezone(tz).date()].append(meal)
    def period(first,last):
        selected = [m for d, rows in daily.items() if first <= d <= last for m in rows]
        active_days = sum(first <= d <= last for d in daily)
        names = {item["name"] for m in selected for item in (m["items"] or [])}
        gaps = [(b["time"]-a["time"]).total_seconds()/3600
                for d, rows in daily.items() if first <= d <= last
                for a,b in zip(rows,rows[1:])]
        ws = [w for d,w in weights if first <= d <= last]
        return {"logged_days":active_days,"logged_meals":len(selected),"unique_foods":len(names),
                "average_gap_hours":round(mean(gaps),1) if gaps else None,
                "long_gaps":sum(g > 5 for g in gaps),
                "weight_measurements":len(ws),
                "average_weight":round(mean(ws),2) if len(ws) >= 3 else None}
    split = end_day-timedelta(days=6)
    return {"window_days":days,"logged_days":len(daily),"weight_measurements":len(weights),
            "previous_week":period(start_day,split-timedelta(days=1)),
            "recent_week":period(split,end_day),
            "interpretation":"Only logged meals; missing days are unknown, not zero intake."}

def food_patterns(user_id, end_day, profile):
    start_day = end_day-timedelta(days=27)
    start, end = day_bounds(start_day,profile)[0], day_bounds(end_day,profile)[1]
    meals = db.load_meals(user_id,start,end)
    weights = dict(db.get_weights(user_id,start_day,end_day+timedelta(days=1)))
    food_days = defaultdict(set)
    tz = user_timezone(profile)
    for meal in meals:
        day = meal["time"].astimezone(tz).date()
        names = {item["name"] for item in meal["items"] or []}
        food_days[day].update(names)
        # Pairs are combinations within a recorded meal, not a whole-day recipe.
        for pair in combinations(sorted(names), 2):
            food_days[day].add(" + ".join(pair))
    # Only days with a food record and both consecutive weight measurements count.
    pairs = {d:weights[d+timedelta(days=1)]-weights[d] for d in food_days
             if d in weights and d+timedelta(days=1) in weights}
    results = []
    for food in {f for day in pairs for f in food_days[day]}:
        with_food = [delta for d,delta in pairs.items() if food in food_days[d]]
        without = [delta for d,delta in pairs.items() if food not in food_days[d]]
        if len(with_food) < 3 or len(without) < 3:
            continue
        results.append({"food":food,"with_days":len(with_food),"without_days":len(without),
            "with_mean_kg":round(mean(with_food),2),"without_mean_kg":round(mean(without),2)})
    return sorted(results,key=lambda r:abs(r["with_mean_kg"]-r["without_mean_kg"]),reverse=True)[:5]


def routine_weight_pattern(user_id, end_day, profile):
    """Compare next-morning changes on sufficiently logged regular/irregular days."""
    start_day = end_day-timedelta(days=27)
    start,end = day_bounds(start_day,profile)[0],day_bounds(end_day,profile)[1]
    meals = db.load_meals(user_id,start,end)
    weights = dict(db.get_weights(user_id,start_day,end_day+timedelta(days=1)))
    daily = defaultdict(list)
    tz = user_timezone(profile)
    for meal in meals:
        daily[meal["time"].astimezone(tz).date()].append(meal)
    regular,irregular = [],[]
    for day,rows in daily.items():
        if len(rows) < 3 or day not in weights or day+timedelta(days=1) not in weights:
            continue
        gaps = [(b["time"]-a["time"]).total_seconds()/3600 for a,b in zip(rows,rows[1:])]
        delta = weights[day+timedelta(days=1)]-weights[day]
        (regular if gaps and max(gaps) <= 4 else irregular).append(delta)
    if len(regular) < 3 or len(irregular) < 3:
        return None
    return {"regular_days":len(regular),"irregular_days":len(irregular),
            "regular_mean_kg":round(mean(regular),2),"irregular_mean_kg":round(mean(irregular),2)}

def render_totals(day):
    t = day["totals"]
    lines = [f"Твой дневник за {day['date']}: {t['meals']} приёмов пищи."]
    for meal in day["meals"]:
        calories = "нет оценки" if meal["calories"] is None else f"~{meal['calories']} ккал"
        lines.append(f"• {meal['local_time']} — {meal['raw']} ({calories})")
    def amount(key,label,unit):
        suffix = " (часть значений неизвестна)" if t[key+"_missing"] else ""
        return f"{label}: ~{t[key]:g} {unit}{suffix}."
    lines.extend([amount("calories","Калории","ккал"),amount("protein","Белки","г"),
                  amount("fat","Жиры","г"),amount("carbs","Углеводы","г")])
    low,high = day.get("corridor",{}).get("lower"),day.get("corridor",{}).get("upper")
    if low is not None and high is not None and not t["calories_missing"]:
        if low <= t["calories"] <= high:
            lines.append(f"Ориентир {low}–{high} ккал соблюдён.")
        elif t["calories"] < low:
            lines.append(f"По записям получилось примерно на {round(low-t['calories'])} ккал ниже ориентира.")
        else:
            lines.append(f"По записям получилось примерно на {round(t['calories']-high)} ккал выше ориентира.")
    if t["average_gap_hours"] is not None:
        lines.append(f"Средний интервал между записями: {t['average_gap_hours']} ч.")
    if t["gaps_over_5h"]:
        lines.append(f"Интервалов дольше 5 часов: {t['gaps_over_5h']}.")
    if t["water_ml"]:
        lines.append(f"Записанная вода: {t['water_ml']} мл.")
    if day.get("weights"):
        today = next((weight for stamp,weight in day["weights"] if stamp.isoformat()==day["date"]),None)
        if today is not None:
            lines.append(f"Вес: {today:g} кг.")
    return "\n".join(lines)

async def analyze_day(day, history):
    if not day["meals"]:
        from nutrition import EVENING_EMPTY
        return EVENING_EMPTY
    client = get_client()
    fallback = ("Спасибо, что записываешь питание честно — здесь нет еды, за которую нужно "
                "стыдить себя или которую нужно отрабатывать. Завтра выбери один посильный шаг "
                "для разнообразия, например добавь фрукт, овощ или другой доступный продукт. "
                "Это забота о себе, а не экзамен на идеальность. А сейчас пора отдохнуть и выспаться.")
    if client is None:
        return fallback
    try:
        response = await client.chat.completions.create(
            model=config.OPENAI_MODEL_ID,
            messages=[{"role":"system","content":EVENING_SYSTEM_PROMPT},
                      {"role":"user","content":build_evening_prompt(day,history)}],
            max_tokens=450,temperature=0.4)
        choice = response.choices[0]
        if choice.finish_reason != "stop" or not choice.message.content:
            return fallback
        return choice.message.content.strip()[:2000]
    except Exception as exc:
        logger.warning("Daily analysis failed: %s",type(exc).__name__)
        return fallback

async def daily_report(user_id, profile, day):
    summary = await query(day_summary,user_id,day,profile)
    if not summary["meals"]:
        return await analyze_day(summary,{})
    history = await query(history_summary,user_id,day,profile)
    advice = await analyze_day(summary,history)
    return render_totals(summary)+"\n\n"+advice

async def send_long(message, text):
    # Telegram text messages have a size limit; no HTML or unsafe Markdown.
    while len(text) > 3800:
        split = text.rfind("\n",0,3800)
        if split < 1:
            split = 3800
        await message.reply_text(text[:split])
        text = text[split:].lstrip("\n")
    if text:
        await message.reply_text(text)
