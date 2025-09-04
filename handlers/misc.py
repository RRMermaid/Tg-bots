from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

from texts import HELP
from services.storage import users_data
from db import (
    save_weight,
    analyze_user_day,
    get_connection,
    load_last_notifications,
)
from domain.tz import now_local
from states import BotState
from config import ADMIN_ID
from services.openai_service import get_client

import re
from datetime import date, timedelta

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP, parse_mode="HTML")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Диалог завершен. Если хотите начать сначала, нажмите /start",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def handle_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    raw_text = (update.message.text or "").replace(",", ".").strip()

    match = re.search(r"\d+(?:\.\d+)?", raw_text)
    if not match:
        await update.message.reply_text("Пожалуйста, введи вес числом (например, 70.5).")
        return BotState.ASK_WEIGHT

    weight_val = float(match.group())
    users_data.setdefault(user.id, {})["weight"] = weight_val
    save_weight(user.id, date.today(), weight_val)

    today = date.today()
    yesterday = today - timedelta(days=1)

    # сравнение веса
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT weight FROM weights WHERE user_id=%s AND date=%s", (user.id, yesterday))
        row = cur.fetchone()
    diff_text = ""
    if row:
        prev = row[0]
        diff = round(weight_val - prev, 1)
        if diff > 0:
            diff_text = f"📈 Изменение за сутки: +{diff} кг."
        elif diff < 0:
            diff_text = f"📉 Изменение за сутки: {diff} кг."
        else:
            diff_text = "➖ Вес не изменился за сутки."

    # анализ по еде
    advice = analyze_user_day(user.id, yesterday)

    # проверяем коридор калорий
    u = users_data.get(user.id, {})
    low, high = u.get("calorie_lower"), u.get("calorie_upper")
    cals_yest = 0
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT SUM(calories) FROM meals WHERE user_id=%s AND time::date=%s",
            (user.id, yesterday),
        )
        row = cur.fetchone()
        if row and row[0]:
            cals_yest = row[0]

    if cals_yest > 0:
        if low is not None and high is not None:
            if cals_yest < low:
                advice += " ⚠️ Вчера ты съел меньше нормы. Это может тормозить жиросжигание.\n"
            elif cals_yest > high:
                advice += " 🍟 Вчера было больше калорий, чем нужно для жиросжигания.\n"
            else:
                advice += " ✅ Вчерашний рацион был в коридоре жиросжигания.\n"

    # === генерируем пожелание от ИИ (опционально) ===
    extra_msg = ""
    client = get_client()
    if client:
        try:
            resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Ты — заботливый фитнес-коуч. Пиши короткие, мотивирующие пожелания."},
                    {"role": "user", "content": f"Сегодня вес {weight_val:.1f} кг. {diff_text or ''} {advice}"}
                ],
                max_tokens=50,
            )
            extra_msg = resp.choices[0].message.content.strip()
        except Exception:
            pass

    # итоговое сообщение
    msg = f"✅ Вес {weight_val:.2f} кг сохранён.\n"
    if diff_text:
        msg += diff_text + "\n"
    if advice:
        msg += advice.strip() + "\n"
    if extra_msg:
        msg += "💡 " + extra_msg

    await update.message.reply_text(msg.strip())
    return BotState.MONITORING

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    # Не раскрываем stack в чат, только логируем
    import logging
    logging.getLogger(__name__).exception("Ошибка во время обработки апдейта", exc_info=context.error)

async def last_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return

    rows = load_last_notifications(10)
    if not rows:
        await update.message.reply_text("Уведомлений пока нет.")
        return

    lines = []
    for uid, kind, sent_at in rows:
        lines.append(f"👤 {uid} | {kind} | {sent_at.strftime('%Y-%m-%d %H:%M')}")

    await update.message.reply_text("\n".join(lines))
    