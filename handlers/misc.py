from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes
from telegram.ext import ContextTypes, ConversationHandler
from texts import HELP
from services.storage import users_data
from db import save_weight
from domain.tz import now_local

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP, parse_mode="HTML")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Диалог завершен. Если хотите начать сначала, нажмите /start",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def handle_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    try:
        weight = float(update.message.text.replace(",", "."))
        tzinfo = users_data.get(user.id, {}).get("tzinfo")
        today = now_local(tzinfo).date()
        users_data.setdefault(user.id, {}).setdefault("weights", []).append({"date": today, "weight": weight})
        await update.message.reply_text(f"Спасибо, вес {weight} кг записан.")
        save_weight(user.id, today, weight)
    except ValueError:
        await update.message.reply_text("Пожалуйста, введи корректное число для веса (например, 70.5).")

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    # Не раскрываем stack в чат, только логируем
    import logging
    logging.getLogger(__name__).exception("Ошибка во время обработки апдейта", exc_info=context.error)
