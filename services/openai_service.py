"""One lazy async client, bounded input/output, no transcript or remote memory."""
import json
import logging
import httpx
from openai import AsyncOpenAI
import config
from domain.meals import validate_nutrition
from prompts import MEAL_SYSTEM_PROMPT

logger = logging.getLogger(__name__)
_client = None

def get_client():
    global _client
    if _client is None and config.OPENAI_API_KEY:
        transport = httpx.AsyncClient(
            proxy=config.OPENAI_PROXY_URL or None, trust_env=False,
            timeout=httpx.Timeout(30.0, connect=10.0))
        _client = AsyncOpenAI(api_key=config.OPENAI_API_KEY,
                             base_url=config.OPENAI_BASE_URL or None,
                             http_client=transport, max_retries=1)
    return _client

async def close_client():
    global _client
    if _client is not None:
        await _client.close()
        _client = None

async def estimate_meal_nutrition(text):
    if len(text) > config.MAX_MEAL_CHARS:
        raise ValueError("Meal text too long")
    client = get_client()
    if client is None:
        return None
    try:
        response = await client.chat.completions.create(
            model=config.OPENAI_MODEL_ID,
            messages=[{"role":"system","content":MEAL_SYSTEM_PROMPT},
                      {"role":"user","content":text}],
            temperature=0.2, max_tokens=900,
            response_format={"type":"json_object"})
        choice = response.choices[0]
        if choice.finish_reason != "stop":
            raise ValueError("Incomplete model response")
        return validate_nutrition(json.loads(choice.message.content))
    except Exception as exc:
        # Do not log user's diary, credentials or full model response.
        logger.warning("Nutrition estimation failed: %s", type(exc).__name__)
        return None
