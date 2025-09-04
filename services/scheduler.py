from datetime import time, timedelta, timezone, datetime
from services.storage import users_data
from handlers.reminders import morning_weight_request_user, evening_report_user
from domain.tz import get_user_offset

def schedule_user_jobs(app, user_id: int):
    u = users_data.get(user_id, {})
    offset = get_user_offset(u)

    # получаем «системное» время сервера (UTC)
    now_sys = datetime.now(timezone.utc)

    # часы, которые выбрал пользователь
    morning_h = int(u.get("morning_hour", 8))
    evening_h = int(u.get("evening_hour", 21))

    # пересчитываем в серверное время с учётом смещения
    morning_server = (now_sys.replace(hour=morning_h, minute=0, second=0, microsecond=0) - offset).timetz()
    evening_server = (now_sys.replace(hour=evening_h, minute=0, second=0, microsecond=0) - offset).timetz()

    # сначала удаляем старые задачи, чтобы не плодить дубликаты
    for job in app.job_queue.get_jobs_by_name(f"morning_{user_id}"):
        job.schedule_removal()
    for job in app.job_queue.get_jobs_by_name(f"evening_{user_id}"):
        job.schedule_removal()

    # ставим новые задачи
    app.job_queue.run_daily(
        morning_weight_request_user,
        time=morning_server,
        name=f"morning_{user_id}",
        data=user_id,
    )
    app.job_queue.run_daily(
        evening_report_user,
        time=evening_server,
        name=f"evening_{user_id}",
        data=user_id,
    )
