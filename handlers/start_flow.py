"""Durable, resumable onboarding stored in PostgreSQL."""
from datetime import datetime, timezone
import math
from telegram import ReplyKeyboardRemove

import config
import db
from domain.calories import calorie_corridor
from domain.tz import parse_clock, parse_tz, timezone_name, user_timezone
from keyboards import (activity_kb, contact_kb, deficit_kb, gender_kb, goal_kb,
                       main_menu_kb, skip_kb)
from services.storage import query
from states import BotState
from texts import (ASK_CITY, ASK_CONTACT, HELLO, TRIAL_ENDED, TRIAL_MESSAGE,
                   UPDATE_NOTICE)

FOCUS_OPTIONS = {
    "1":"Соблюдать режим питания",
    "2":"Контролировать калории и КБЖУ",
    "3":"Искать связи питания и веса",
    "4":"Получать поддержку",
}


def numeric(text, minimum, maximum, integer=False):
    try:
        value = float(text.replace(",","."))
    except (AttributeError,ValueError):
        raise ValueError("Введите число.") from None
    if not math.isfinite(value) or not minimum <= value <= maximum or (integer and value != int(value)):
        raise ValueError("Значение вне допустимого диапазона.")
    return int(value) if integer else value


async def ensure_profile(update):
    user = update.effective_user
    return await query(db.ensure_user,user.id,user.username,user.first_name)


async def ask(message, step, profile=None):
    prompts = {
        BotState.NAME:"Как тебя зовут?",
        BotState.CONTACT:ASK_CONTACT.format(name=(profile or {}).get("name") or ""),
        BotState.TIMEZONE:ASK_CITY,
        BotState.GENDER:"Укажи пол — он нужен только для расчёта обмена веществ.",
        BotState.AGE:"Сколько тебе лет? Бот рассчитан на взрослых пользователей (18+).",
        BotState.WEIGHT:"Какой у тебя сейчас вес в килограммах? Например: 80,2.",
        BotState.GOAL:"Какая у тебя сейчас цель?",
        BotState.TARGET_WEIGHT:"К какому весу ты хочешь прийти? Напиши число в килограммах.",
        BotState.HEIGHT:"Какой у тебя рост в сантиметрах?",
        BotState.ACTIVITY:("Выбери уровень активности:\n1 — обычный образ жизни без тренировок или до двух лёгких занятий в неделю;\n"
                           "2 — полноценные тренировки 2–3 раза в неделю;\n3 — спорт до 5 раз в неделю;\n"
                           "4 — активный спорт 5 и более раз в неделю."),
        BotState.FOCUS:("Что особенно важно получать от бота? Можно выбрать несколько вариантов. "
                        "Напиши номера через запятую:\n1 — соблюдать режим питания\n"
                        "2 — контролировать калории и КБЖУ\n3 — искать связи питания и веса\n"
                        "4 — получать поддержку"),
        BotState.LIMITATIONS:("Есть ли заболевания, аллергии или другие ограничения, которые важно учитывать? "
                              "Напиши их или выбери «Нет ограничений»."),
        BotState.MORNING_TIME:"Во сколько по твоему времени присылать доброе утро и приглашение взвеситься? Например: 08:00.",
        BotState.EVENING_TIME:"Во сколько присылать вечерний отчёт? Например: 21:00.",
        BotState.DEFICIT:("При твоём весе можно выбрать комфортный дефицит 10% или более строгий "
                          "дефицит 20% для более быстрого результата. Какой темп тебе подходит?"),
        BotState.LOG_WEIGHT:"Напиши сегодняшний вес в килограммах, например: 79,6.",
        BotState.WEIGHT_CONTEXT:("Чтобы точнее разбирать динамику, напиши, сколько часов ты спал(а) этой ночью. "
                                 "Можно ответить «Пропустить»."),
    }
    keyboards = {BotState.CONTACT:contact_kb,BotState.GENDER:gender_kb,
                 BotState.ACTIVITY:activity_kb,BotState.GOAL:goal_kb,
                 BotState.LIMITATIONS:skip_kb,BotState.DEFICIT:deficit_kb}
    await message.reply_text(prompts[step],reply_markup=keyboards.get(step,ReplyKeyboardRemove()))


async def set_step(user_id, message, step, fields=None):
    await query(db.save_user_data,user_id,{**(fields or {}),"flow_step":str(step)})
    profile = await query(db.load_user_data,user_id)
    await ask(message,step,profile)


async def notify_new_user(update, context, profile):
    if profile.get("new_user_notified") or not config.ADMIN_ID:
        return
    username = f"@{update.effective_user.username}" if update.effective_user.username else "без username"
    try:
        await context.bot.send_message(
            chat_id=config.ADMIN_ID,
            text=("Новый пользователь «Налегке» 🌿\n"
                  f"Имя Telegram: {update.effective_user.first_name or 'не указано'}\n"
                  f"Username: {username}\nID: {update.effective_user.id}"))
        await query(db.mark_new_user_notified,profile["id"])
    except Exception:
        # The user must still be able to enter the bot if the admin chat is unavailable.
        pass


