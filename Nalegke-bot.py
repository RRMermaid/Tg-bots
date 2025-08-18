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

# ==== OpenAI ====
# Поддержка нового клиента (OpenAI v1+) и старого (openai==0.x)
OPENAI_AVAILABLE = False
MODEL_ID = os.getenv("OPENAI_MODEL_ID", "gpt-4o-mini")

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    # Попытка нового клиента
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    OPENAI_AVAILABLE = True
except Exception:
    try:
        # Попытка старого клиента
        import openai
        openai.api_key = os.getenv("OPENAI_API_KEY")
        client = None
        OPENAI_AVAILABLE = bool(openai.api_key)
    except Exception:
        OPENAI_AVAILABLE = False
        client = None

# ==== Логирование ====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    handlers=[logging.FileHandler("bot.log", encoding='utf-8'), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# ==== Состояния диалога ====
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

# ==== Клавиатуры ====
gender_kb = ReplyKeyboardMarkup([["Мужской", "Женский"]], one_time_keyboard=True, resize_keyboard=True)
activity_kb = ReplyKeyboardMarkup([["1", "2", "3", "4", "5"]], one_time_keyboard=True, resize_keyboard=True)
goal_kb = ReplyKeyboardMarkup([["Похудеть", "Удержать вес", "Набрать массу"]], one_time_keyboard=True, resize_keyboard=True)

# ==== Формулы ====
def calculate_bmr(weight, height, age, gender):
    if gender == "Мужской":
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161
    return bmr

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

# ==== Диалог ====
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
        weight = float(update.message.text.replace(',', '.'))
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

    users_data[user.id].update({
        "bmr": bmr,
        "tdee": tdee,
        "calorie_lower": round(lower),
        "calorie_upper": round(upper),
        "meals": [],
        "weights": [],
    })

    await update.message.reply_text(
        f"Ваш коридор калорий на сегодня: {round(lower)} - {round(upper)} ккал.\n"
        "Теперь можете вносить приёмы пищи в свободной форме — например: «два варёных яйца и яблоко».\n"
        "Я сам посчитаю КБЖУ и поставлю подходящее напоминание."
    )
    return RECORD_MEAL

# ==== Оценка КБЖУ из текста ====

# Фолбэк без OpenAI: очень грубые оценки (чтобы не ломалось, если API-ключа нет)
RUS_NUM = {"пол": 0.5, "полтора": 1.5, "один": 1, "одно": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5}
def _word_qty(text: str) -> float:
    for w, n in RUS_NUM.items():
        if re.search(rf"\b{w}\b", text):
            return n
    m = re.search(r"(\d+(?:[.,]\d+)?)", text)
    return float(m.group(1).replace(",", ".")) if m else 1.0

def offline_estimate(text: str) -> dict:
    t = text.lower()
    # мини-словарь примеров
    if "яйц" in t:
        q = _word_qty(t)
        # 1 яйцо ~ 70 ккал, 6г белка, 5г жира, 0.5г углеводов
        return {
            "calories": int(round(70 * q)),
            "protein_g": round(6 * q, 1),
            "fat_g": round(5 * q, 1),
            "carbs_g": round(0.5 * q, 1),
            "meal_kind": "plate",
            "next_meal_hours": 4
        }
    if "суп" in t:
        # Порция супа 300 мл ~ 150 ккал
        return {"calories": 150, "protein_g": 6, "fat_g": 6, "carbs_g": 16, "meal_kind": "soup", "next_meal_hours": 2}
    if "яблок" in t:
        q = _word_qty(t)
        return {"calories": int(round(52 * q * 100/182)), "protein_g": 0.3*q, "fat_g": 0.2*q, "carbs_g": 14*q, "meal_kind": "snack", "next_meal_hours": 3}
    if "курин" in t or "грудк" in t:
        # 150 г кур. грудки ~ 165 ккал
        return {"calories": 165, "protein_g": 31, "fat_g": 3.6, "carbs_g": 0, "meal_kind": "plate", "next_meal_hours": 4}
    # Если не узнал — вернём None
    return {}

