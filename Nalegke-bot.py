import psycopg2

def get_connection():
    DATABASE_URL = os.getenv("DATABASE_URL")  # строка подключения к базе
    return psycopg2.connect(DATABASE_URL)

# ==== Standard library ====
import asyncio
import json
import logging
import os
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from db import create_tables, save_user_data, load_user_data, save_weight, save_meal, analyze_user_day

# ==== Third-party ====
import httpx
from openai import OpenAI
from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, Contact
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ConversationHandler, ContextTypes,
    CallbackQueryHandler
)

# ==== Local/project ====
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# --- Дружелюбная проверка наличия ключей ---
if not os.getenv("OPENAI_API_KEY"):
    print("⚠️ OPENAI_API_KEY не найден в .env")
if not os.getenv("TELEGRAM_BOT_TOKEN"):
    print("⚠️ TELEGRAM_BOT_TOKEN не найден в .env")

# ==== OpenAI (>=1.0.0) ====

OPENAI_AVAILABLE = False
MODEL_ID = os.getenv("OPENAI_MODEL_ID")

try:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    OPENAI_AVAILABLE = True
except Exception as e:
    client = None
    OPENAI_AVAILABLE = False
    logging.error(f"Ошибка инициализации OpenAI: {e}")

# ==== Logging ====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[logging.FileHandler("bot.log", encoding="utf-8"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# ==== Dialogue states ====
(
    ASK_CONTACT,
    ASK_TZ,
    ASK_MORNING_HOUR,
    ASK_EVENING_HOUR,
    ASK_NAME,
    ASK_GENDER,
    ASK_AGE,
    ASK_WEIGHT,
    ASK_HEIGHT,
    ASK_ACTIVITY,
    ASK_GOAL,
    RECORD_MEAL,
    MONITORING,
) = range(13)

users_data = {}

# ==== Keyboards ====
gender_kb = ReplyKeyboardMarkup([["Мужской", "Женский"]], one_time_keyboard=True, resize_keyboard=True)
activity_kb = ReplyKeyboardMarkup([["1", "2", "3", "4", "5"]], one_time_keyboard=True, resize_keyboard=True)
goal_kb = ReplyKeyboardMarkup([["Похудеть", "Удержать вес", "Набрать массу"]], one_time_keyboard=True, resize_keyboard=True)

# Кнопка «поделиться контактом» + «Пропустить»
contact_kb = ReplyKeyboardMarkup(
    [[KeyboardButton("Поделиться контактом ☎️", request_contact=True)],
     ["Пропустить"]],
    resize_keyboard=True, one_time_keyboard=True
)

def parse_tz(text: str):
    """Понимает 'Europe/Moscow', 'UTC+3', 'GMT+3', '+3', '-5' -> tzinfo."""
    t = text.strip()
    # IANA-таймзона
    if "/" in t:
        try:
            return ZoneInfo(t)
        except Exception:
            pass
    # Смещение
    m = re.fullmatch(r'(?:UTC|GMT)?\s*([+-]?\d{1,2})', t, re.I)
    if m:
        try:
            off = int(m.group(1))
            return timezone(timedelta(hours=off))
        except Exception:
            pass
    return None

def get_user_tz(user_id: int):
    tz = users_data.get(user_id, {}).get("tzinfo")
    return tz if tz is not None else timezone.utc

def now_local(user_id: int):
    # Always return the current time in the user's timezone
    return datetime.now(get_user_tz(user_id))

def schedule_user_jobs(app, user_id: int):
    u = users_data.get(user_id, {})
    tz = u.get("tzinfo") or timezone.utc
    morning_h = int(u.get("morning_hour", 8))
    evening_h = int(u.get("evening_hour", 21))

    # Сначала отменим старые (если были)
    for job in app.job_queue.get_jobs_by_name(f"morning_{user_id}"):
        job.schedule_removal()
    for job in app.job_queue.get_jobs_by_name(f"evening_{user_id}"):
        job.schedule_removal()

    # Новые (передаём aware time с tzinfo)
    app.job_queue.run_daily(
        morning_weight_request_user,
        time=time(hour=morning_h, minute=0, tzinfo=tz),
        name=f"morning_{user_id}",
        data=user_id,
    )
    app.job_queue.run_daily(
        evening_report_user,
        time=time(hour=evening_h, minute=0, tzinfo=tz),
        name=f"evening_{user_id}",
        data=user_id,
    )

