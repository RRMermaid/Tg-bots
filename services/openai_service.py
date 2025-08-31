import json
import re
import logging
import asyncio
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL_ID, build_http_client_for_openai

logger = logging.getLogger(__name__)

OPENAI_SYSTEM_PROMPT = """
Ты — добрый, заботливый нутрициолог ... (тот же текст промпта, без изменений)
"""

_client: OpenAI | None = None

def get_client() -> OpenAI | None:
    global _client
    if _client is not None:
        return _client
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY не найден в .env")
        return None
    try:
        http_client = build_http_client_for_openai()
        _client = OpenAI(api_key=OPENAI_API_KEY, http_client=http_client)
        return _client
    except Exception as e:
        logger.error(f"Ошибка инициализации OpenAI: {e}")
        return None

async def estimate_meal_nutrition(text: str) -> dict:
    client = get_client()
    if not client:
        return {}
    try:
        resp = await asyncio.to_thread(
            client.chat.completions.create,
            model=OPENAI_MODEL_ID,
            messages=[{"role": "system", "content": OPENAI_SYSTEM_PROMPT},
                      {"role": "user",   "content": text}],
            temperature=0.2,
            max_tokens=200,
        )
        content = resp.choices[0].message.content
        m = re.search(r"\{.*\}", content, flags=re.S)
        if not m:
            raise ValueError("Не найден JSON в ответе модели")
        data = json.loads(m.group(0))
        if "calories" in data and "meal_kind" in data:
            return data
    except Exception as e:
        logger.warning(f"OpenAI недоступен/ошибка парсинга: {e}")
    return {}
