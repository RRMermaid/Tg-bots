import re
from datetime import datetime, timedelta

import db
from domain.meals import (basic_nutrition, manual_nutrition, meal_reminder_minutes,
                          split_meals)
from domain.tz import user_timezone
from keyboards import edit_meal_keyboard, main_menu_kb
from services.analysis_service import day_summary
from services.openai_service import estimate_meal_nutrition
from services.storage import query


def water_amount(text):
    match = re.fullmatch(r"(?:выпил[а]?\s+)?вод[аыу]\s+(\d+(?:[.,]\d+)?)\s*(мл|л|ml|l)",text,re.I)
    if not match:
        return None
    ml = float(match[1].replace(",",".")) * (1000 if match[2].lower() in ("л","l") else 1)
    if not 1 <= ml <= 10000:
        raise ValueError("Уточни объём воды в мл или литрах.")
    return round(ml)


def portion_question(raw):
    return (f"Уточни, пожалуйста, порцию для записи «{raw}». Напиши граммы, количество "
            "или понятную меру — например: «250 г», «2 штуки», «4 ложки» или «1 тарелка».")


async def prepare_payload(parts):
    payload = []
    for part in parts:
        raw = part["raw"]
        water = water_amount(raw)
        if water is not None:
            payload.append({"time":part["time"].isoformat(),"raw":raw,"water_ml":water})
            continue
        if re.fullmatch(r"(?:выпил[а]?\s+)?вод[аыу]",raw,re.I):
            raise ValueError("Напиши объём воды: «вода 250 мл».")
        nutrition = manual_nutrition(raw) or basic_nutrition(raw)
        if nutrition is None:
            nutrition = await estimate_meal_nutrition(raw)
        if nutrition is None:
            raise ValueError("Сейчас не получилось рассчитать запись. Уточни состав и порцию или укажи калории.")
        if not nutrition["is_food"]:
            raise ValueError("Напиши, что удалось поесть и примерно сколько.")
        if nutrition.get("needs_clarification"):
            return None,{**part,"question":nutrition.get("clarification_question")}
        nutrition["reminder_minutes"] = meal_reminder_minutes(raw,nutrition.get("meal_kind") or "dense")
        payload.append({**nutrition,"time":part["time"].isoformat(),"raw":raw})
    return payload,None


def meal_lines(meal):
    if meal.get("water_ml"):
        return [f"💧 Вода записана: {meal['water_ml']} мл."]
    macros = []
    for key,label in (("protein_g","Б"),("fat_g","Ж"),("carbs_g","У")):
        macros.append(f"{label} {meal[key]:g} г" if meal.get(key) is not None else f"{label} —")
    lines = [f"🍽 {meal['raw']}",f"Примерно {meal['calories']} ккал · "+" · ".join(macros)]
    if meal.get("comment"):
        lines.append(meal["comment"])
    if meal.get("estimated"):
        assumption = str(meal.get("assumptions") or "").strip().rstrip(".")
        assumption = assumption or "взяты средняя порция и типичный рецепт"
        lines.append(f"Оценка приблизительная: {assumption[0].lower()+assumption[1:]}. Фактические значения могут отличаться.")
    return lines


def minutes_of(clock):
    hour,minute = map(int,clock.split(":"))
    return hour*60+minute


def evening_is_close(profile, next_time):
    local = next_time.astimezone(user_timezone(profile))
    gap = minutes_of(profile["evening_time"]) - (local.hour*60+local.minute)
    return 0 <= gap < 120


