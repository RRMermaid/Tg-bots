import logging
import os
import re
import json
import asyncio
from datetime import datetime, time, timedelta

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)

# ==== .env ====
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ==== OpenAI ====
OPENAI_AVAILABLE = False
MODEL_ID = os.getenv("OPENAI_MODEL_ID", "gpt-4o-mini")
try:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    OPENAI_AVAILABLE = True
except Exception:
    try:
        import openai
        openai.api_key = os.getenv("OPENAI_API_KEY")
        client = None
        OPENAI_AVAILABLE = bool(openai.api_key)
    except Exception:
        OPENAI_AVAILABLE = False
        client = None

# ==== Logging ====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[logging.FileHandler("bot.log", encoding="utf-8"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# ==== Dialogue states ====
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
) = range(9)


users_data = {}


# ==== Keyboards ====
gender_kb = ReplyKeyboardMarkup([["Мужской", "Женский"]], one_time_keyboard=True, resize_keyboard=True)
activity_kb = ReplyKeyboardMarkup([["1", "2", "3", "4", "5"]], one_time_keyboard=True, resize_keyboard=True)
goal_kb = ReplyKeyboardMarkup([["Похудеть", "Удержать вес", "Набрать массу"]], one_time_keyboard=True, resize_keyboard=True)


# ==== Formulas ====
def calculate_bmr(weight, height, age, gender):
    if gender == "Мужской":
        return 10 * weight + 6.25 * height - 5 * age + 5
    else:
        return 10 * weight + 6.25 * height - 5 * age - 161


def calculate_tdee(bmr, activity_level):
    factors = {1: 1.2, 2: 1.375, 3: 1.55, 4: 1.725, 5: 1.9}
    return bmr * factors.get(activity_level, 1.2)


def calculate_calorie_range(tdee, goal):
    if goal == "Похудеть":
        upper = tdee
        lower = max(upper - upper * 0.2, upper - 500)
        return lower, upper
    elif goal == "Удержать вес":
        return tdee - 100, tdee + 100
    else:  # Набрать массу
        return tdee, tdee + 300


# ==== System prompt for OpenAI ====
OPENAI_SYSTEM_PROMPT = (
    "Ты диетолог. Разбери русский текст с приёмом пищи и оцени КБЖУ. "
    "Ответ строго в формате JSON без комментариев и лишнего текста, поля:\n"
    "{"
    '"calories": <целое число>, '
    '"protein_g": <число>, '
    '"fat_g": <число>, '
    '"carbs_g": <число>, '
    '"meal_kind": "plate|soup|snack|dessert|drink", '
    '"next_meal_hours": <целое 2 или 3 или 4>, '
    '"explanation": "коротко, как считал"'
    "}\n"
    "Правила: полноценная тарелка (гарнир+белок+овощи) => meal_kind=\"plate\" и next_meal_hours=4; "
    "суп => meal_kind=\"soup\" и 2; перекус => 3. Если есть десерт отдельно, meal_kind=\"dessert\" и 3."
)