# Быстрый выбор удобного часа
def hour_kb(start=6, end=23):
    row = []
    rows = []
    for h in range(start, end+1):
        row.append(f"{h:02d}:00")
        if len(row) == 4:
            rows.append(row)
            row = []
    if row: rows.append(row)
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)

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

async def clarify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = users_data.get(user_id, {})
    pending = data.get("pending_meal")
    if not pending:
        await query.edit_message_reply_markup(None)
        await query.message.reply_text("Нет активной оценки. Отправь приём пищи текстом.")
        return

    action = query.data
    # базовая оценка
    base_cals = pending.get("base_calories", 0)
    adj = pending.setdefault("adjust", {"portion": 1.0, "oil_extra": 0})

    if action == "portion_small":
        adj["portion"] = 0.85
    elif action == "portion_normal":
        adj["portion"] = 1.0
    elif action == "portion_big":
        adj["portion"] = 1.15
    elif action == "oil_none":
        adj["oil_extra"] = 0
    elif action == "oil_tsp":
        adj["oil_extra"] = 45   # ~1 ч.л. масла ~ 45 ккал
    elif action == "oil_tbsp":
        adj["oil_extra"] = 120  # ~1 ст.л. масла ~ 120 ккал

    # пересчёт
    cals = int(round(base_cals * adj["portion"] + adj["oil_extra"]))
    pending["calories"] = cals

    # промежуточное обновление подписи
    if action != "finalize":
        txt = (f"Уточняем… Сейчас выходит ~{cals} ккал.\n"
               f"Выбери размер порции и масло, затем нажми «Готово ✅».")
        await query.edit_message_text(txt, reply_markup=_clarify_kb())
        return

    # финализация: пишем в дневник и убираем кнопки
    meal_entry = {
        "time": pending["time"],
        "calories": cals,
        "protein": pending.get("protein"),
        "fat": pending.get("fat"),
        "carbs": pending.get("carbs"),
        "raw": pending.get("raw"),
        "auto": True,
        "adjust": adj,
    }

    users_data.setdefault(user_id, {}).setdefault("meals", []).append(meal_entry)
    users_data[user_id]["pending_meal"] = None

    # --- Персонализированное напоминание ---
    meal_kind = pending.get("meal_kind")
    if meal_kind in ("soup", "eggs", "omelette"):
        delay = timedelta(hours=2)
        reminder_text = "Важно покушать через 2 часа после супа или яичницы!"
    else:
        delay = timedelta(hours=3)
        reminder_text = "Через 3 часа после этого приёма пищи важно позаботиться о себе и покушать!"

    async def personalized_reminder(context: ContextTypes.DEFAULT_TYPE):
        try:
            await context.bot.send_message(chat_id=user_id, text=reminder_text)
        except Exception as e:
            logger.error(f"Ошибка отправки персонального напоминания пользователю {user_id}: {e}")

    context.application.job_queue.run_once(personalized_reminder, when=delay)

    await query.edit_message_reply_markup(None)
    await query.message.reply_text(f"Записано: {cals} ккал ✅")
    
    save_meal(
        user_id,
        meal_entry["time"],
        meal_entry["calories"],
        meal_entry.get("protein"),
        meal_entry.get("fat"),
        meal_entry.get("carbs"),
        meal_entry.get("raw"),
        meal_entry.get("meal_kind"),
        meal_entry["adjust"].get("portion", 1.0),
        meal_entry["adjust"].get("oil_extra", 0)
    )
    
def _clarify_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Готово ✅", callback_data="finalize")]
    ])