OPENAI_SYSTEM_PROMPT = (
    "Ты диетолог. Разбери русский текст с приёмом пищи и оцени КБЖУ. "
    "Ответ строго в формате JSON без комментариев и лишнего текста, поля:\n"
    "{"
    "\"calories\": <целое число>, "
    "\"protein_g\": <число>, "
    "\"fat_g\": <число>, "
    "\"carbs_g\": <число>, "
    "\"meal_kind\": \"plate|soup|snack|dessert|drink\", "
    "\"next_meal_hours\": <целое 2 или 3 или 4>, "
    "\"explanation\": \"коротко, как считал\""
    "}\n"
    "Правила: полноценная тарелка (гарнир+белок+овощи) => meal_kind=\"plate\" и next_meal_hours=4; суп => meal_kind=\"soup\" и 2; перекус => 3. "
    "Если есть десерт отдельно, meal_kind=\"dessert\" и 3. КБЖУ оценивай реалистично по типовым порциям."
)

async def estimate_meal_nutrition(text: str) -> dict:
    """Возвращает dict с ключами: calories, protein_g, fat_g, carbs_g, meal_kind, next_meal_hours, explanation"""
    # 1) OpenAI, если доступен
    if OPENAI_AVAILABLE:
        async def _call_new():
            # Новый клиент
            resp = await asyncio.to_thread(
                client.chat.completions.create,
                model=MODEL_ID,
                messages=[{"role": "system", "content": OPENAI_SYSTEM_PROMPT},
                          {"role": "user", "content": text}],
                temperature=0.2,
                max_tokens=200,
            )
            return resp.choices[0].message.content

        async def _call_old():
            # Старый клиент
            resp = await asyncio.to_thread(
                openai.ChatCompletion.create,
                model=MODEL_ID,
                messages=[{"role": "system", "content": OPENAI_SYSTEM_PROMPT},
                          {"role": "user", "content": text}],
                temperature=0.2,
                max_tokens=200,
            )
            return resp.choices[0].message["content"]

        try:
            content = await (_call_new() if client else _call_old())
            # Достаём JSON даже если модель добавила лишний текст
            json_match = re.search(r"\{.*\}", content, flags=re.S)
            if not json_match:
                raise ValueError("Не найден JSON в ответе модели")
            data = json.loads(json_match.group(0))
            # Мини-валидация
            if "calories" in data and "meal_kind" in data:
                return data
        except Exception as e:
            logger.warning(f"OpenAI недоступен/ошибка парсинга: {e}")

    # 2) Фолбэк без OpenAI
    est = offline_estimate(text)
    if est:
        est.setdefault("explanation", "Оценка по встроенному справочнику.")
        return est
    # 3) Совсем не удалось
    return {}

# ==== Приёмы пищи и напоминания ====
def _schedule_next_reminder(context: ContextTypes.DEFAULT_TYPE, user_id: int, hours: int):
    now = datetime.now()
    target = now + timedelta(hours=hours)
    # не позже 21:00
    cutoff = now.replace(hour=21, minute=0, second=0, microsecond=0)
    if target > cutoff:
        # если уже поздно — не напоминаем
        return None
    # ставим мягкое имя задачи, чтобы не плодить
    name = f"eat_reminder_{user_id}_{int(target.timestamp())}"
    context.job_queue.run_once(reminder_generic, when=(target - now).total_seconds(), data=user_id, name=name)
    return target

