"""One durable scheduler tick; restart rebuilds due work from SQL."""
import logging
from datetime import datetime
import db
from domain.tz import UTC, user_timezone, parse_clock
from handlers.reminders import send_notification
from services.storage import query

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
        delay = user["interval_hours"]*3600
        if delay <= elapsed < delay+3600:
            due.append(("meal",str(user["last_meal_id"]),local))
    return due

async def scheduler_tick(context):
    users = await query(db.reminder_users)
    instant = datetime.now(UTC)
    for user in users:
        try:
            for kind,key,local in due_reminders(user,instant):
                await send_notification(context.bot,user,kind,key,local)
        except Exception as exc:
            logger.warning("Reminder failed for user %s: %s",user["id"],type(exc).__name__)

async def start_scheduler(application):
    if application.job_queue is None:
        raise RuntimeError("Install python-telegram-bot[job-queue]")
    application.job_queue.run_repeating(scheduler_tick,interval=30,first=1,
        name="durable-reminders",job_kwargs={"max_instances":1,"coalesce":True})
