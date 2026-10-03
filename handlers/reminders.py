"""Notification content. Scheduling and durable deduplication live separately."""
from nutrition import MORNING_VARIANTS, MEAL_REMINDER
from services.analysis_service import daily_report
from services.storage import query
import db

async def notification_text(kind, user, local_now):
    if kind == "morning":
        template = MORNING_VARIANTS[local_now.date().toordinal()%len(MORNING_VARIANTS)]
        return template.format(name=user.get("name") or "друг")
    if kind == "meal":
        return MEAL_REMINDER
    return await daily_report(user["id"],user,local_now.date())

async def send_notification(bot, user, kind, key, local_now):
    claimed = await query(db.claim_notification,user["id"],kind,key)
    if not claimed:
        return False
    success = False
    try:
        text = await notification_text(kind,user,local_now)
        # Claim covers the whole report even if it needs several Telegram messages.
        while len(text) > 3800:
            split = text.rfind("\n",0,3800)
            if split < 1:
                split = 3800
            await bot.send_message(chat_id=user["id"],text=text[:split])
            text = text[split:].lstrip("\n")
        if text:
            await bot.send_message(chat_id=user["id"],text=text)
        success = True
        return True
    finally:
        # Ambiguous network failures are NOT retried automatically, to avoid duplicate sends.
        await query(db.finish_notification,user["id"],kind,key,success)