async def saved_message(profile, payload, received_at):
    food = [meal for meal in payload if not meal.get("water_ml")]
    lines = ["Запись сохранена 🌿"]
    for meal in payload:
        lines.extend(meal_lines(meal))
    if food:
        latest = max(food,key=lambda meal:meal["time"])
        stamp = datetime.fromisoformat(latest["time"])
        summary = await query(day_summary,profile["id"],stamp.astimezone(user_timezone(profile)).date(),profile)
        upper = profile.get("calorie_upper")
        if upper is not None:
            remaining = round(upper-summary["totals"]["calories"])
            if remaining >= 0:
                lines.append(f"До верхней границы коридора осталось примерно {remaining} ккал.")
            else:
                lines.append(f"Сейчас примерно на {abs(remaining)} ккал выше верхней границы. "
                             "Следующий приём не нужно пропускать — ориентируйся на голод и выбери подходящую порцию.")
        next_time = stamp+timedelta(minutes=latest.get("reminder_minutes",180))
        received_local = received_at.astimezone(user_timezone(profile))
        next_local = next_time.astimezone(user_timezone(profile))
        if next_time > received_at and next_local.date() == received_local.date():
            lines.append("Ориентир следующего приёма — около "+next_local.strftime("%H:%M")+".")
            if evening_is_close(profile,next_time):
                lines.append("До вечернего отчёта останется меньше двух часов, поэтому отдельного напоминания не будет.")
        else:
            lines.append("Это запись за прошедшее время, поэтому новое напоминание по ней не ставлю.")
    return "\n".join(lines)


async def finish_save(update, profile, draft, payload, editing=False):
    if editing:
        saved = await query(db.replace_draft,profile["id"],draft["id"],payload)
    else:
        saved = await query(db.confirm_draft,profile["id"],draft["id"])
    if not saved:
        await update.message.reply_text("Эта запись уже обработана; повторно её не добавляю.")
        return
    await update.message.reply_text(await saved_message(profile,payload,update.message.date),
                                    reply_markup=edit_meal_keyboard(draft["id"]))


async def record_meal(update, context, profile):
    if not profile["profile_complete"] or not profile.get("timezone"):
        await update.message.reply_text("Сначала заполним анкету: /start.")
        return
    uid = profile["id"]
    text = (update.message.text or "").strip()

    # Older versions could leave the user stuck in a portion-clarification state.
    # New entries use an average portion instead, so retire that stale draft.
    clarification = await query(db.get_active_draft,uid,"clarifying")
    if clarification:
        await query(db.update_draft,uid,clarification["id"],clarification["payload"],"cancelled")

    editing = await query(db.get_active_draft,uid,"editing")
    source = f"tg:{update.effective_chat.id}:{update.message.message_id}"
    existing = await query(db.get_draft,uid,source_key=source)
    if existing and existing["state"] == "confirmed":
        await update.message.reply_text("Эта запись уже сохранена.",reply_markup=edit_meal_keyboard(existing["id"]))
        return
    try:
        parts = split_meals(text,update.message.date,profile)
        payload,missing = await prepare_payload(parts)
        if missing:
            question = missing.get("question") or portion_question(missing["raw"])
            if editing or len(parts) > 1:
                await update.message.reply_text(question+" Пришли всю исправленную запись целиком.")
                return
            draft = await query(db.save_clarification,uid,source,[
                {"time":missing["time"].isoformat(),"raw":missing["raw"]}])
            await update.message.reply_text(question)
            return
        if editing:
            await finish_save(update,profile,editing,payload,editing=True)
        else:
            draft = existing or await query(db.save_draft,uid,source,payload)
            await finish_save(update,profile,draft,payload)
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def edit_meal(update, context):
    callback = update.callback_query
    await callback.answer()
    if update.effective_chat is None or update.effective_chat.type != "private":
        return
    match = re.fullmatch(r"meal:edit:(\d+)",callback.data or "")
    if not match:
        return
    if await query(db.start_edit_draft,update.effective_user.id,int(match[1])):
        await callback.message.reply_text(
            "Пришли исправленную запись целиком: название, порцию и при необходимости время.",
            reply_markup=main_menu_kb)
    else:
        await callback.message.reply_text("Эту запись сейчас нельзя изменить.")