async def record_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    text = update.message.text.strip()
    users_data.setdefault(user_id, {}).setdefault("meals", [])

    # 1) Сначала всегда пытаемся оценить КБЖУ через ИИ/фолбэк
    info = await estimate_meal_nutrition(text)

    # 2) Если ИИ не смог — принимаем явные калории ТОЛЬКО с единицами "ккал"/"kcal"
    explicit_kcal = False
    if not info or "calories" not in info:
        kcal_match = re.search(r"\b(\d{2,5})\s*(ккал|kcal)\b", text.lower())
        if kcal_match:
            info = {
                "calories": int(kcal_match.group(1)),
                "protein_g": None, "fat_g": None, "carbs_g": None,
                "meal_kind": "snack", "next_meal_hours": 3,
                "explanation": "Пользователь указал калории явно."
            }
            explicit_kcal = True

    # 3) Если всё ещё не вышло — просим переформулировать
    if not info or "calories" not in info:
        await update.message.reply_text(
            "Пока не могу понять блюдо. Напиши проще (например: «2 варёных яйца и яблоко»). "
            "Либо укажи калории явно — «200 ккал»."
        )
        return RECORD_MEAL

    now = datetime.now()
    entry = {
        "time": now,
        "text": text,
        "calories": int(info.get("calories", 0)),
        "protein_g": info.get("protein_g"),
        "fat_g": info.get("fat_g"),
        "carbs_g": info.get("carbs_g"),
        "meal_kind": info.get("meal_kind"),
        "source": "user" if explicit_kcal else "ai",
    }
    users_data[user_id]["meals"].append(entry)

    # 4) Напоминание по типу приёма
    next_hours = int(info.get("next_meal_hours") or (2 if entry["meal_kind"] == "soup" else 4))
    target = _schedule_next_reminder(context, user_id, next_hours)

    # 5) Ответ пользователю
    kbju_str = []
    if entry["protein_g"] is not None: kbju_str.append(f"Б: {entry['protein_g']}")
    if entry["fat_g"] is not None:     kbju_str.append(f"Ж: {entry['fat_g']}")
    if entry["carbs_g"] is not None:   kbju_str.append(f"У: {entry['carbs_g']}")
    kbju_line = (" (" + ", ".join(kbju_str) + " г)") if kbju_str else ""

    if target:
        reminder_line = f"\nСледующее напоминание — через ~{next_hours} ч (в {target.strftime('%H:%M')})."
    else:
        reminder_line = "\nПоздно для напоминания — после 21:00 не беспокою."

    explanation = info.get("explanation")
    explain_line = f"\nПодсчёт: {explanation}" if explanation else ""

    await update.message.reply_text(
        f"Записано: {entry['calories']} ккал{kbju_line}.{reminder_line}{explain_line}"
    )
    return RECORD_MEAL

async def reminder_generic(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    now = datetime.now()
    if now.hour >= 21:
        return
    try:
        await context.bot.send_message(chat_id=user_id, text="Пора подкрепиться 🍽️")
    except Exception as e:
        logger.error(f"Ошибка отправки напоминания: {e}")

# ==== Ввод веса ====
async def handle_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    try:
        weight = float(update.message.text.replace(',', '.'))
        users_data.setdefault(user.id, {}).setdefault("weights", []).append({"date": datetime.now().date(), "weight": weight})
        await update.message.reply_text(f"Спасибо, вес {weight} кг записан.")
        logger.info(f"Пользователь {user.id} ввел вес: {weight}")
    except ValueError:
        await update.message.reply_text("Пожалуйста, введи корректное число для веса (например, 70.5).")
        logger.warning(f"Некорректный вес от {user.id}: {update.message.text}")

# ==== Вечерний отчёт и утренний запрос ====
async def evening_report(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    date_today = now.date()
    for user_id, data in users_data.items():
        meals = [m for m in data.get("meals", []) if m["time"].date() == date_today]
        if not meals:
            continue
        calories_today = sum(m['calories'] for m in meals)
        meals_count = len(meals)
        # Сумма КБЖУ
        prot = sum((m.get("protein_g") or 0) for m in meals)
        fat = sum((m.get("fat_g") or 0) for m in meals)
        carb = sum((m.get("carbs_g") or 0) for m in meals)

        text = (
            f"Итог дня:\n"
            f"• Калории: {calories_today} ккал\n"
            f"• Приёмов пищи: {meals_count}\n"
            f"• КБЖУ: Б {round(prot,1)} г / Ж {round(fat,1)} г / У {round(carb,1)} г\n"
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

# ==== Cancel ====
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    logger.info(f"Пользователь {user.id} прервал диалог командой /cancel")
    await update.message.reply_text("Диалог завершен. Если хотите начать сначала, нажмите /start", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ==== Error handler (чтобы не сыпались стектрейсы в лог) ====
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Ошибка во время обработки апдейта", exc_info=context.error)

# ==== main ====
def main():
    # ⚠️ Лучше хранить токен в .env: TELEGRAM_BOT_TOKEN=...
    token = os.getenv("TELEGRAM_BOT_TOKEN", "7272229081:AAHo8LBIn-oB9WnJ8YDkRf3R5zV2B-5qly8")
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
    # Ввод веса в любой момент просто числом
    application.add_handler(MessageHandler(filters.Regex(r"^\d+(\.\d+)?$"), handle_weight))
    application.add_error_handler(on_error)

    # Планировщик задач
    application.job_queue.run_daily(evening_report, time=time(hour=23, minute=0, second=0))
    application.job_queue.run_daily(morning_weight_request, time=time(hour=8, minute=0, second=0))

    application.run_polling()

if __name__ == "__main__":
    main()
