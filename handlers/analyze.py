from telegram import Update
from telegram.ext import ContextTypes
from db import load_meals_for_today, get_weight_trend
from services.analysis_service import analyze_day

async def analyze_day_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    meals = load_meals_for_today(user_id)
    weight_trend = get_weight_trend(user_id) or "нет данных"

    if not meals:
        await update.message.reply_text("Сегодня ещё нет записанных приёмов пищи.")
        return

    analysis = analyze_day(meals, weight_trend)
    text = "Твой рацион за сегодня:\n- " + "\n- ".join(meals) + "\n\n" + analysis

    await update.message.reply_text(text)
