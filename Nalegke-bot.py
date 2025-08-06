import logging
from datetime import datetime, time
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)

# Настройка логирования: запись в файл bot.log и вывод в консоль
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# States ConversationHandler
(
    START,
    ASK_NAME,
    ASK_GENDER,
    ASK_AGE,
    ASK_WEIGHT,
    ASK_HEIGHT,
    ASK_ACTIVITY,
    ASK_GOAL,
    RECORD_MEAL,
    MONITORING,
) = range(10)

users_data = {}

# Клавиатуры
gender_kb = ReplyKeyboardMarkup(
    [["Мужской", "Женский"]], one_time_keyboard=True, resize_keyboard=True)
activity_kb = ReplyKeyboardMarkup(
    [["1", "2", "3", "4", "5"]], one_time_keyboard=True, resize_keyboard=True)
goal_kb = ReplyKeyboardMarkup(
    [["Похудеть", "Удержать вес", "Набрать массу"]],
    one_time_keyboard=True,
    resize_keyboard=True,
)


def calculate_bmr(weight, height, age, gender):
    # Формула Миффлина-Сан Жеора
    if gender == "Мужской":
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161
    return bmr


def calculate_tdee(bmr, activity_level):
    # Коэффициенты активности по шкале 1-5
    factors = {1: 1.2, 2: 1.375, 3: 1.55, 4: 1.725, 5: 1.9}
    return bmr * factors.get(activity_level, 1.2)


def calculate_calorie_range(tdee, goal):
    # Коридор для жиросжигания: от (верхняя - 20%) до (верхняя - 500) ккал
    # Удержание: +/-100 от нормы
    # Набор массы: верхняя + 300 калорий
    if goal == "Похудеть":
        upper = tdee
        lower = max(upper - upper * 0.2, upper - 500)
        return lower, upper
    elif goal == "Удержать вес":
        return tdee - 100, tdee + 100
    else:  # Набрать массу
        return tdee, tdee + 300


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    logger.info(f"Пользователь {user.id} ({user.full_name}) начал диалог")
    await update.message.reply_text(
        "Привет! Я бот по контролю питания и веса.\n"
        "Я помогу тебе отслеживать калории, вести дневник и давать рекомендации.\n"
        "Для начала, представься, пожалуйста. Как тебя зовут?"
    )
    return ASK_NAME


async def ask_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    logger.info(f"Пользователь {user.id} ответил именем: {update.message.text}")
    user_id = user.id
    users_data[user_id] = {"name": update.message.text}
    await update.message.reply_text(
        f"Приятно познакомиться, {update.message.text}! Укажи, пожалуйста, свой пол.",
        reply_markup=gender_kb,
    )
    return ASK_GENDER


async def ask_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    gender = update.message.text
    users_data[user_id]["gender"] = gender
    logger.info(f"Пользователь {user_id} указал пол: {gender}")
    await update.message.reply_text(
        "Сколько тебе лет? Пожалуйста, введи число (например, 30).",
        reply_markup=ReplyKeyboardRemove()
    )
    return ASK_AGE


async def ask_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    try:
        age = int(update.message.text)
        users_data[user_id]["age"] = age
        logger.info(f"Пользователь {user_id} ввел возраст: {age}")
        await update.message.reply_text(
            "Каков твой текущий вес в килограммах? (например, 70)")
        return ASK_WEIGHT
    except ValueError:
        logger.warning(
            f"Пользователь {user_id} ввел некорректный возраст: {update.message.text}")
        await update.message.reply_text("Пожалуйста, введи только число для возраста.")
        return ASK_AGE


