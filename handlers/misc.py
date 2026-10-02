import logging
from datetime import timedelta
from telegram import ReplyKeyboardRemove
import db
from domain.tz import now_local, parse_clock
from handlers.start_flow import numeric
from services.analysis_service import history_summary, food_patterns
from services.storage import query
from texts import HELP

async def help_command(update, context):
    await update.message.reply_text(HELP)

async def cancel(update, context):
    await query(db.save_user_data,update.effective_user.id,{"flow_step":None})
    await update.message.reply_text("Заполнение остановлено. Дневник сохранён.",
                                     reply_markup=ReplyKeyboardRemove())

async def handle_weight(update, context, profile=None, text=None):
    profile = profile or await query(db.load_user_data,update.effective_user.id)
    if not profile.get("profile_complete") or not profile.get("timezone"):
        await update.message.reply_text("Сначала настроим анкету и время: /start.")
        return
    text = text if text is not None else " ".join(context.args)
    try:
        value = numeric(text,20,400)
    except ValueError:
        await update.message.reply_text("Напиши вес числом: /weight 80,2.")
        return
    today = update.message.date.astimezone(now_local(profile).tzinfo).date()
    await query(db.save_weight,profile["id"],today,value)
    rows = await query(db.get_weights,profile["id"],today-timedelta(days=13),today)
    recent = [w for _,w in rows[-7:]]
    msg = f"Вес {value:g} кг сохранён 🌿"
    if len(recent) >= 3:
        msg += f"\nСреднее по последним {len(recent)} записям: {sum(recent)/len(recent):.2f} кг."
    msg += "\nОдно число не определяет прогресс. Продолжаем спокойно."
    await update.message.reply_text(msg)

async def reminders_command(update, context):
    uid = update.effective_user.id
    profile = await query(db.load_user_data,uid)
    if not profile.get("profile_complete") or not profile.get("timezone"):
        await update.message.reply_text("Сначала настроим анкету и время: /start.")
        return
    try:
        if len(context.args) != 3:
            raise ValueError
        morning, evening = map(parse_clock,context.args[:2])
        interval = numeric(context.args[2],1,12,True)
        if morning >= evening:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "Формат: /reminders 08:00 21:00 4. Утро раньше вечера; интервал — от 1 до 12 часов.")
        return
    await query(db.save_user_data,uid,{"morning_time":morning,"evening_time":evening,"interval_hours":interval})
    await update.message.reply_text(f"Сохранено по твоему времени: утро {morning}, вечер {evening}, интервал {interval} ч.")

async def toggle_reminders(update, context):
    enabled = update.message.text.split()[0].split("@")[0] == "/resume"
    await query(db.save_user_data,update.effective_user.id,{"reminders_enabled":enabled})
    await update.message.reply_text("Напоминания включены." if enabled else "Напоминания выключены. Дневник доступен.")

async def progress_command(update, context):
    profile = await query(db.load_user_data,update.effective_user.id)
    if not profile.get("profile_complete") or not profile.get("timezone"):
        await update.message.reply_text("Сначала настроим анкету и время: /start.")
        return
    summary = await query(history_summary,profile["id"],now_local(profile).date(),profile)
    if not summary["logged_days"] and not summary["weight_measurements"]:
        await update.message.reply_text("Пока нет записей для сравнения. Начнём с сегодняшнего дня 🌿")
        return
    lines = ["Наблюдения за последние 14 дней (только по дневнику):"]
    for key,label in (("previous_week","Предыдущие 7 дней"),("recent_week","Последние 7 дней")):
        period = summary[key]
        gap = "нет данных" if period["average_gap_hours"] is None else f"{period['average_gap_hours']} ч"
        weight = "недостаточно записей" if period["average_weight"] is None else f"{period['average_weight']} кг"
        lines.append(f"• {label}: {period['logged_days']} дней с записями, {period['unique_foods']} продуктов; "
                     f"средний перерыв {gap}; средний вес {weight}.")
    lines.append("Пропущенные записи не означают пропущенную еду. Забота о себе — тоже прогресс 🌿")
    await update.message.reply_text("\n".join(lines))

async def patterns_command(update, context):
    profile = await query(db.load_user_data,update.effective_user.id)
    if not profile.get("profile_complete") or not profile.get("timezone"):
        await update.message.reply_text("Сначала настроим анкету и время: /start.")
        return
    patterns = await query(food_patterns,profile["id"],now_local(profile).date(),profile)
    if not patterns:
        await update.message.reply_text(
            "Пока недостаточно данных для связей еды и веса. Для продукта нужны минимум 3 дня "
            "с ним и 3 дня без него, с весом в оба соседних утра. Ручные калории без состава "
            "в такое сравнение не входят.")
        return
    lines = ["Наблюдаемые связи за 28 дней:"]
    for p in patterns:
        lines.append(f"• {p['food']}: среднее изменение к следующему утру {p['with_mean_kg']:+.2f} кг "
                     f"в {p['with_days']} днях с продуктом; {p['without_mean_kg']:+.2f} кг "
                     f"в {p['without_days']} днях без него.")
    lines.append("Это наблюдения, не доказательство влияния продукта: причинные выводы и запреты по ним не делаем.")
    await update.message.reply_text("\n".join(lines))

async def last_notifications(update, context):
    rows = await query(db.load_last_notifications,update.effective_user.id)
    await update.message.reply_text("\n".join(f"{kind} — {stamp.isoformat()}" for kind,stamp in rows)
                                     or "Уведомлений пока нет.")

async def on_error(update, context):
    error = context.error
    logging.getLogger(__name__).error("Update failed: %s",type(error).__name__)
    if update is not None and getattr(update,"effective_message",None):
        try:
            await update.effective_message.reply_text(
                "Сейчас действие не завершилось. Попробуй ещё раз. "
                "Подтверждённые записи сохраняются; повторное подтверждение не добавляет дубль.")
        except Exception:
            pass
