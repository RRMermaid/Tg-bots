"""One durable scheduler tick; restart rebuilds due work from SQL."""
import logging
from datetime import datetime, timedelta
import config
import db
from domain.tz import UTC, user_timezone, parse_clock
from handlers.reminders import send_notification
from services.storage import query
from texts import TRIAL_ENDED

logger = logging.getLogger(__name__)

def due_reminders(user, instant):
    if not user.get("profile_complete") or not user.get("timezone") or not user.get("reminders_enabled"):
        return []
    local = instant.astimezone(user_timezone(user))
    def minutes(clock):
        hh, mm = map(int,parse_clock(clock).split(":"))
        return hh*60+mm
    clock = local.hour*60+local.minute
    morning = minutes(user["morning_time"])
    evening = minutes(user["evening_time"])
    due = []
    date_key = local.date().isoformat()
    if 0 <= clock-morning < 15:
        due.append(("morning",date_key,local))
    if 0 <= clock-evening < 30:
        due.append(("evening",date_key,local))
    stamp = user.get("last_meal_time")
    if stamp and user.get("last_meal_id") and morning <= clock < evening:
        elapsed = (instant-stamp).total_seconds()
        delay = (user.get("last_meal_reminder_minutes") or 180)*60
        if delay <= elapsed < delay+3600:
            meal_due = (stamp+timedelta(seconds=delay)).astimezone(user_timezone(user))
            meal_clock = meal_due.hour*60+meal_due.minute
            # If the suggested meal is less than two hours before the evening report,
            # the user asked to skip another prompt and wait for the full report.
            if meal_due.date() != local.date() or not (0 <= evening-meal_clock < 120):
                due.append(("meal",str(user["last_meal_id"]),local))
    return due


async def send_trial_expirations(bot, instant):
    users = await query(db.expired_trial_users,instant)
    for user in users:
        key = user["trial_ends_at"].isoformat()
        if await query(db.claim_notification,user["id"],"trial_ended_user",key):
            success = False
            try:
                await bot.send_message(chat_id=user["id"],text=TRIAL_ENDED)
                success = True
            finally:
                await query(db.finish_notification,user["id"],"trial_ended_user",key,success)
        if config.ADMIN_ID and await query(db.claim_notification,user["id"],"trial_ended_admin",key):
            success = False
            try:
                username = f"@{user['telegram_username']}" if user.get("telegram_username") else "без username"
                await bot.send_message(chat_id=config.ADMIN_ID,text=(
                    "Завершился тестовый период пользователя «Налегке»:\n"
                    f"{user.get('name') or user.get('telegram_first_name') or 'Без имени'} · {username} · ID {user['id']}"))
                success = True
            finally:
                await query(db.finish_notification,user["id"],"trial_ended_admin",key,success)

async def scheduler_tick(context):
    instant = datetime.now(UTC)
    users = await query(db.reminder_users,instant)
    for user in users:
        try:
            for kind,key,local in due_reminders(user,instant):
                await send_notification(context.bot,user,kind,key,local)
        except Exception as exc:
            logger.warning("Reminder failed for user %s: %s",user["id"],type(exc).__name__)
    try:
        await send_trial_expirations(context.bot,instant)
    except Exception as exc:
        logger.warning("Trial expiration notification failed: %s",type(exc).__name__)

async def start_scheduler(application):
    if application.job_queue is None:
        raise RuntimeError("Install python-telegram-bot[job-queue]")
    application.job_queue.run_repeating(scheduler_tick,interval=30,first=1,
        name="durable-reminders",job_kwargs={"max_instances":1,"coalesce":True})
