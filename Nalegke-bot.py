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


def main():
    setup_logging()
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")

    # 🆕 Подгружаем всех пользователей из БД в кэш при запуске
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

            BotState.RECORD_MEAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, record_meal)],
            BotState.MONITORING:  [MessageHandler(filters.TEXT & ~filters.COMMAND, record_meal)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.Regex(r"^\d+(?:[.,]\d+)?$"), handle_weight))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("analyze_day", analyze_day_command))
    app.add_error_handler(on_error)

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
