"""Configuration only; importing modules never connects to external services."""
import os
from dotenv import load_dotenv

load_dotenv(encoding="utf-8")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL_ID = os.getenv("OPENAI_MODEL_ID", "gpt-4o-mini")
OPENAI_PROXY_URL = os.getenv("OPENAI_PROXY_URL", "")
TELEGRAM_PROXY_URL = os.getenv("TELEGRAM_PROXY_URL", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_ID = int(os.getenv("ADMIN_ID") or "0")
MAX_MESSAGE_CHARS = 4000
MAX_MEALS_PER_MESSAGE = 8
MAX_MEAL_CHARS = 1500
MAX_REPORT_CONTEXT_CHARS = 6000
