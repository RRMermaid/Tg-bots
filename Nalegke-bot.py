import re
from datetime import datetime

from domain.tz import now_local
from db import save_meal, analyze_user_day, load_all_users
from handlers.reminders import reminder_4h

from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)

from config import TELEGRAM_BOT_TOKEN, OPENAI_API_KEY
from openai import OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

from handlers.start_flow import (
    start, handle_contact_or_skip, handle_local_time,
    handle_morning_hour, handle_evening_hour,
    ask_gender, ask_age, ask_weight, ask_height,
    ask_activity, ask_goal, show_calorie_corridor
)
from handlers.meals import record_meal
from handlers.misc import help_command, cancel, handle_weight, on_error, last_notifications
from handlers.analyze import analyze_day_command
from states import BotState
from logging_config import setup_logging

# 🆕 импортируем кэш и загрузку всех пользователей
from services.storage import users_data

async def handle_any_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    tz = users_data.get(uid, {}).get("tzinfo")
    text = (update.message.text or "").strip()

    # Регулярка ищет время (09:00, 9-30 и т.п.)
    pattern = r"(\d{1,2}[:\-]\d{2})"
    parts = re.split(pattern, text)

    if len(parts) < 3:
        await update.message.reply_text("⚠️ Укажи время в формате 09:00 еда ...")
        return

    last_meal_time = None

    # Парсим куски: время → описание
    for i in range(1, len(parts), 2):
        time_str = parts[i].replace("-", ":")
        desc = parts[i+1].strip(" ,.;\n")

        # Парсим время
        try:
            hh, mm = map(int, time_str.split(":"))
            meal_time = now_local(tz).replace(hour=hh, minute=mm, second=0, microsecond=0)
        except Exception:
            continue

        # Проверка на воду 💧
        if re.search(r"\bвода\b", desc.lower()):
            await update.message.reply_text(f"💧 {time_str} — вода учтена, молодец!")
            continue

        # Сохраняем еду
        save_meal(uid, meal_time, desc)
        last_meal_time = meal_time

        # Итог дня после этого приёма
        stats = analyze_user_day(uid)
        await update.message.reply_text(
            f"🍽 {time_str} — '{desc}' записано!\n\n"
            f"📊 Итог на {time_str}:\n"
            f"Калории: {stats['calories']} ккал\n"
            f"Белки: {stats['protein']} г\n"
            f"Жиры: {stats['fat']} г\n"
            f"Углеводы: {stats['carbs']} г"
        )

    # Обновляем таймер следующего приёма
    if last_meal_time:
        context.job_queue.run_once(
            reminder_4h,
            when=4*60*60,
            data=uid,
            name=f"next_meal_{uid}",
            replace_existing=True,
        )
        await update.message.reply_text(
            f"⏱ Следующий приём пищи напомню через 4 часа от {last_meal_time.strftime('%H:%M')}."
        )
        
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

    # Основной ConversationHandler
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            BotState.ASK_CONTACT: [
                MessageHandler(filters.CONTACT | filters.Regex("(?i)^пропустить$"), handle_contact_or_skip)
            ],
            BotState.ASK_LOCAL_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_local_time)],
            BotState.ASK_MORNING_HOUR: [MessageHandler(filters.Regex(r"^\d{2}:00$"), handle_morning_hour)],
            BotState.ASK_EVENING_HOUR: [MessageHandler(filters.Regex(r"^\d{2}:00$"), handle_evening_hour)],

            BotState.ASK_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_gender)],
            BotState.ASK_GENDER:   [MessageHandler(filters.Regex("^(Мужской|Женский)$"), ask_age)],
            BotState.ASK_AGE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_weight)],
            BotState.ASK_WEIGHT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_height)],
            BotState.ASK_HEIGHT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_activity)],
            BotState.ASK_ACTIVITY: [MessageHandler(filters.Regex("^[1-5]{1}$"), ask_goal)],
            BotState.ASK_GOAL:     [MessageHandler(filters.Regex("^(Похудеть|Удержать вес|Набрать массу)$"), show_calorie_corridor)],

            # 🆕 Основной режим после анкеты
            BotState.MONITORING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_any_text)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    # Регистрируем обработчики
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.Regex(r"^\d+(?:[.,]\d+)?$"), handle_weight))  # Вес
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("analyze_day", analyze_day_command))
    app.add_handler(CommandHandler("last_notifications", last_notifications))
    app.add_error_handler(on_error)

    # 🚀 Запуск
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