OPENAI_SYSTEM_PROMPT = """
Ты — добрый, заботливый нутрициолог, помогающий людям восстановить режим питания. Пользователь присылает состав/описание приёма пищи, а твоя задача — аккуратно оценить КБЖУ и время до следующего приёма. Думай реалистичными порциями и типовыми продуктами; если описание расплывчатое, выбирай консервативную (более скромную) оценку.

Дополнительные цели:
• Веди учёт по каждому продукту мысленно — так, чтобы на основе накопленных данных можно было находить продукты, которые статистически ухудшают динамику веса, и те, что помогают.  
• Помни правила режима: завтрак в течение 2 часов после пробуждения; каждый приём пищи — полноценный (суп ИЛИ «гарнир + белок + овощи»). После супа пауза 2–3 часа; после полноценной тарелки — 3–4 часа.  
• Будь тёплым и поддерживающим: после расчёта можно добавить короткую дружелюбную заметку (мягкое напоминание про воду/сон/бережность к себе).

СТРОГИЙ ФОРМАТ ОТВЕТА — ТОЛЬКО JSON (без комментариев и лишнего текста), поля:
{
  "calories": <целое число>,               // суммарные ккал по приёму
  "protein_g": <число>,                    // суммарный белок, граммы
  "fat_g": <число>,                        // суммарный жир, граммы
  "carbs_g": <число>,                      // суммарные углеводы, граммы
  "meal_kind": "plate|soup|snack|dessert|drink",
  "next_meal_hours": 2|3|4,                // рекомендуемый интервал до следующего приёма
  "explanation": "очень коротко, как считал (основные продукты и порции)",
  "support": "1–2 предложения мягкой поддержки (например: Я всё записал; не забывай про воду и сон)"
}

Правила:
• «Полноценная тарелка» (гарнир+белок+овощи) => meal_kind="plate", next_meal_hours=3 или 4.  
• Суп => meal_kind="soup", next_meal_hours=2 или 3.  
• Отдельная сладость/фрукт/перекус => meal_kind="dessert" или "snack", обычно 3 часа.  
• Напиток без еды => meal_kind="drink" (обычно без изменения интервала, но укажи 2–3 часа, если был калорийный напиток).  
• Если упомянуто масло/соусы, добавь типичные калории (ч.л. ~45 ккал, ст.л. ~120 ккал).  
• Все числа — реальные, округляй калории до целых, макросы до десятых.
"""

# ==== OpenAI call ====
async def estimate_meal_nutrition(text: str) -> dict:
    if not OPENAI_AVAILABLE or client is None:
        return {}

    try:
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
        content = resp.choices[0].message.content
        json_match = re.search(r"\{.*\}", content, flags=re.S)
        if not json_match:
            raise ValueError("Не найден JSON в ответе модели")
        data = json.loads(json_match.group(0))
        if "calories" in data and "meal_kind" in data:
            return data
    except Exception as e:
        logger.warning(f"OpenAI недоступен/ошибка парсинга: {e}")

    return {}

# ==== Handlers (анкета) ====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    data = load_user_data(user.id)
    if data:
        users_data[user.id] = data
    else:
        users_data.setdefault(user.id, {})
        
    user = update.message.from_user
    users_data.setdefault(user.id, {})
    logger.info(f"Пользователь {user.id} ({user.full_name}) начал диалог")

    msg = (
        "Привет! Я бот по контролю питания и веса.\n\n"
        "👉 Разреши мне получить твой контакт — так я смогу в любой момент восстановить историю и напоминания, "
        "если ты сменишь устройство. Можешь пропустить."
    )
    await update.message.reply_text(msg, reply_markup=contact_kb)
    return ASK_CONTACT

async def handle_contact_or_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    d = users_data.setdefault(user.id, {})

    # Пользователь нажал «Пропустить»
    if update.message and update.message.text and update.message.text.strip().lower() == "пропустить":
        pass
    # Контакт
    elif update.message and isinstance(update.message.contact, Contact):
        d["phone"] = update.message.contact.phone_number

    # Спрашиваем часовой пояс
    txt = (
        "Укажи свой часовой пояс, чтобы я писал в уместное для тебя время.\n"
        "Например: Europe/Moscow или UTC+3 (можно просто +3).\n\n"
        "Если не уверен(а) — напиши город и попробуем подобрать позже."
    )
    await update.message.reply_text(txt, reply_markup=ReplyKeyboardRemove())
    return ASK_TZ

async def handle_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    tz = parse_tz(update.message.text or "")
    if not tz:
        await update.message.reply_text("Не получилось распознать. Пример: Europe/Moscow или UTC+3. Попробуй снова:")
        return ASK_TZ

    users_data.setdefault(user.id, {})["tzinfo"] = tz
    await update.message.reply_text(
        "Принято! Во сколько удобно присылать утренний запрос веса? Выбери час:",
        reply_markup=hour_kb(6, 11)
    )
    return ASK_MORNING_HOUR

