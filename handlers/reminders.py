from telegram.ext import ContextTypes
from services.storage import users_data
from domain.tz import now_local
from db import analyze_user_day

async def reminder_4h(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    now = now_local(users_data.get(user_id, {}).get("tzinfo"))
    if now.hour >= 21:
        return
    try:
        await context.bot.send_message(chat_id=user_id, text="Критично важно покушать примерно сейчас!")
    except Exception:
        pass

async def morning_weight_request_user(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    try:
        await context.bot.send_message(chat_id=user_id, text="Доброе утро! Пожалуйста, сообщи свой текущий вес 🌤️")
    except Exception:
        pass

async def evening_report_user(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    data = users_data.get(user_id) or {}
    if not data:
        return
    date_today = now_local(data.get("tzinfo")).date()
    meals = [m for m in data.get("meals", []) if m.get("time") and m["time"].date() == date_today]
    if not meals:
        return
    calories_today = sum(m.get("calories", 0) for m in meals)
    prot = sum((m.get("protein") or 0) for m in meals)
    fat  = sum((m.get("fat") or 0) for m in meals)
    carb = sum((m.get("carbs") or 0) for m in meals)
    text = (
        "Итог дня:\n"
        f"• Калории: {calories_today} ккал\n"
        f"• Приёмов пищи: {len(meals)}\n"
        f"• КБЖУ: Б {round(prot,1)} г / Ж {round(fat,1)} г / У {round(carb,1)} г\n"
        "Напоминание: полноценная тарелка (гарнир+белок+овощи) помогает держать режим. Вода и сон — тоже важны 💧😴"
    )
    try:
        await context.bot.send_message(chat_id=user_id, text=text)
        advice = analyze_user_day(user_id, date_today)
        if advice:
            await context.bot.send_message(chat_id=user_id, text=advice)
    except Exception:
        pass
