import os
import httpx
import logging
from dotenv import load_dotenv

# Telegram должен ходить без системных прокси
for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(k, None)
os.environ.setdefault("NO_PROXY", "api.telegram.org")

load_dotenv(encoding="utf-8")
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL_ID = os.getenv("OPENAI_MODEL_ID") or "gpt-4o-mini"
OPENAI_PROXY_URL = os.getenv("OPENAI_PROXY_URL")

def build_http_client_for_openai() -> httpx.Client | None:
    if not OPENAI_PROXY_URL:
        return None
    try:
        transport = httpx.HTTPTransport(proxy=OPENAI_PROXY_URL)
        client = httpx.Client(transport=transport, timeout=60.0)
        logger.info(f"Using OpenAI proxy: {OPENAI_PROXY_URL}")
        return client
    except Exception as e:
        logger.warning(f"Failed to init OpenAI proxy {OPENAI_PROXY_URL}: {e}")
        return None