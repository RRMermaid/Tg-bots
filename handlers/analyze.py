import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from services.openai_service import get_client
from db import load_meals_for_today

async def analyze_day_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    client = get_client()
    if not client:
        await update.message.reply_text("⚠️ GPT временно недоступен.")
        return

    meals = load_meals_for_today(user_id)
    if not meals:
        await update.message.reply_text("Сегодня ещё не было записей о еде.")
        return

    resp = await asyncio.to_thread(
        client.chat.completions.create,
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Ты нутрициолог. Проанализируй рацион пользователя и дай советы по питанию."},
            {"role": "user", "content": "\n".join(meals)}
        ],
        max_tokens=200,
    )
    advice = resp.choices[0].message.content.strip()
    await update.message.reply_text("📊 Анализ дня:\n\n" + advice)
    