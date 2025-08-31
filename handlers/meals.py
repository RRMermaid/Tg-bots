import re
from datetime import timedelta
from telegram import Update
from telegram.ext import ContextTypes
from services.storage import users_data
from services.openai_service import estimate_meal_nutrition
from domain.tz import now_local
from states import BotState
from db import save_meal

async def record_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    uid = user.id
    text = (update.message.text or "").strip()
    data = users_data.setdefault(uid, {})

    if "goal" not in data:
        await update.message.reply_text("Пожалуйста, начните с команды /start")
        return BotState.RECORD_MEAL

    t_low = text.lower()
    cal_match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:к+кал+|кал+|калл+|калорий|ккалл+|k+cal+|kcals?|cal(?:ories)?)\b",
        t_low
    )
    if cal_match:
        cals = int(float(cal_match.group(1).replace(",", ".")))
        now = now_local(data.get("tzinfo"))
        data.setdefault("meals", []).append({"time": now, "calories": cals, "raw": text})
        save_meal(uid, now, cals, None, None, None, text, "snack", 1.0, 0)
        await update.message.reply_text(f"Записано: {cals} ккал (ручной ввод).")
        return BotState.RECORD_MEAL

    await update.message.reply_text("Считаю калории…")
    nutri = await estimate_meal_nutrition(t_low)
    if not nutri or "calories" not in nutri:
        await update.message.reply_text("Не удалось оценить блюдо автоматически 😕 Пришлите калории числом, например: 350 ккал.")
        return BotState.RECORD_MEAL

    now = now_local(data.get("tzinfo"))
    cals = int(nutri["calories"])
    p = nutri.get("protein_g")
    f = nutri.get("fat_g")
    ch = nutri.get("carbs_g")
    meal_kind = nutri.get("meal_kind") or "plate"

    entry = {"time": now, "calories": cals, "protein": p, "fat": f, "carbs": ch, "raw": text, "meal_kind": meal_kind, "auto": True}
    data.setdefault("meals", []).append(entry)

    save_meal(uid, now, cals, p, f, ch, text, meal_kind, 1.0, 0)

    if meal_kind == "soup" or ("яич" in t_low) or ("омлет" in t_low) or ("яйц" in t_low):
        delay = timedelta(hours=2); reminder_text = "Важно покушать через 2 часа после лёгкого блюда (суп/яйца)!"
    else:
        delay = timedelta(hours=3); reminder_text = "Через 3 часа после этого приёма пищи важно позаботиться о себе и покушать!"

    async def personalized_reminder(ctx: ContextTypes.DEFAULT_TYPE):
        try:
            await ctx.bot.send_message(chat_id=uid, text=reminder_text)
        except Exception:
            pass

    context.application.job_queue.run_once(personalized_reminder, when=delay)

    macros = ""
    if all(x is not None for x in (p, f, ch)):
        macros = f"\nБ: {round(p,1)} г • Ж: {round(f,1)} г • У: {round(ch,1)} г"
    gap = 2 if delay.seconds == 7200 else 3
    await update.message.reply_text(f"Записано: ~{cals} ккал.{macros}\nСледующий приём через ~{gap} ч.")
    return BotState.RECORD_MEAL
