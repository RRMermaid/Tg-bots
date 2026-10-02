"""Single entry point for the independent Nalegke bot."""
import re
import httpx
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.request import HTTPXRequest
import config
import db
from handlers.start_flow import start, edit_profile, change_timezone, handle_flow
from handlers.meals import record_meal, confirm_meal
from handlers.misc import (help_command,cancel,handle_weight,on_error,reminders_command,
                           toggle_reminders,progress_command,patterns_command,last_notifications)
from handlers.analyze import analyze_day_command
from services.storage import query
from services.scheduler import start_scheduler
from services.openai_service import close_client
from logging_config import setup_logging

class TelegramRequest(HTTPXRequest):
    # PTB 20.8 does not expose httpx_kwargs; keep this override version-pinned.
    def _build_client(self):
        return httpx.AsyncClient(**self._client_kwargs, trust_env=False)

async def handle_text(update, context):
    profile = await query(db.ensure_user,update.effective_user.id)
    if await handle_flow(update,context,profile):
        return
    text = (update.message.text or "").strip()
    if re.fullmatch(r"\d+(?:[.,]\d+)?",text):
        await handle_weight(update,context,profile,text)
        return
    await record_meal(update,context,profile)

async def unknown_command(update, context):
    await update.message.reply_text("Такой команды пока нет. Доступные команды: /help.")

async def shutdown(application):
    await close_client()

def build_application(token=None, bot=None):
    builder = ApplicationBuilder().concurrent_updates(False)
    if bot is not None:
        builder = builder.bot(bot)
    else:
        builder = builder.token(token or config.TELEGRAM_BOT_TOKEN)
        builder = builder.request(TelegramRequest(proxy=config.TELEGRAM_PROXY_URL or None))
        builder = builder.get_updates_request(TelegramRequest(proxy=config.TELEGRAM_PROXY_URL or None))
    app = builder.post_init(start_scheduler).post_shutdown(shutdown).build()
    commands = {
        "start":start,"profile":edit_profile,"timezone":change_timezone,"help":help_command,
        "cancel":cancel,"weight":handle_weight,"report":analyze_day_command,
        "analyze_day":analyze_day_command,"reminders":reminders_command,
        "pause":toggle_reminders,"resume":toggle_reminders,"progress":progress_command,
        "patterns":patterns_command,"last_notifications":last_notifications,
    }
    for command,callback in commands.items():
        app.add_handler(CommandHandler(command,callback,filters=filters.ChatType.PRIVATE))
    app.add_handler(CallbackQueryHandler(confirm_meal,pattern=r"^meal:(save|edit|cancel):\d+$"))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.COMMAND,unknown_command))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,handle_text))
    app.add_error_handler(on_error)
    return app

def main():
    setup_logging()
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN in .env")
    db.create_tables()
    with db.single_instance(config.TELEGRAM_BOT_TOKEN):
        build_application().run_polling(allowed_updates=["message","callback_query"],
                                        drop_pending_updates=False,bootstrap_retries=3)

if __name__ == "__main__":
    main()
