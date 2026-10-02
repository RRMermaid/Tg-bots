import re
import db
from domain.meals import split_meals, manual_nutrition
from keyboards import draft_keyboard
from nutrition import MEAL_SUPPORT
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

def render_draft(draft):
    if draft["state"] == "confirmed":
        return "Эта запись уже сохранена."
    if draft["state"] == "cancelled":
        return "Эта запись отменена. Пришли новое описание."
    lines = ["Проверь запись перед сохранением:"]
    for meal in draft["payload"]:
        stamp = meal["time"][:16].replace("T"," ")
        if meal.get("water_ml"):
            lines.append(f"• {stamp} — вода, {meal['water_ml']} мл")
            continue
        lines.append(f"• {stamp} — {meal['raw']}")
        lines.append(f"  Примерно {meal['calories']} ккал")
        macros = []
        for key,label in (("protein_g","Б"),("fat_g","Ж"),("carbs_g","У")):
            macros.append(f"{label}: {meal[key]:g} г" if meal.get(key) is not None else f"{label}: неизвестно")
        lines.append("  "+" · ".join(macros))
        if meal.get("assumptions"):
            lines.append("  "+meal["assumptions"])
    return "\n".join(lines)

async def record_meal(update, context, profile):
    if not profile["profile_complete"] or not profile.get("timezone"):
        await update.message.reply_text("Сначала настроим анкету и время: /start.")
        return
    uid = profile["id"]
    source = f"tg:{update.effective_chat.id}:{update.message.message_id}"
    existing = await query(db.get_draft,uid,source_key=source)
    if existing:
        await update.message.reply_text(render_draft(existing),
            reply_markup=draft_keyboard(existing["id"]) if existing["state"] == "pending" else None)
        return
    try:
        parts = split_meals(update.message.text,update.message.date,profile)
        payload = []
        for part in parts:
            water = water_amount(part["raw"])
            if water is not None:
                payload.append({"time":part["time"].isoformat(),"raw":part["raw"],"water_ml":water})
                continue
            if re.fullmatch(r"(?:выпил[а]?\s+)?вод[аыу]",part["raw"],re.I):
                raise ValueError("Напиши объём воды: «вода 250 мл».")
            nutrition = manual_nutrition(part["raw"])
            if nutrition is None:
                nutrition = await estimate_meal_nutrition(part["raw"])
            if nutrition is None:
                await update.message.reply_text(
                    "Сейчас не получилось оценить еду. Дневник не изменён. "
                    "Попробуй уточнить состав и порцию или укажи калории: «350 ккал».")
                return
            if not nutrition["is_food"]:
                await update.message.reply_text(
                    "Я рядом 🌿 Для записи еды напиши, что удалось поесть и примерно сколько. "
                    "День не обязан быть идеальным.")
                return
            payload.append({**nutrition,"time":part["time"].isoformat(),"raw":part["raw"]})
        draft = await query(db.save_draft,uid,source,payload)
        await update.message.reply_text(render_draft(draft),reply_markup=draft_keyboard(draft["id"]))
    except ValueError as exc:
        await update.message.reply_text(str(exc))

async def confirm_meal(update, context):
    callback = update.callback_query
    await callback.answer()
    if update.effective_chat is None or update.effective_chat.type != "private":
        return
    uid = update.effective_user.id
    match = re.fullmatch(r"meal:(save|edit|cancel):(\d+)",callback.data or "")
    if not match:
        return
    action, draft_id = match[1],int(match[2])
    draft = await query(db.get_draft,uid,draft_id=draft_id)
    if not draft:
        await callback.message.reply_text("Запись не найдена.")
        return
    if action == "save":
        saved = await query(db.confirm_draft,uid,draft_id)
        if saved:
            await callback.edit_message_reply_markup(reply_markup=None)
            await callback.message.reply_text("Запись сохранена 🌿\n"+MEAL_SUPPORT)
        else:
            await callback.message.reply_text("Запись уже обработана; повторно не добавляю.")
    else:
        cancelled = await query(db.cancel_draft,uid,draft_id)
        if cancelled:
            await callback.edit_message_reply_markup(reply_markup=None)
            await callback.message.reply_text(
                "Пришли уточнённое описание и порцию." if action == "edit" else "Запись отменена.")
        else:
            await callback.message.reply_text("Запись уже обработана.")
