import re
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardRemove, Contact
from telegram.ext import ContextTypes
from keyboards import contact_kb, hour_kb, gender_kb, activity_kb, goal_kb
from states import BotState
from texts import HELLO, ASK_LOCAL_TIME
from services.storage import users_data
from domain.tz import parse_tz
from services.scheduler import schedule_user_jobs
from db import save_user_data, load_user_data

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    data = load_user_data(user.id)
    if data:
        users_data[user.id] = data
    else:
        users_data.setdefault(user.id, {})
    await update.message.reply_text(HELLO, reply_markup=contact_kb)
    return BotState.ASK_CONTACT

async def handle_contact_or_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    d = users_data.setdefault(user.id, {})
    if update.message and update.message.text and update.message.text.strip().lower() == "пропустить":
        pass
    elif update.message and isinstance(update.message.contact, Contact):
        d["phone"] = update.message.contact.phone_number
    # новый вопрос вместо ASK_LOCAL_TIME
    from texts import ASK_LOCAL_TIME
    await update.message.reply_text(ASK_LOCAL_TIME, reply_markup=ReplyKeyboardRemove())
    return BotState.ASK_LOCAL_TIME


async def handle_local_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь ввёл локальное время (HH:MM), вычисляем смещение относительно сервера."""
    user = update.effective_user
    text = (update.message.text or "").strip()

    try:
        hh, mm = map(int, text.split(":"))
        now_server = datetime.now().replace(second=0, microsecond=0)
        user_time = now_server.replace(hour=hh, minute=mm)

        # разница в минутах (может быть отрицательной)
        offset_minutes = int((user_time - now_server).total_seconds() / 60)

        users_data.setdefault(user.id, {})["tz_offset"] = offset_minutes

        # сохраним в БД (если добавлено поле tz_offset)
        save_user_data(user.id, users_data[user.id])

        await update.message.reply_text(
            "Принято! Во сколько удобно присылать утренний запрос веса? Выбери час:",
            reply_markup=hour_kb(6, 11)
        )
        return BotState.ASK_MORNING_HOUR

    except Exception:
        await update.message.reply_text("Пожалуйста, укажи время в формате HH:MM (например, 09:30).")
        return BotState.ASK_LOCAL_TIME

async def handle_morning_hour(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    m = re.fullmatch(r'(\d{2}):00', (update.message.text or "").strip())
    if not m:
        await update.message.reply_text("Выбери из кнопок, пожалуйста (формат HH:00).")
        return BotState.ASK_MORNING_HOUR
    users_data.setdefault(user.id, {})["morning_hour"] = int(m.group(1))
    await update.message.reply_text("А во сколько присылать вечерний итог дня?", reply_markup=hour_kb(19, 23))
    return BotState.ASK_EVENING_HOUR

async def handle_evening_hour(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    m = re.fullmatch(r'(\d{2}):00', (update.message.text or "").strip())
    if not m:
        await update.message.reply_text("Выбери из кнопок, пожалуйста (формат HH:00).")
        return BotState.ASK_EVENING_HOUR
    users_data.setdefault(user.id, {})["evening_hour"] = int(m.group(1))
    
    # Добавлена проверка перед вызовом schedule_user_jobs
    if context.application and context.application.job_queue:
        schedule_user_jobs(context.application, user.id)
    else:
        # Логирование для отладки
        print(f"Warning: Cannot schedule jobs for user {user.id} - Application or JobQueue is None")
        print(f"Application: {context.application}")
        print(f"JobQueue: {context.application.job_queue if context.application else None}")
    
    await update.message.reply_text("Отлично! Теперь давай познакомимся. Как тебя зовут?", reply_markup=ReplyKeyboardRemove())
    return BotState.ASK_NAME

async def ask_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    users_data[user.id] = {"name": update.message.text}
    await update.message.reply_text(f"Приятно познакомиться, {update.message.text}! Укажи, пожалуйста, свой пол.", reply_markup=gender_kb)
    return BotState.ASK_GENDER

async def ask_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    users_data[user.id]["gender"] = update.message.text
    await update.message.reply_text("Сколько тебе лет? Пожалуйста, введи число (например, 30).")
    return BotState.ASK_AGE

async def ask_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    try:
        age = int(update.message.text)
        users_data[user.id]["age"] = age
        await update.message.reply_text("Каков твой текущий вес в килограммах? (например, 70)")
        return BotState.ASK_WEIGHT
    except ValueError:
        await update.message.reply_text("Пожалуйста, введи только число для возраста.")
        return BotState.ASK_AGE

async def ask_height(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    try:
        weight = float(update.message.text.replace(",", "."))
        users_data[user.id]["weight"] = weight
        await update.message.reply_text("Каков твой рост в сантиметрах? (например, 175)")
        return BotState.ASK_HEIGHT
    except ValueError:
        await update.message.reply_text("Пожалуйста, введи число для веса.")
        return BotState.ASK_WEIGHT

async def ask_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    try:
        height = int(update.message.text)
        users_data[user.id]["height"] = height
        await update.message.reply_text(
            "Оцени свою физическую активность по пятибалльной шкале:\n"
            "1 - минимальная (сидячий образ жизни)\n"
            "5 - очень высокая (ежедневные интенсивные тренировки)",
            reply_markup=activity_kb,
        )
        return BotState.ASK_ACTIVITY
    except ValueError:
        await update.message.reply_text("Пожалуйста, введи число для роста.")
        return BotState.ASK_HEIGHT

async def ask_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    try:
        activity = int(update.message.text)
        users_data[user.id]["activity"] = activity
        await update.message.reply_text("Какова твоя цель?\nПохудеть, удержать вес или набрать массу?", reply_markup=goal_kb)
        return BotState.ASK_GOAL
    except ValueError:
        await update.message.reply_text("Пожалуйста, выбери число от 1 до 5 на клавиатуре.")
        return BotState.ASK_ACTIVITY

from domain.calories import calculate_bmr, calculate_tdee, calculate_calorie_range

async def show_calorie_corridor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    goal = update.message.text
    users_data[user.id]["goal"] = goal
    d = users_data[user.id]
    bmr = calculate_bmr(d["weight"], d["height"], d["age"], d["gender"])
    tdee = calculate_tdee(bmr, d["activity"])
    lower, upper = calculate_calorie_range(tdee, goal)
    users_data[user.id].update({
        "bmr": bmr, "tdee": tdee,
        "calorie_lower": round(lower),
        "calorie_upper": round(upper),
        "meals": [], "weights": [],
    })
    await update.message.reply_text(
        f"Ваш коридор калорий на сегодня: {round(lower)} - {round(upper)} ккал.\n"
        "Теперь можете вносить приёмы пищи в свободной форме — например: «два варёных яйца и яблоко».\n"
        "Я сам посчитаю КБЖУ через ChatGPT и поставлю напоминания."
    )
    save_user_data(user.id, users_data[user.id])
    return BotState.MONITORING