async def start(update, context):
    profile = await ensure_profile(update)
    await notify_new_user(update,context,profile)
    if profile.get("profile_complete") and profile.get("onboarding_version") == config.ONBOARDING_VERSION:
        if not await query(db.access_active,profile["id"],datetime.now(timezone.utc)):
            await update.message.reply_text(TRIAL_ENDED,reply_markup=ReplyKeyboardRemove())
            return
        await query(db.save_user_data,profile["id"],{"flow_step":None})
        await update.message.reply_text(
            f"С возвращением, {profile.get('name') or 'друг'} 🌿 Что посмотрим?",
            reply_markup=main_menu_kb)
        return
    if profile.get("flow_step") and profile.get("flow_step") in {str(s) for s in BotState}:
        await update.message.reply_text("Продолжим знакомство с того места, где остановились.")
        await ask(update.message,BotState(profile["flow_step"]),profile)
        return
    await query(db.save_user_data,profile["id"],{"profile_complete":False,"flow_step":str(BotState.NAME)})
    await update.message.reply_text(UPDATE_NOTICE if profile.get("legacy_user") else HELLO,
                                    reply_markup=ReplyKeyboardRemove())


async def edit_profile(update, context):
    profile = await ensure_profile(update)
    await query(db.save_user_data,profile["id"],{"flow_step":str(BotState.NAME)})
    await update.message.reply_text("Обновим анкету. Как тебя зовут?",reply_markup=ReplyKeyboardRemove())


async def change_timezone(update, context):
    profile = await ensure_profile(update)
    await query(db.save_user_data,profile["id"],{"flow_step":"timezone_only"})
    await update.message.reply_text(ASK_CITY,reply_markup=ReplyKeyboardRemove())


def parse_focus(text):
    values = [part for part in text.replace(";",",").replace(" ",",").split(",") if part]
    if not values or any(value not in FOCUS_OPTIONS for value in values):
        raise ValueError("Напиши номера от 1 до 4 через запятую, например: 1,2,4.")
    return [FOCUS_OPTIONS[value] for value in dict.fromkeys(values)]


def goal_recommendation(profile):
    common = ("Старайся питаться регулярно, ориентироваться на голод и аппетит и не делать "
              "перерывы между едой заметно длиннее трёх часов. Будем постепенно добавлять "
              "разнообразие и искать баланс между белками, жирами, углеводами и растительными "
              "продуктами. Не нужно менять всё сразу: один доступный шаг — уже забота о себе.")
    if profile["goal"] == "Похудеть":
        return (common+" Если тянет к еде без физического голода, попробуй заметить, не стоят ли "
                "за этим усталость, грусть или напряжение.")
    if profile["goal"] == "Набрать массу":
        return (common+" Для набора особенно важно не пропускать приёмы пищи и добирать достаточно "
                "энергии и белка.")
    return common+" Для удержания веса будем смотреть прежде всего на устойчивость режима и среднюю динамику."


async def finish_onboarding(update, user_id):
    profile = await query(db.load_user_data,user_id)
    low,high = calorie_corridor(profile)
    await query(db.save_user_data,user_id,{"calorie_lower":low,"calorie_upper":high,
        "goal_start_weight":profile["weight"],"milestones_reached":0,"profile_complete":True,
        "flow_step":None,"onboarding_version":config.ONBOARDING_VERSION})
    completed = await query(db.load_user_data,user_id)
    instant = datetime.now(timezone.utc)
    local_day = instant.astimezone(user_timezone(completed)).date()
    await query(db.save_weight,user_id,local_day,completed["weight"])
    _,trial_ends = await query(db.activate_trial,user_id,instant,config.TRIAL_MONTHS)
    trial_text = (TRIAL_MESSAGE.format(date=trial_ends.astimezone(user_timezone(completed)).strftime("%d.%m.%Y"))
                  if trial_ends > instant else TRIAL_ENDED)
    await update.message.reply_text(
        f"Анкета готова 🌿 Твой ориентировочный коридор: {low}–{high} ккал.\n\n"
        +goal_recommendation(completed)+"\n\n"+trial_text,reply_markup=main_menu_kb)

    if await query(db.access_active,user_id,instant):
        await update.message.reply_text(
            "Теперь рассказывай мне о своих приёмах пищи 🌿\n\n"
            "Напиши, что и примерно сколько ты поел(а). Например: «2 яйца и 150 г гречки». "
            "Отправляй записи прямо сюда после каждого приёма пищи.\n\n"
            "Давай начнём: что ты ел(а) в последний раз?",
            reply_markup=main_menu_kb)


