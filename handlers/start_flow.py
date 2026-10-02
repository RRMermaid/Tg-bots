"""Resumable onboarding stored in SQL; no ConversationHandler state in RAM."""
import math
from telegram import ReplyKeyboardRemove
import db
from domain.tz import now_local, parse_tz, timezone_name
from domain.calories import calculate_bmr, calculate_tdee, calculate_calorie_range
from keyboards import gender_kb, activity_kb, goal_kb
from services.storage import query
from states import BotState
from texts import HELLO, ASK_LOCAL_TIME

QUESTIONS = {
    BotState.TIMEZONE:ASK_LOCAL_TIME, BotState.NAME:"Как тебя зовут?",
    BotState.GENDER:"Укажи пол для расчётной формулы.",
    BotState.AGE:"Сколько тебе лет? Бот рассчитан на взрослых (18+).",
    BotState.WEIGHT:"Какой сейчас вес в килограммах? Например, 80,2.",
    BotState.HEIGHT:"Какой рост в сантиметрах?",
    BotState.ACTIVITY:"Выбери активность: 1 — преимущественно сидячая, 2 — невысокая, "
                      "3 — средняя, 4 — высокая, 5 — очень высокая.",
    BotState.GOAL:"Какая цель тебе сейчас подходит?",
}

def numeric(text, minimum, maximum, integer=False):
    try:
        value = float(text.replace(",","."))
    except ValueError:
        raise ValueError("Введите число.") from None
    if not math.isfinite(value) or not minimum <= value <= maximum or (integer and value != int(value)):
        raise ValueError("Значение вне допустимого диапазона.")
    return int(value) if integer else value

async def ask(message, step):
    kb = {BotState.GENDER:gender_kb,BotState.ACTIVITY:activity_kb,BotState.GOAL:goal_kb}
    await message.reply_text(QUESTIONS[step],reply_markup=kb.get(step,ReplyKeyboardRemove()))

async def set_step(user_id, message, step, fields=None):
    await query(db.save_user_data,user_id,{**(fields or {}),"flow_step":step})
    await ask(message,step)

async def start(update, context):
    profile = await query(db.ensure_user,update.effective_user.id)
    if profile["profile_complete"] and profile.get("timezone"):
        await query(db.save_user_data,profile["id"],{"flow_step":None})
        await update.message.reply_text(
            "С возвращением 🌿 Дневник и настройки сохранены. Пиши еду обычными словами "
            "или посмотри /help.",reply_markup=ReplyKeyboardRemove())
        return
    await update.message.reply_text(HELLO)
    step = profile.get("flow_step")
    if step not in QUESTIONS:
        step = BotState.TIMEZONE if not profile.get("timezone") else BotState.NAME
    await set_step(profile["id"],update.message,step)

async def edit_profile(update, context):
    profile = await query(db.ensure_user,update.effective_user.id)
    await set_step(profile["id"],update.message,
                   BotState.NAME if profile.get("timezone") else BotState.TIMEZONE,
                   {"profile_complete":False})

async def change_timezone(update, context):
    await query(db.ensure_user,update.effective_user.id)
    await set_step(update.effective_user.id,update.message,BotState.TIMEZONE)

async def handle_flow(update, context, profile):
    step = profile.get("flow_step")
    if not step:
        return False
    text = (update.message.text or "").strip()
    uid = profile["id"]
    try:
        if step == BotState.TIMEZONE:
            tz = parse_tz(text)
            if tz is None:
                raise ValueError("Не удалось распознать город или пояс. Например, Тюмень или UTC+5.")
            fields = {"timezone":timezone_name(tz)}
            if profile["profile_complete"]:
                await query(db.save_user_data,uid,{**fields,"flow_step":None})
                await update.message.reply_text("Часовой пояс сохранён: "+fields["timezone"],
                                                 reply_markup=ReplyKeyboardRemove())
            else:
                await set_step(uid,update.message,BotState.NAME,fields)
        elif step == BotState.NAME:
            if not 1 <= len(text) <= 80:
                raise ValueError("Напиши имя длиной до 80 символов.")
            await set_step(uid,update.message,BotState.GENDER,{"name":text})
        elif step == BotState.GENDER:
            if text not in ("Мужской","Женский"):
                raise ValueError("Выбери вариант на клавиатуре.")
            await set_step(uid,update.message,BotState.AGE,{"gender":text})
        elif step == BotState.AGE:
            await set_step(uid,update.message,BotState.WEIGHT,{"age":numeric(text,18,100,True)})
        elif step == BotState.WEIGHT:
            await set_step(uid,update.message,BotState.HEIGHT,{"weight":numeric(text,20,400)})
        elif step == BotState.HEIGHT:
            await set_step(uid,update.message,BotState.ACTIVITY,{"height":numeric(text,100,250,True)})
        elif step == BotState.ACTIVITY:
            await set_step(uid,update.message,BotState.GOAL,{"activity":numeric(text,1,5,True)})
        elif step == BotState.GOAL:
            if text not in ("Похудеть","Удержать вес","Набрать массу"):
                raise ValueError("Выбери цель на клавиатуре.")
            await query(db.save_user_data,uid,{"goal":text,"profile_complete":True,"flow_step":None})
            await query(db.save_weight,uid,now_local(profile).date(),profile["weight"])
            bmr = calculate_bmr(profile["weight"],profile["height"],profile["age"],profile["gender"])
            low, high = calculate_calorie_range(calculate_tdee(bmr,profile["activity"]),text)
            await update.message.reply_text(
                f"Анкета сохранена 🌿 Приблизительный ориентир: {round(low)}–{round(high)} ккал. "
                "Это оценка, а не назначение и не экзамен.\n"
                "Пиши еду текстом; я предложу оценку для подтверждения.\n"
                f"Утро: {profile['morning_time']}, вечер: {profile['evening_time']}, "
                f"интервал заботы о себе: {profile['interval_hours']} ч. Настройки: /reminders.",
                reply_markup=ReplyKeyboardRemove())
        else:
            await query(db.save_user_data,uid,{"flow_step":None})
            await update.message.reply_text("Продолжим с /start.")
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        await ask(update.message,step)
    return True
