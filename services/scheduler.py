from datetime import time, timezone
from telegram.ext import ContextTypes
from services.storage import users_data

def schedule_user_jobs(app, user_id: int):
    u = users_data.get(user_id, {})
    tz = u.get("tzinfo") or timezone.utc
    morning_h = int(u.get("morning_hour", 8))
    evening_h = int(u.get("evening_hour", 21))

    for job in app.job_queue.get_jobs_by_name(f"morning_{user_id}"):
        job.schedule_removal()
    for job in app.job_queue.get_jobs_by_name(f"evening_{user_id}"):
        job.schedule_removal()

    from handlers.reminders import morning_weight_request_user, evening_report_user  # локальный импорт, чтобы избежать циклов

    app.job_queue.run_daily(
        morning_weight_request_user,
        time=time(hour=morning_h, minute=0, tzinfo=tz),
        name=f"morning_{user_id}",
        data=user_id,
    )
    app.job_queue.run_daily(
        evening_report_user,
        time=time(hour=evening_h, minute=0, tzinfo=tz),
        name=f"evening_{user_id}",
        data=user_id,
    )
