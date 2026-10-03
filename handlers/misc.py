import logging
from datetime import timedelta

import db
from domain.calories import calorie_corridor, reached_milestones
from domain.tz import now_local, parse_clock, user_timezone
from handlers.start_flow import numeric
from keyboards import main_menu_kb, skip_only_kb
from services.analysis_service import (day_summary, food_patterns, history_summary,
                                       routine_weight_pattern)
from services.storage import query
from states import BotState
from texts import HELP


async def help_command(update, context):
    await update.message.reply_text(HELP,reply_markup=main_menu_kb)


async def cancel(update, context):
    await query(db.save_user_data,update.effective_user.id,{"flow_step":None})
    await query(db.abandon_active_drafts,update.effective_user.id)
    await update.message.reply_text("Действие остановлено. Сохранённые записи остались в дневнике.",
                                     reply_markup=main_menu_kb)


def ordinal_five(number):
    words = {1:"Первая",2:"Вторая",3:"Третья",4:"Четвёртая",5:"Пятая"}
    return words.get(number,f"{number}-я")


def wanted_direction(goal, diff):
    if goal == "Похудеть":
        return diff < 0
    if goal == "Набрать массу":
        return diff > 0
    return abs(diff) <= 0.3


async def weight_facts(profile, day):
    previous_day = day-timedelta(days=1)
    summary = await query(day_summary,profile["id"],previous_day,profile)
    facts = []
    checkin = await query(db.get_checkin,profile["id"],day)
    if checkin and checkin.get("sleep_hours") is not None:
        facts.append(f"Перед этим взвешиванием записано {checkin['sleep_hours']:g} часа сна.")
    if summary["meals"]:
        last = summary["meals"][-1]
        evening_h,evening_m = map(int,profile["evening_time"].split(":"))
        meal_h,meal_m = map(int,last["local_time"].split(":"))
        if meal_h*60+meal_m >= evening_h*60+evening_m-120:
            facts.append(f"Последняя записанная еда была в {last['local_time']}; поздний приём мог временно отразиться на весе.")
    if summary["totals"]["water_ml"]:
        facts.append(f"За вчера в дневнике записано {summary['totals']['water_ml']} мл воды — учитываю только внесённый объём.")
    else:
        facts.append("За вчера нет данных о воде, поэтому её влияние оценить нельзя.")
    patterns = await query(food_patterns,profile["id"],day,profile)
    if patterns:
        pattern = patterns[0]
        facts.append(
            f"Для «{pattern['food']}» уже есть наблюдение: среднее изменение к утру "
            f"{pattern['with_mean_kg']:+.2f} кг в {pattern['with_days']} днях с продуктом и "
            f"{pattern['without_mean_kg']:+.2f} кг в {pattern['without_days']} днях без него. "
            "Это связь в дневнике, а не доказанная причина.")
    return facts