async def ask_height(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    try:
        weight = float(update.message.text.replace(',', '.'))
        users_data[user_id]["weight"] = weight
        logger.info(f"Пользователь {user_id} ввел вес: {weight}")
        await update.message.reply_text(
            "Каков твой рост в сантиметрах? (например, 175)")
        return ASK_HEIGHT
    except ValueError:
        logger.warning(
            f"Пользователь {user_id} ввел некорректный вес: {update.message.text}")
        await update.message.reply_text("Пожалуйста, введи число для веса.")
        return ASK_WEIGHT


async def ask_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    try:
        height = int(update.message.text)
        users_data[user_id]["height"] = height
        logger.info(f"Пользователь {user_id} ввел рост: {height}")
        await update.message.reply_text(
            "Оцени свою физическую активность по пятибалльной шкале:\n"
            "1 - минимальная (сидячий образ жизни)\n"
            "5 - очень высокая (ежедневные интенсивные тренировки)",
            reply_markup=activity_kb,
        )
        return ASK_ACTIVITY
    except ValueError:
        logger.warning(
            f"Пользователь {user_id} ввел некорректный рост: {update.message.text}")
        await update.message.reply_text("Пожалуйста, введи число для роста.")
        return ASK_HEIGHT


async def ask_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    try:
        activity = int(update.message.text)
        if activity < 1 or activity > 5:
            raise ValueError
        users_data[user_id]["activity"] = activity
        logger.info(f"Пользователь {user_id} указал активность: {activity}")
        await update.message.reply_text(
            "Какова твоя цель?\n"
            "Похудеть, удержать вес или набрать массу?",
            reply_markup=goal_kb,
        )
        return ASK_GOAL
    except ValueError:
        logger.warning(
            f"Пользователь {user_id} ввел некорректную активность: {update.message.text}")
        await update.message.reply_text(
            "Пожалуйста, выбери число от 1 до 5 на клавиатуре.")
        return ASK_ACTIVITY


async def show_calorie_corridor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    goal = update.message.text
    users_data[user_id]["goal"] = goal

    data = users_data[user_id]
    bmr = calculate_bmr(data["weight"], data["height"], data["age"], data["gender"])
    tdee = calculate_tdee(bmr, data["activity"])
    lower, upper = calculate_calorie_range(tdee, goal)

    users_data[user_id].update({
        "bmr": bmr,
        "tdee": tdee,
        "calorie_lower": round(lower),
        "calorie_upper": round(upper),
        "meals": [],
        "weights": [],
    })

    logger.info(f"Пользователь {user_id} получил коридор калорий: {round(lower)}-{round(upper)} ккал, цель: {goal}")

    await update.message.reply_text(
        f"Ваш коридор калорий на сегодня: {round(lower)} - {round(upper)} ккал.\n"
        "Теперь вы можете каждый день вносить свои приемы пищи. "
        "Напишите первую запись о приеме пищи (например: завтрак - 300 ккал)."
    )
    return RECORD_MEAL


async def record_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    text = update.message.text
    data = users_data[user_id]

    import re
    match = re.search(r'(\d+)', text)
    if not match:
        logger.warning(
            f"Пользователь {user_id} отправил некорректный прием пищи: '{text}'")
        await update.message.reply_text("Пожалуйста, укажи количество калорий в сообщении.")
        return RECORD_MEAL

    cals = int(match.group(1))
    now = datetime.now()
    data["meals"].append({"time": now, "calories": cals})

    logger.info(f"Пользователь {user_id} добавил прием пищи: {cals} ккал в {now.isoformat()}")

    await update.message.reply_text(
        f"Записано: {cals} ккал.\n"
        "Я напомню тебе о следующем приеме пищи через 2 часа."
    )

    try:
        context.job_queue.run_once(reminder_2h, 2 * 60 * 60, data=user_id, name=f"reminder_2h_{user_id}")
        context.job_queue.run_once(reminder_3h, 3 * 60 * 60, data=user_id, name=f"reminder_3h_{user_id}")
        context.job_queue.run_once(reminder_4h, 4 * 60 * 60, data=user_id, name=f"reminder_4h_{user_id}")
        logger.info(f"Планирование напоминаний для пользователя {user_id}")
    except Exception as e:
        logger.error(f"Ошибка при планировании напоминаний для пользователя {user_id}: {e}")

    return RECORD_MEAL


async def reminder_2h(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    try:
        await context.bot.send_message(chat_id=user_id, text="Позаботься о себе, не забудь покушать!")
        logger.info(f"Отправлено напоминание 2ч пользователю {user_id}")
    except Exception as e:
        logger.error(f"Ошибка отправки напоминания 2ч пользователю {user_id}: {e}")


async def reminder_3h(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="Если ты не внес данные о приеме пищи, пожалуйста, обязательно покушай. Иначе начнется выделяться гормон стресса, и похудение приостановится."
        )
        logger.info(f"Отправлено напоминание 3ч пользователю {user_id}")
    except Exception as e:
        logger.error(f"Ошибка отправки напоминания 3ч пользователю {user_id}: {e}")


async def reminder_4h(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    now = datetime.now()
    if now.hour >= 21:
        # После 21:00 не напоминаем
        logger.info(f"Напоминание 4ч не отправлено пользователю {user_id} из-за времени ({now.hour} ч.)")
        return
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="Критично важно покушать примерно сейчас!"
        )
        logger.info(f"Отправлено напоминание 4ч пользователю {user_id}")
    except Exception as e:
        logger.error(f"Ошибка отправки напоминания 4ч пользователю {user_id}: {e}")


async def evening_report(context: ContextTypes.DEFAULT_TYPE):
    chat_ids = list(users_data.keys())
    now = datetime.now()
    date_today = now.date()

    for user_id in chat_ids:
        data = users_data[user_id]
        meals = data.get("meals", [])
        calories_today = sum(m['calories'] for m in meals if m['time'].date() == date_today)
        meals_count = sum(1 for m in meals if m['time'].date() == date_today)

        if meals_count == 0:
            continue

        text = (
            f"Сегодня вы съели {calories_today} ккал, "
            f"питание было {meals_count} раз.\n"
            "Старайтесь соблюдать коридор калорийности!\n"
        )
        try:
            await context.bot.send_message(chat_id=user_id, text=text)
            logger.info(f"Вечерний отчет отправлен пользователю {user_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки вечернего отчета пользователю {user_id}: {e}")


async def morning_weight_request(context: ContextTypes.DEFAULT_TYPE):
    for user_id in users_data.keys():
        try:
            await context.bot.send_message(chat_id=user_id, text="Доброе утро! Пожалуйста, сообщите свой текущий вес.")
            logger.info(f"Запрос утреннего веса отправлен пользователю {user_id}")
        except Exception as e:
            logger.error(f"Ошибка при запросе утреннего веса пользователю {user_id}: {e}")


async def handle_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    try:
        weight = float(update.message.text.replace(',', '.'))
        if user_id in users_data:
            users_data[user_id].setdefault("weights", []).append({"date": datetime.now().date(), "weight": weight})
            await update.message.reply_text("Спасибо, вес записан.")
            logger.info(f"Пользователь {user_id} ввел вес: {weight}")
        else:
            await update.message.reply_text("Пожалуйста, начните с команды /start")
            logger.warning(f"Пользователь {user_id} попытался ввести вес без старта диалога")
    except ValueError:
        await update.message.reply_text("Пожалуйста, введи число для веса (например, 70.5)")
        logger.warning(f"Пользователь {user_id} ввел некорректный вес: {update.message.text}")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    logger.info(f"Пользователь {user.id} прервал диалог командой /cancel")
    await update.message.reply_text("Диалог завершен. Если хотите начать сначала, нажмите /start", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def main():
    logger.info("Запуск бота...")
    application = ApplicationBuilder().token("7272229081:AAHo8LBIn-oB9WnJ8YDkRf3R5zV2B-5qly8").build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_gender)],
            ASK_GENDER: [MessageHandler(filters.Regex("^(Мужской|Женский)$"), ask_age)],
            ASK_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_weight)],
            ASK_WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_height)],
            ASK_HEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_activity)],
            ASK_ACTIVITY: [MessageHandler(filters.Regex("^[1-5]{1}$"), ask_goal)],
            ASK_GOAL: [MessageHandler(filters.Regex("^(Похудеть|Удержать вес|Набрать массу)$"), show_calorie_corridor)],
            RECORD_MEAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, record_meal)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    application.add_handler(conv_handler)
    # Обработка веса вне диалога
    application.add_handler(MessageHandler(filters.Regex(r"^\d+(\.\d+)?$"), handle_weight))

    # Планировщик: вечером в 23:00 отчет
    application.job_queue.run_daily(evening_report, time=time(hour=23, minute=0, second=0))
    # Утром в 8:00 сбор веса
    application.job_queue.run_daily(morning_weight_request, time=time(hour=8, minute=0, second=0))

    application.run_polling()
    logger.info("Бот остановлен")


if __name__ == "__main__":
    main()
