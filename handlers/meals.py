import re
from datetime import datetime, timedelta, timezone
from telegram import Update
from telegram.ext import ContextTypes
from services.storage import users_data
from services.openai_service import estimate_meal_nutrition
from db import save_meal
from states import BotState
from domain.tz import get_user_offset

async def record_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    text = (update.message.text or "").strip()
    data = users_data.setdefault(user_id, {})

    if "goal" not in data:
        await update.message.reply_text("Пожалуйста, начните с команды /start")
        return BotState.RECORD_MEAL

    now_sys = datetime.now(timezone.utc)
    now_user = now_sys + get_user_offset(data)

    # === Ручной ввод калорий ===
    t_low = text.lower()
    cal_match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:к+кал+|кал+|калл+|калорий|ккалл+|k+cal+|kcals?|cal(?:ories)?)\b",
        t_low
    )
    if cal_match:
        val = cal_match.group(1)
        cals = int(float(val.replace(",", ".")))

        data.setdefault("meals", []).append({"time": now_user, "calories": cals, "raw": text})
        data["pending_meal"] = None

        save_meal(
            user_id=user_id,
            time_obj=now_user,
            calories=cals,
            protein=None,
            fat=None,
            carbs=None,
            raw=text,
            meal_kind="snack",
            portion=1.0,
            oil_extra=0
        )

        await update.message.reply_text(f"Записано: {cals} ккал (ручной ввод).")
        return BotState.RECORD_MEAL

    # === Автооценка через OpenAI ===
    await update.message.reply_text("Считаю калории…")
    nutri = {}
    try:
        nutri = await estimate_meal_nutrition(t_low)
    except Exception:
        pass

    if not nutri or "calories" not in nutri:
        await update.message.reply_text(
            "Не удалось оценить блюдо автоматически 😕 Пришлите калории числом, например: 350 ккал."
        )
        return BotState.RECORD_MEAL

    cals = int(nutri["calories"])
    p = nutri.get("protein_g")
    f = nutri.get("fat_g")
    ch = nutri.get("carbs_g")
    meal_kind = nutri.get("meal_kind") or "plate"

    meal_entry = {
        "time": now_user,
        "calories": cals,
        "protein": p,
        "fat": f,
        "carbs": ch,
        "raw": text,
        "meal_kind": meal_kind,
        "auto": True,
    }
    data.setdefault("meals", []).append(meal_entry)

    save_meal(
        user_id=user_id,
        time_obj=now_user,
        calories=cals,
        protein=p,
        fat=f,
        carbs=ch,
        raw=text,
        meal_kind=meal_kind,
        portion=1.0,
        oil_extra=0
    )

    # === Определяем задержку для напоминания ===
    if meal_kind == "soup" or ("яич" in t_low) or ("омлет" in t_low) or ("яйц" in t_low):
        delay = timedelta(hours=2)
        reminder_text = "Важно покушать через 2 часа после лёгкого блюда (суп/яйца)!"
    else:
        delay = timedelta(hours=3)
        reminder_text = "Через 3 часа после этого приёма пищи важно позаботиться о себе и покушать!"

    async def personalized_reminder(ctx: ContextTypes.DEFAULT_TYPE):
        try:
            await ctx.bot.send_message(chat_id=user_id, text=reminder_text)
        except Exception:
            pass

    # === Удаляем старые напоминания, чтобы не спамить ===
    for job in context.application.job_queue.get_jobs_by_name(f"next_meal_{user_id}"):
        job.schedule_removal()

    # === Ставим новое напоминание ===
    context.application.job_queue.run_once(
        personalized_reminder,
        when=delay,
        name=f"next_meal_{user_id}",
        data=user_id,
    )

    macros = (
        f"\nБ: {round(p,1)} г • Ж: {round(f,1)} г • У: {round(ch,1)} г"
        if all(x is not None for x in (p, f, ch)) else ""
    )
    gap = 2 if delay == timedelta(hours=2) else 3
    await update.message.reply_text(f"Записано: ~{cals} ккал.{macros}\nСледующий приём через ~{gap} ч.")

    return BotState.RECORD_MEAL