async def handle_weight(update, context, profile=None, text=None):
    profile = profile or await query(db.load_user_data,update.effective_user.id)
    if not profile.get("profile_complete") or not profile.get("timezone"):
        await update.message.reply_text("Сначала заполним анкету: /start.")
        return
    text = text if text is not None else " ".join(context.args)
    try:
        value = numeric(text,20,400)
    except ValueError:
        await update.message.reply_text("Напиши вес числом, например: 79,6.")
        return
    today = update.message.date.astimezone(user_timezone(profile)).date()
    rows = await query(db.get_weights,profile["id"],today-timedelta(days=28),today)
    previous = next((weight for stamp,weight in reversed(rows) if stamp < today),None)
    await query(db.save_weight,profile["id"],today,value)
    await query(db.save_user_data,profile["id"],{"flow_step":None})
    lines = [f"Вес {value:g} кг сохранён 🌿"]
    undesirable = False
    if previous is not None:
        diff = round(value-previous,2)
        if wanted_direction(profile["goal"],diff):
            if profile["goal"] == "Похудеть" and diff < 0:
                lines.append(f"Хорошая динамика: {diff:+g} кг с прошлого взвешивания.")
            elif profile["goal"] == "Набрать массу" and diff > 0:
                lines.append(f"Нужная для набора динамика: +{diff:g} кг с прошлого взвешивания.")
            else:
                lines.append(f"Вес остаётся стабильным: изменение {diff:+g} кг.")
        else:
            undesirable = True
            direction = "вырос" if diff > 0 else "снизился"
            lines.append(f"Вес {direction} на {abs(diff):g} кг. Посмотрим на возможные факторы без поспешных выводов.")
            lines.extend(await weight_facts(profile,today))

    start_weight = profile.get("goal_start_weight") or profile.get("weight") or value
    old_count = int(profile.get("milestones_reached") or 0)
    new_count = reached_milestones(float(start_weight),value,profile["goal"])
    if new_count > old_count:
        low,high = calorie_corridor(profile,value)
        await query(db.save_user_data,profile["id"],{
            "milestones_reached":new_count,"calorie_lower":low,"calorie_upper":high})
        label = ordinal_five(new_count)
        if profile["goal"] == "Похудеть":
            lines.append(f"Урааа! {label} пятёрка в прошлом 🎉 Новый коридор: {low}–{high} ккал.")
        else:
            lines.append(f"Урааа! {label} пятёрка набрана 🎉 Новый коридор: {low}–{high} ккал.")

    recent = [weight for stamp,weight in rows if stamp < today][-6:]+[value]
    if len(recent) >= 3:
        lines.append(f"Среднее по последним {len(recent)} измерениям: {sum(recent)/len(recent):.2f} кг.")
    if profile.get("target_weight") is not None:
        reached = ((profile["goal"] == "Похудеть" and value <= profile["target_weight"]) or
                   (profile["goal"] == "Набрать массу" and value >= profile["target_weight"]))
        if reached:
            lines.append("Ты достиг(ла) указанного желаемого веса. Можно обновить цель через /profile.")

    if undesirable:
        await query(db.save_user_data,profile["id"],{"flow_step":str(BotState.WEIGHT_CONTEXT)})
        lines.append("Сон тоже может влиять на краткосрочную динамику. Сколько часов ты спал(а) этой ночью?")
        await update.message.reply_text("\n".join(lines),reply_markup=skip_only_kb)
    else:
        await update.message.reply_text("\n".join(lines),reply_markup=main_menu_kb)


async def reminders_command(update, context):
    uid = update.effective_user.id
    try:
        if len(context.args) not in (2,3):
            raise ValueError
        morning,evening = map(parse_clock,context.args[:2])
        if morning >= evening:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Формат: /reminders 08:00 21:00. Утро должно быть раньше вечера.")
        return
    await query(db.save_user_data,uid,{"morning_time":morning,"evening_time":evening})
    await update.message.reply_text(f"Сохранено: утро {morning}, вечерний отчёт {evening}.",reply_markup=main_menu_kb)


async def toggle_reminders(update, context):
    enabled = update.message.text.split()[0].split("@")[0] == "/resume"
    await query(db.save_user_data,update.effective_user.id,{"reminders_enabled":enabled})
    await update.message.reply_text("Напоминания включены." if enabled else "Напоминания выключены. Дневник доступен.",
                                    reply_markup=main_menu_kb)


async def week_command(update, context):
    profile = await query(db.load_user_data,update.effective_user.id)
    end = now_local(profile).date()
    summary = await query(history_summary,profile["id"],end,profile)
    week = summary["recent_week"]
    if not week["logged_days"] and not week["weight_measurements"]:
        await update.message.reply_text("За последние семь дней пока нет данных для анализа.",reply_markup=main_menu_kb)
        return
    gap = "недостаточно данных" if week["average_gap_hours"] is None else f"{week['average_gap_hours']} ч"
    weight = "недостаточно измерений" if week["average_weight"] is None else f"{week['average_weight']} кг"
    lines = ["Анализ последних 7 дней:",
             f"• Дней с записями питания: {week['logged_days']}",
             f"• Записано приёмов пищи: {week['logged_meals']}",
             f"• Средний интервал между записями: {gap}",
             f"• Интервалов дольше 5 часов: {week['long_gaps']}",
             f"• Средний вес: {weight}"]
    await update.message.reply_text("\n".join(lines),reply_markup=main_menu_kb)