async def handle_flow(update, context, profile):
    step = profile.get("flow_step")
    if not step:
        return False
    text = (update.message.text or "").strip()
    uid = profile["id"]
    try:
        if step == "timezone_only":
            tz = parse_tz(text)
            if tz is None:
                raise ValueError("Не удалось распознать город. Например: Тюмень или Москва.")
            await query(db.save_user_data,uid,{"timezone":timezone_name(tz),"flow_step":None})
            await update.message.reply_text("Город и часовой пояс сохранены.",reply_markup=main_menu_kb)
        elif step == BotState.NAME:
            if not 1 <= len(text) <= 80:
                raise ValueError("Напиши имя длиной до 80 символов.")
            await set_step(uid,update.message,BotState.CONTACT,{"name":text})
        elif step == BotState.CONTACT:
            contact = update.message.contact
            if contact is None and text.lower() != "пропустить":
                raise ValueError("Поделись контактом кнопкой или выбери «Пропустить».")
            fields = {"phone":contact.phone_number} if contact else {}
            await set_step(uid,update.message,BotState.TIMEZONE,fields)
        elif step == BotState.TIMEZONE:
            tz = parse_tz(text)
            if tz is None:
                raise ValueError("Не удалось распознать город. Например: Тюмень или Москва.")
            await set_step(uid,update.message,BotState.GENDER,{"timezone":timezone_name(tz)})
        elif step == BotState.GENDER:
            if text not in ("Мужской","Женский"):
                raise ValueError("Выбери вариант на клавиатуре.")
            await set_step(uid,update.message,BotState.AGE,{"gender":text})
        elif step == BotState.AGE:
            await set_step(uid,update.message,BotState.WEIGHT,{"age":numeric(text,18,100,True)})
        elif step == BotState.WEIGHT:
            await set_step(uid,update.message,BotState.GOAL,{"weight":numeric(text,20,400)})
        elif step == BotState.GOAL:
            if text not in ("Похудеть","Удержать вес","Набрать массу"):
                raise ValueError("Выбери цель на клавиатуре.")
            await set_step(uid,update.message,BotState.TARGET_WEIGHT,{"goal":text})
        elif step == BotState.TARGET_WEIGHT:
            target = numeric(text,20,400)
            if profile["goal"] == "Похудеть" and target >= profile["weight"]:
                raise ValueError("Для похудения желаемый вес должен быть ниже текущего.")
            if profile["goal"] == "Набрать массу" and target <= profile["weight"]:
                raise ValueError("Для набора желаемый вес должен быть выше текущего.")
            await set_step(uid,update.message,BotState.HEIGHT,{"target_weight":target})
        elif step == BotState.HEIGHT:
            await set_step(uid,update.message,BotState.ACTIVITY,{"height":numeric(text,100,250,True)})
        elif step == BotState.ACTIVITY:
            await set_step(uid,update.message,BotState.FOCUS,{"activity":numeric(text,1,4,True)})
        elif step == BotState.FOCUS:
            await set_step(uid,update.message,BotState.LIMITATIONS,{"focus_areas":parse_focus(text)})
        elif step == BotState.LIMITATIONS:
            if not text or len(text) > 1000:
                raise ValueError("Напиши ограничения кратко, до 1000 символов.")
            limitations = None if text.lower() == "нет ограничений" else text
            await set_step(uid,update.message,BotState.MORNING_TIME,{"limitations":limitations})
        elif step == BotState.MORNING_TIME:
            await set_step(uid,update.message,BotState.EVENING_TIME,{"morning_time":parse_clock(text)})
        elif step == BotState.EVENING_TIME:
            evening = parse_clock(text)
            if evening <= profile["morning_time"]:
                raise ValueError("Вечерний отчёт должен быть позже утреннего напоминания.")
            await query(db.save_user_data,uid,{"evening_time":evening})
            current = await query(db.load_user_data,uid)
            if current["goal"] == "Похудеть" and current["weight"] > 80:
                await set_step(uid,update.message,BotState.DEFICIT)
            else:
                await query(db.save_user_data,uid,{"deficit_percent":10})
                await finish_onboarding(update,uid)
        elif step == BotState.DEFICIT:
            choices = {"Комфортный — 10%":10,"Более быстрый — 20%":20}
            if text not in choices:
                raise ValueError("Выбери один из двух вариантов на клавиатуре.")
            await query(db.save_user_data,uid,{"deficit_percent":choices[text]})
            await finish_onboarding(update,uid)
        elif step == BotState.LOG_WEIGHT:
            from handlers.misc import handle_weight
            await handle_weight(update,context,profile,text)
        elif step == BotState.WEIGHT_CONTEXT:
            if text.lower() == "пропустить":
                await query(db.save_user_data,uid,{"flow_step":None})
                await update.message.reply_text("Хорошо, продолжим наблюдение по имеющимся данным.",reply_markup=main_menu_kb)
            else:
                hours = numeric(text,0,24)
                day = update.message.date.astimezone(user_timezone(profile)).date()
                await query(db.save_checkin,uid,day,hours,None)
                await query(db.save_user_data,uid,{"flow_step":None})
                observation = ("Сон был короче семи часов; это могло повлиять на краткосрочное изменение веса. "
                               "Продолжим наблюдать, повторяется ли связь."
                               if hours < 7 else
                               "Продолжительность сна записана. Я не вижу явного недосыпа, поэтому продолжим искать связи в динамике.")
                await update.message.reply_text(observation,reply_markup=main_menu_kb)
        else:
            await query(db.save_user_data,uid,{"flow_step":None})
            return False
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        if step in {str(s) for s in BotState}:
            await ask(update.message,BotState(step),profile)
    return True
