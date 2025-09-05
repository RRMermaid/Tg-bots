import os
from dotenv import load_dotenv

load_dotenv()  # Загружает переменные окружения из .env

api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    raise RuntimeError("OPENAI_API_KEY отсутствует в окружении")

from openai import OpenAI
client = OpenAI(api_key=api_key)
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)

from config import TELEGRAM_BOT_TOKEN
from handlers.start_flow import (
    start, handle_contact_or_skip, handle_local_time,
    handle_morning_hour, handle_evening_hour,
    ask_gender, ask_age, ask_weight, ask_height,
    ask_activity, ask_goal, show_calorie_corridor
)
from handlers.meals import record_meal
from handlers.misc import help_command, cancel, handle_weight, on_error
from handlers.analyze import analyze_day_command
from states import BotState
from logging_config import setup_logging

# 🆕 импортируем кэш и загрузку всех пользователей
from services.storage import users_data
from db import load_all_users
from handlers.misc import last_notifications

async def handle_any_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Универсальный обработчик текста:
    - если пользователь уже есть в БД → пишем еду,
    - если нет → просим начать с /start.
    """
    uid = update.effective_user.id
    if uid in users_data and "goal" in users_data[uid]:
        return await record_meal(update, context)
    else:
        await update.message.reply_text("Пожалуйста, начните с команды /start")
        return BotState.ASK_CONTACT


def main():
    setup_logging()
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")

    # 🔥 Загружаем всех пользователей из БД в кэш при запуске
    try:
        users_data.update(load_all_users())
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Не удалось загрузить пользователей из БД: {e}")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            BotState.ASK_CONTACT: [
                MessageHandler(filters.CONTACT | filters.Regex("(?i)^пропустить$"), handle_contact_or_skip)
            ],
            BotState.ASK_LOCAL_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_local_time)],
            BotState.ASK_MORNING_HOUR: [MessageHandler(filters.Regex(r"^\d{2}:00$"), handle_morning_hour)],
            BotState.ASK_EVENING_HOUR: [MessageHandler(filters.Regex(r"^\d{2}:00$"), handle_evening_hour)],

            BotState.ASK_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_gender)],
            BotState.ASK_GENDER:  [MessageHandler(filters.Regex("^(Мужской|Женский)$"), ask_age)],
            BotState.ASK_AGE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_weight)],
            BotState.ASK_WEIGHT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_height)],
            BotState.ASK_HEIGHT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_activity)],
            BotState.ASK_ACTIVITY:[MessageHandler(filters.Regex("^[1-5]{1}$"), ask_goal)],
            BotState.ASK_GOAL:    [MessageHandler(filters.Regex("^(Похудеть|Удержать вес|Набрать массу)$"), show_calorie_corridor)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv)

    # Обработчик чисел → сохраняем вес
    app.add_handler(MessageHandler(filters.Regex(r"^\d+(?:[.,]\d+)?$"), handle_weight))

    # Команды
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("analyze_day", analyze_day_command))

    # 🆕 Универсальный обработчик текста для старых пользователей
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_any_text))

    app.add_error_handler(on_error)

    app.run_polling(allowed_updates=Update.ALL_TYPES)

    application.add_handler(CommandHandler("last_notifications", last_notifications))

if __name__ == "__main__":
    main()