async def progress_command(update, context):
    profile = await query(db.load_user_data,update.effective_user.id)
    summary = await query(history_summary,profile["id"],now_local(profile).date(),profile)
    if not summary["logged_days"] and not summary["weight_measurements"]:
        await update.message.reply_text("Пока нет записей для сравнения.",reply_markup=main_menu_kb)
        return
    lines = [f"Прогресс относительно цели «{profile['goal']}» за 14 дней:"]
    for key,label in (("previous_week","Предыдущие 7 дней"),("recent_week","Последние 7 дней")):
        period = summary[key]
        gap = "нет данных" if period["average_gap_hours"] is None else f"{period['average_gap_hours']} ч"
        weight = "недостаточно измерений" if period["average_weight"] is None else f"{period['average_weight']} кг"
        lines.append(f"• {label}: {period['logged_days']} дней питания; средний интервал {gap}; средний вес {weight}.")
    await update.message.reply_text("\n".join(lines),reply_markup=main_menu_kb)


async def recommendations_command(update, context):
    profile = await query(db.load_user_data,update.effective_user.id)
    end = now_local(profile).date()
    history = await query(history_summary,profile["id"],end,profile)
    routine = await query(routine_weight_pattern,profile["id"],end,profile)
    foods = await query(food_patterns,profile["id"],end,profile)
    if not history["logged_days"]:
        await update.message.reply_text("Пока недостаточно записей. Начни с еды и веса — рекомендации появятся по твоим данным.",
                                        reply_markup=main_menu_kb)
        return
    lines = ["Рекомендации по твоим записям:"]
    recent = history["recent_week"]
    if recent["average_gap_hours"] is not None:
        if recent["average_gap_hours"] > 4:
            lines.append(f"• Средний записанный интервал — {recent['average_gap_hours']} ч. Попробуй заранее планировать следующий приём ближе к трём часам.")
        else:
            lines.append(f"• Средний записанный интервал — {recent['average_gap_hours']} ч: режим выглядит достаточно регулярным.")
    if routine:
        lines.append(f"• В {routine['regular_days']} днях с интервалами до 4 часов среднее изменение к утру было "
                     f"{routine['regular_mean_kg']:+.2f} кг; в {routine['irregular_days']} других днях — "
                     f"{routine['irregular_mean_kg']:+.2f} кг.")
    if foods:
        top = foods[0]
        lines.append(f"• «{top['food']}»: {top['with_mean_kg']:+.2f} кг к следующему утру в {top['with_days']} днях с продуктом "
                     f"против {top['without_mean_kg']:+.2f} кг в {top['without_days']} днях без него.")
    if not routine and not foods:
        lines.append("• Для надёжных связей пока мало сопоставимых дней. Продолжай отмечать еду и утренний вес.")
    lines.append("Это наблюдения по дневнику, а не доказательство, что один продукт или интервал сам вызвал изменение веса.")
    await update.message.reply_text("\n".join(lines),reply_markup=main_menu_kb)


async def patterns_command(update, context):
    await recommendations_command(update,context)


async def settings_command(update, context):
    profile = await query(db.load_user_data,update.effective_user.id)
    end = profile.get("trial_ends_at")
    trial = end.astimezone(user_timezone(profile)).strftime("%d.%m.%Y") if end else "ещё не начат"
    await update.message.reply_text(
        f"Цель: {profile.get('goal')}\nГород/пояс: {profile.get('timezone')}\n"
        f"Утро: {profile.get('morning_time')}\nВечерний отчёт: {profile.get('evening_time')}\n"
        f"Тестовый период до: {trial}\n\nАнкета: /profile\nВремя: /reminders 08:00 21:00\n"
        "Отключить напоминания: /pause",reply_markup=main_menu_kb)


async def my_id_command(update, context):
    await update.message.reply_text(f"Твой Telegram ID: {update.effective_user.id}")


async def last_notifications(update, context):
    rows = await query(db.load_last_notifications,update.effective_user.id)
    await update.message.reply_text("\n".join(f"{kind} — {stamp.isoformat()}" for kind,stamp in rows)
                                     or "Уведомлений пока нет.")


async def on_error(update, context):
    logging.getLogger(__name__).error("Update failed: %s",type(context.error).__name__,exc_info=context.error)
    if update is not None and getattr(update,"effective_message",None):
        try:
            await update.effective_message.reply_text("Сейчас действие не завершилось. Попробуй ещё раз.")
        except Exception:
            pass