# ==== OpenAI call ====
async def estimate_meal_nutrition(text: str) -> dict:
    if not OPENAI_AVAILABLE:
        return {}

    async def _call_new():
        resp = await asyncio.to_thread(
            client.chat.completions.create,
            model=MODEL_ID,
            messages=[
                {"role": "system", "content": OPENAI_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.2,
            max_tokens=200,
        )
        return resp.choices[0].message.content

    async def _call_old():
        resp = await asyncio.to_thread(
            openai.ChatCompletion.create,
            model=MODEL_ID,
            messages=[
                {"role": "system", "content": OPENAI_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.2,
            max_tokens=200,
        )
        return resp.choices[0].message["content"]

    try:
        content = await (_call_new() if client else _call_old())
        json_match = re.search(r"\{.*\}", content, flags=re.S)
        if not json_match:
            raise ValueError("Не найден JSON в ответе модели")
        data = json.loads(json_match.group(0))
        if "calories" in data and "meal_kind" in data:
            return data
    except Exception as e:
        logger.warning(f"OpenAI недоступен/ошибка парсинга: {e}")
    return {}


# ==== Handlers ====
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
    users_data[user.id] = {"name": update.message.text}
    await update.message.reply_text(
        f"Приятно познакомиться, {update.message.text}! Укажи, пожалуйста, свой пол.",
        reply_markup=gender_kb,
    )
    return ASK_GENDER


async def ask_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    users_data[user.id]["gender"] = update.message.text
    await update.message.reply_text("Сколько тебе лет? Пожалуйста, введи число (например, 30).")
    return ASK_AGE


async def ask_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    try:
        age = int(update.message.text)
        users_data[user.id]["age"] = age
        await update.message.reply_text("Каков твой текущий вес в килограммах? (например, 70)")
        return ASK_WEIGHT
    except ValueError:
        await update.message.reply_text("Пожалуйста, введи только число для возраста.")
        return ASK_AGE


async def ask_height(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    try:
        weight = float(update.message.text.replace(",", "."))
        users_data[user.id]["weight"] = weight
        await update.message.reply_text("Каков твой рост в сантиметрах? (например, 175)")
        return ASK_HEIGHT
    except ValueError:
        await update.message.reply_text("Пожалуйста, введи число для веса.")
        return ASK_WEIGHT


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
        return ASK_ACTIVITY
    except ValueError:
        await update.message.reply_text("Пожалуйста, введи число для роста.")
        return ASK_HEIGHT


async def ask_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    try:
        activity = int(update.message.text)
        users_data[user.id]["activity"] = activity
        await update.message.reply_text(
            "Какова твоя цель?\n"
            "Похудеть, удержать вес или набрать массу?",
            reply_markup=goal_kb,
        )
        return ASK_GOAL
    except ValueError:
        await update.message.reply_text("Пожалуйста, выбери число от 1 до 5 на клавиатуре.")
        return ASK_ACTIVITY


async def show_calorie_corridor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    goal = update.message.text
    users_data[user.id]["goal"] = goal
    data = users_data[user.id]

    bmr = calculate_bmr(data["weight"], data["height"], data["age"], data["gender"])
    tdee = calculate_tdee(bmr, data["activity"])
    lower, upper = calculate_calorie_range(tdee, goal)

    users_data[user.id].update(
        {
            "bmr": bmr,
            "tdee": tdee,
            "calorie_lower": round(lower),
            "calorie_upper": round(upper),
            "meals": [],
            "weights": [],
        }
    )

    await update.message.reply_text(
        f"Ваш коридор калорий на сегодня: {round(lower)} - {round(upper)} ккал.\n"
        "Теперь можете вносить приёмы пищи в свободной форме — например: «два варёных яйца и яблоко».\n"
        "Я сам посчитаю КБЖУ через ChatGPT и поставлю подходящее напоминание."
    )
    return RECORD_MEAL


async def record_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    text = update.message.text.strip()
    data = users_data.get(user_id)

    if data is None:
        await update.message.reply_text("Пожалуйста, начните с команды /start")
        return RECORD_MEAL

    match = re.search(r"(\d+)", text)

    if match:
        cals = int(match.group(1))
        now = datetime.now()
        data["meals"].append({"time": now, "calories": cals, "raw": text})
        logger.info(f"[manual] Пользователь {user_id}: {cals} ккал в {now.isoformat()} ({text})")
        await update.message.reply_text(f"Записано: {cals} ккал.\nЯ напомню о следующем приёме пищи через 2 часа.")
    else:
        await update.message.reply_text("Считаю калории через ChatGPT…")
        nutri = await estimate_meal_nutrition(text)
        if not nutri or nutri.get("calories") is None:
            await update.message.reply_text("Не удалось оценить блюдо через ChatGPT. Можешь прислать калории числом?")
            logger.warning(f"Оценка ChatGPT не удалась: '{text}' от {user_id}")
            return RECORD_MEAL

        cals = nutri["calories"]
        now = datetime.now()
        data["meals"].append(
            {
                "time": now,
                "calories": cals,
                "protein_g": nutri.get("protein_g"),
                "fat_g": nutri.get("fat_g"),
                "carbs_g": nutri.get("carbs_g"),
                "raw": text,
                "auto": True,
            }
        )
        logger.info(f"[ChatGPT] Пользователь {user_id}: {cals} ккал, БЖУ ({nutri}) из '{text}'")
        p = nutri.get("protein_g")
        f = nutri.get("fat_g")
        ch = nutri.get("carbs_g")
        macros = f"\nБ: {p or '-'} г • Ж: {f or '-'} г • У: {ch or '-'} г"
        await update.message.reply_text(f"Записано: ~{cals} ккал за «{text}».{macros}\nЯ напомню о следующем приёме пищи через 2 часа.")

    try:
        context.job_queue.run_once(reminder_2h, 2 * 60 * 60, data=user_id, name=f"reminder_2h_{user_id}")
        context.job_queue.run_once(reminder_3h, 3 * 60 * 60, data=user_id, name=f"reminder_3h_{user_id}")
        context.job_queue.run_once(reminder_4h, 4 * 60 * 60, data=user_id, name=f"reminder_4h_{user_id}")
        logger.info(f"Планирование напоминаний для пользователя {user_id}")
    except Exception as e:
        logger.error(f"Ошибка при планировании напоминаний для пользователя {user_id}: {e}")

    return RECORD_MEAL


# ==== Reminder handlers ====
async def reminder_generic(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    now = datetime.now()
    if now.hour >= 21:
        return
    try:
        await context.bot.send_message(chat_id=user_id, text="Пора подкрепиться 🍽️")
    except Exception as e:
        logger.error(f"Ошибка отправки напоминания: {e}")


async def reminder_2h(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    try:
        await context.bot.send_message(chat_id=user_id, text="Позаботься о себе, не забудь покушать!")
    except Exception as e:
        logger.error(f"Ошибка отправки напоминания 2ч пользователю {user_id}: {e}")


async def reminder_3h(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "Если ты не внёс данные о приёме пищи, пожалуйста, обязательно покушай. "
                "Иначе начнёт выделяться гормон стресса, и похудение приостановится."
            ),
        )
    except Exception as e:
        logger.error(f"Ошибка отправки напоминания 3ч пользователю {user_id}: {e}")


async def reminder_4h(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    now = datetime.now()
    if now.hour >= 21:
        return
    try:
        await context.bot.send_message(chat_id=user_id, text="Критично важно покушать примерно сейчас!")
    except Exception as e:
        logger.error(f"Ошибка отправки напоминания 4ч пользователю {user_id}: {e}")


# ==== Weight input handler ====
async def handle_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    try:
        weight = float(update.message.text.replace(",", "."))
        users_data.setdefault(user.id, {}).setdefault("weights", []).append({"date": datetime.now().date(), "weight": weight})
        await update.message.reply_text(f"Спасибо, вес {weight} кг записан.")
        logger.info(f"Пользователь {user.id} ввел вес: {weight}")
    except ValueError:
        await update.message.reply_text("Пожалуйста, введи корректное число для веса (например, 70.5).")
        logger.warning(f"Некорректный вес от {user.id}: {update.message.text}")


# ==== Evening report and morning request ====
async def evening_report(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    date_today = now.date()
    for user_id, data in users_data.items():
        meals = [m for m in data.get("meals", []) if m["time"].date() == date_today]
        if not meals:
            continue
        calories_today = sum(m["calories"] for m in meals)
        meals_count = len(meals)
        prot = sum((m.get("protein_g") if m.get("protein_g") is not None else 0) for m in meals)
        fat = sum((m.get("fat_g") if m.get("fat_g") is not None else 0) for m in meals)
        carb = sum((m.get("carbs_g") if m.get("carbs_g") is not None else 0) for m in meals)

        text = (
            "Итог дня:\n"
            f"• Калории: {calories_today} ккал\n"
            f"• Приёмов пищи: {meals_count}\n"
            f"• КБЖУ: Б {round(prot, 1)} г / Ж {round(fat, 1)} г / У {round(carb, 1)} г\n"
            "Совет: старайтесь держать белок в норме и собирать полноценную тарелку (гарнир+белок+овощи). "
            "После супа — перекус через ~2 часа; после полноценного блюда — выдерживайте до ~4 часов."
        )
        try:
            await context.bot.send_message(chat_id=user_id, text=text)
        except Exception as e:
            logger.error(f"Ошибка вечернего отчёта {user_id}: {e}")


async def morning_weight_request(context: ContextTypes.DEFAULT_TYPE):
    for user_id in users_data.keys():
        try:
            await context.bot.send_message(chat_id=user_id, text="Доброе утро! Пожалуйста, сообщите свой текущий вес.")
        except Exception as e:
            logger.error(f"Ошибка при запросе утреннего веса: {e}")


# ==== Cancel handler ====
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    logger.info(f"Пользователь {user.id} прервал диалог командой /cancel")
    await update.message.reply_text("Диалог завершен. Если хотите начать сначала, нажмите /start", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ==== Error handler ====
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Ошибка во время обработки апдейта", exc_info=context.error)


# ==== Main ====
def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")
    application = ApplicationBuilder().token(token).build()

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
    application.add_handler(MessageHandler(filters.Regex(r"^\d+(\.\d+)?$"), handle_weight))
    application.add_error_handler(on_error)

    application.job_queue.run_daily(evening_report, time=time(hour=23, minute=0, second=0))
    application.job_queue.run_daily(morning_weight_request, time=time(hour=8, minute=0, second=0))

    application.run_polling()


if __name__ == "__main__":
    main()