async def handle_morning_hour(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    m = re.fullmatch(r'(\d{2}):00', (update.message.text or "").strip())
    if not m:
        await update.message.reply_text("Выбери из кнопок, пожалуйста (формат HH:00).")
        return ASK_MORNING_HOUR
    users_data.setdefault(user.id, {})["morning_hour"] = int(m.group(1))
    await update.message.reply_text(
        "А во сколько присылать вечерний итог дня?",
        reply_markup=hour_kb(19, 23)
    )
    return ASK_EVENING_HOUR

async def handle_evening_hour(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    m = re.fullmatch(r'(\d{2}):00', (update.message.text or "").strip())
    if not m:
        await update.message.reply_text("Выбери из кнопок, пожалуйста (формат HH:00).")
        return ASK_EVENING_HOUR
    users_data.setdefault(user.id, {})["evening_hour"] = int(m.group(1))

    # Ставим персональные ежедневные задачи
    schedule_user_jobs(context.application, user.id)

    # Переходим к анкете (имя)
    await update.message.reply_text(
        "Отлично! Теперь давай познакомимся. Как тебя зовут?",
        reply_markup=ReplyKeyboardRemove()
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
        "Я сам посчитаю КБЖУ через ChatGPT, предложу уточнение порции и поставлю напоминания."
    )
    save_user_data(user.id, users_data[user.id])
    # Сразу переходим в режим мониторинга
    return MONITORING

async def monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Режим мониторинга: здесь бот просто ждёт входящих сообщений с едой/калориями."""
    user = update.message.from_user
    users_data.setdefault(user.id, {})
    # Подсказка пользователю, если он прислал что-то непонятное
    await update.message.reply_text(
        "Я в режиме мониторинга — присылай приёмы пищи в свободной форме (например: «2 яйца, 200 г гречки, салат»)\n"
        "или калории числом с единицами (например: «350 ккал»). "
        "Чтобы выйти — /cancel."
    )
    return MONITORING

# ==== Обновлённый record_meal (с уточнениями) ====
# ...existing code...

async def record_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    text = update.message.text.strip().lower()
    data = users_data.setdefault(user_id, {})

    if "goal" not in data:
        await update.message.reply_text("Пожалуйста, начните с команды /start")
        return RECORD_MEAL

    # Разрешаем считать калории вручную ТОЛЬКО когда есть единицы "ккал/кал/kcal"
    cal_match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:к+кал+|кал+|калл+|калорий|ккалл+|k+cal+|kcals?|cal(?:ories)?)\b",
        text
    )

    if cal_match:
        # Ручной ввод калорий
        val = cal_match.group(1)
        cals = int(float(val.replace(",", ".")))
        now = now_local(user_id)
        data.setdefault("meals", []).append({"time": now, "calories": cals, "raw": text})
        data["pending_meal"] = None  # <--- вот эта строка
        logger.info(f"[manual] Пользователь {user_id}: {cals} ккал ({text})")
        await update.message.reply_text(f"Записано: {cals} ккал (ручной ввод).")
        return RECORD_MEAL

    # Автооценка через OpenAI
    await update.message.reply_text("Считаю калории…")
    nutri = {}
    if OPENAI_AVAILABLE and client is not None:
        try:
            nutri = await estimate_meal_nutrition(text)
        except Exception as e:
            logger.warning(f"Ошибка OpenAI для {user_id}: {e}")

    if not nutri or "calories" not in nutri:
        await update.message.reply_text(
            "Не удалось оценить блюдо автоматически 😕 Пришлите калории числом, например: 350 ккал."
        )
        logger.warning(f"Автооценка не удалась (OpenAI): '{text}' от {user_id}")
        return RECORD_MEAL

    # Готовим «ожидающую запись» и показываем клавиатуру уточнений
    base_cals = int(nutri["calories"])
    
    pending = {
    "time": now_local(user_id),
    "raw": text,
    "base_calories": base_cals,
    "protein": nutri.get("protein_g"),
    "fat": nutri.get("fat_g"),
    "carbs": nutri.get("carbs_g"),
    "meal_kind": nutri.get("meal_kind"),  # <--- добавить эту строку
    "adjust": {"portion": 1.0, "oil_extra": 0}
    }

    data["pending_meal"] = pending  # <--- обязательно сохраняем!

    p, f, ch = nutri.get("protein_g"), nutri.get("fat_g"), nutri.get("carbs_g")
    macros = f"\nБ: {p or '-'} г • Ж: {f or '-'} г • У: {ch or '-'} г"
    txt = (
        f"Предварительно: ~{base_cals} ккал за «{text}».{macros}\n\n"
        "Уточни размер порции и масло, затем нажми «Готово ✅»."
    )
    await update.message.reply_text(txt, reply_markup=_clarify_kb())
    return RECORD_MEAL

# ...existing code...

async def reminder_4h(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    now = now_local(user_id)
    if now.hour >= 21:
        return
    try:
        await context.bot.send_message(chat_id=user_id, text="Критично важно покушать примерно сейчас!")
    except Exception as e:
        logger.error(f"Ошибка отправки напоминания 4ч пользователю {user_id}: {e}")

async def morning_weight_request_user(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    try:
        await context.bot.send_message(chat_id=user_id, text="Доброе утро! Пожалуйста, сообщи свой текущий вес 🌤️")
    except Exception as e:
        logger.error(f"Ошибка утреннего запроса веса для {user_id}: {e}")

async def evening_report_user(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data
    data = users_data.get(user_id) or {}
    if not data:
        return
    date_today = now_local(user_id).date()
    meals = [m for m in data.get("meals", []) if m.get("time") and m["time"].date() == date_today]
    if not meals:
        return
    calories_today = sum(m.get("calories", 0) for m in meals)
    meals_count = len(meals)
    prot = sum((m.get("protein") or 0) for m in meals)
    fat  = sum((m.get("fat") or 0) for m in meals)
    carb = sum((m.get("carbs") or 0) for m in meals)

    text = (
        "Итог дня:\n"
        f"• Калории: {calories_today} ккал\n"
        f"• Приёмов пищи: {meals_count}\n"
        f"• КБЖУ: Б {round(prot,1)} г / Ж {round(fat,1)} г / У {round(carb,1)} г\n"
        "Напоминание: полноценная тарелка (гарнир+белок+овощи) помогает держать режим. Вода и сон — тоже важны 💧😴"
    )
    try:
        await context.bot.send_message(chat_id=user_id, text=text)
        # Анализируем и даем советы
        advice = analyze_user_day(user_id, date_today)
        if advice:
            await context.bot.send_message(chat_id=user_id, text=advice)
    except Exception as e:
        logger.error(f"Ошибка вечернего отчёта для {user_id}: {e}")

# ==== Weight input handler ====
async def handle_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    try:
        weight = float(update.message.text.replace(",", "."))
        users_data.setdefault(user.id, {}).setdefault("weights", []).append({"date": datetime.now().date(), "weight": weight})
        await update.message.reply_text(f"Спасибо, вес {weight} кг записан.")
        logger.info(f"Пользователь {user.id} ввел вес: {weight}")

        # Сохраняем в базу
        save_weight(user.id, datetime.now().date(), weight)
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
            
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "ℹ️ <b>Помощь по боту</b>\n\n"
        "• Просто напишите, что вы поели — бот сам оценит калории.\n"
        "• Можно указать калории вручную: <code>350 ккал</code>\n"
        "• Для уточнения порции и масла используйте кнопки после автооценки.\n"
        "• Введите вес числом, чтобы записать взвешивание.\n"
        "• Команда /report покажет дневной отчёт.\n"
        "• Команда /start — сбросить настройки и начать заново.\n"
        "\nЕсли возникли вопросы — напишите автору!"
    )
    await update.message.reply_text(text, parse_mode="HTML")

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
    print("main() запущен")
    
    create_tables()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")

    application = ApplicationBuilder().token(token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            # контакт или "Пропустить"
            ASK_CONTACT: [
                MessageHandler(
                    filters.CONTACT | filters.Regex("(?i)^пропустить$"),
                    handle_contact_or_skip
                )
            ],
            # часовой пояс
            ASK_TZ: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_timezone)],
            # утренний час
            ASK_MORNING_HOUR: [MessageHandler(filters.Regex(r"^\d{2}:00$"), handle_morning_hour)],
            # вечерний час
            ASK_EVENING_HOUR: [MessageHandler(filters.Regex(r"^\d{2}:00$"), handle_evening_hour)],

            # анкета
            ASK_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_gender)],
            ASK_GENDER:  [MessageHandler(filters.Regex("^(Мужской|Женский)$"), ask_age)],
            ASK_AGE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_weight)],
            ASK_WEIGHT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_height)],
            ASK_HEIGHT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_activity)],
            ASK_ACTIVITY:[MessageHandler(filters.Regex("^[1-5]{1}$"), ask_goal)],
            ASK_GOAL:    [MessageHandler(filters.Regex("^(Похудеть|Удержать вес|Набрать массу)$"), show_calorie_corridor)],

            # внесение еды
            RECORD_MEAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, record_meal)],
            MONITORING:  [MessageHandler(filters.TEXT & ~filters.COMMAND, record_meal)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(clarify_callback))
    application.add_handler(MessageHandler(filters.Regex(r"^\d+(?:[.,]\d+)?$"), handle_weight))
    application.add_error_handler(on_error)

    # Добавьте help-хендлер здесь:
    application.add_handler(CommandHandler("help", help_command))

    # ВАЖНО: не ставим глобальные run_daily — они теперь персональные (ставятся после выбора TZ/часов)

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()