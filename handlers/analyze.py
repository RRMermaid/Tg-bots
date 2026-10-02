import db
from domain.tz import now_local
from services.storage import query
from services.analysis_service import daily_report, send_long

async def analyze_day_command(update, context):
    profile = await query(db.load_user_data,update.effective_user.id)
    if not profile.get("profile_complete") or not profile.get("timezone"):
        await update.message.reply_text("Сначала настроим анкету и время: /start.")
        return
    await send_long(update.message,await daily_report(profile["id"],profile,now_local(profile).date()))
