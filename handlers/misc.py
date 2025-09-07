from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
from texts import HELP
from services.storage import users_data
from db import save_weight
from domain.tz import now_local

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

    import re
    match = re.search(r"\d+(?:\.\d+)?", raw_text)
    if not match:
        await update.message.reply_text("Пожалуйста, введи вес числом (например, 70.5).")
        return

    weight_val = float(match.group())
    users_data.setdefault(user.id, {})["weight"] = weight_val

    from datetime import date, timedelta
    today = date.today()
    yesterday = today - timedelta(days=1)

    save_weight(user.id, today, weight_val)

    # --- сравнение с вчерашним весом ---
    from db import get_connection, analyze_user_day
    diff_text = ""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT weight FROM weights WHERE user_id=%s AND date=%s", (user.id, yesterday))
        row = cur.fetchone()
    if row:
        prev = row[0]
        diff = round(weight_val - prev, 1)
        if diff > 0:
            diff_text = f"📈 За сутки +{diff} кг."
        elif diff < 0:
            diff_text = f"📉 За сутки {diff} кг."
        else:
            diff_text = "➖ Вес не изменился за сутки."

    # --- анализ по еде ---
    advice = analyze_user_day(user.id, yesterday)

    # --- GPT пожелание ---
    from services.openai_service import get_client
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

    # --- итог ---
    msg = f"✅ Вес {weight_val:.2f} кг сохранён.\n"
    if diff_text:
        msg += diff_text + "\n"
    if advice:
        msg += advice.strip() + "\n"
    if extra_msg:
        msg += "💡 " + extra_msg

    await update.message.reply_text(msg.strip())

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    # Не раскрываем stack в чат, только логируем
    import logging
    logging.getLogger(__name__).exception("Ошибка во время обработки апдейта", exc_info=context.error)
