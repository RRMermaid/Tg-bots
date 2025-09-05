import json
import logging
import asyncio
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL_ID, build_http_client_for_openai

logger = logging.getLogger(__name__)

OPENAI_SYSTEM_PROMPT = """
Ты — добрый, заботливый нутрициолог. 
Твоя задача — определить калорийность и КБЖУ блюда. 
Ответь строго в JSON формате, например:
{
  "calories": 350,
  "protein_g": 20,
  "fat_g": 10,
  "carbs_g": 45,
  "meal_kind": "plate"
}
"""

_client: OpenAI | None = None

def get_client() -> OpenAI | None:
    global _client
    if _client is not None:
        return _client
    if not OPENAI_API_KEY:
        return None  # тихо, без лишних сообщений
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
            messages=[
                {"role": "system", "content": OPENAI_SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            temperature=0.2,
            max_tokens=200,
            response_format={"type": "json_object"}  # 🔥 гарантируем JSON
        )
        content = resp.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        logger.warning(f"Ошибка при парсинге ответа OpenAI: {e}")
        # Логируем полный ответ для отладки
        try:
            logger.error(f"Полный ответ модели: {resp}")
        except Exception:
            pass
        return {}
