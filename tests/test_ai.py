import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
import config
from services import openai_service,analysis_service
from prompts import build_evening_prompt
from app import TelegramRequest

def client(content,reason="stop"):
    response = SimpleNamespace(choices=[SimpleNamespace(
        finish_reason=reason,message=SimpleNamespace(content=content))])
    create = AsyncMock(return_value=response)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

async def test_ai_valid_json_and_fixed_budget(monkeypatch):
    fake = client(json.dumps({"is_food":True,"calories":350,"protein_g":None,
                            "fat_g":10,"carbs_g":45,"items":[{"name":"гречка","grams":150}]}))
    monkeypatch.setattr(openai_service,"get_client",lambda:fake)
    result = await openai_service.estimate_meal_nutrition("150 г гречки")
    assert result["calories"] == 350
    args = fake.chat.completions.create.call_args.kwargs
    assert len(args["messages"]) == 2
    assert args["max_tokens"] == 900
    assert args["response_format"] == {"type":"json_object"}
    assert args["model"] == config.OPENAI_MODEL_ID

@pytest.mark.parametrize("text,reason",[("not json","stop"),('{"is_food":true}',"stop"),
                                      ('{"is_food":false}',"length")])
async def test_ai_bad_or_truncated_response_is_not_saved(monkeypatch,text,reason):
    fake = client(text,reason)
    monkeypatch.setattr(openai_service,"get_client",lambda:fake)
    assert await openai_service.estimate_meal_nutrition("еда") is None

async def test_no_key_and_no_network(monkeypatch):
    monkeypatch.setattr(openai_service,"get_client",lambda:None)
    assert await openai_service.estimate_meal_nutrition("еда") is None

async def test_message_limit_prevents_api_call(monkeypatch):
    fake = client("{}")
    monkeypatch.setattr(openai_service,"get_client",lambda:fake)
    with pytest.raises(ValueError):
        await openai_service.estimate_meal_nutrition("x"*1501)
    fake.chat.completions.create.assert_not_called()

def test_report_context_does_not_grow_with_diary():
    day = {"totals":{"meals":10000},"meals":[{"local_time":"12:00","raw":"еда"*500,"calories":350}]*10000}
    text = build_evening_prompt(day,{"logged_days":14,"previous_week":{},"recent_week":{}})
    payload = json.loads(text)
    assert len(payload["recorded_meals"]) == 12
    assert payload["omitted_meals"] == 9988
    assert len(text) <= config.MAX_REPORT_CONTEXT_CHARS

async def test_report_failure_returns_support(monkeypatch):
    fake = client("bad",reason="length")
    monkeypatch.setattr(analysis_service,"get_client",lambda:fake)
    day = {"totals":{"meals":1},"meals":[{"local_time":"12:00","raw":"еда","calories":350}]}
    answer = await analysis_service.analyze_day(day,{})
    assert "отдохнуть" in answer
    args = fake.chat.completions.create.call_args.kwargs
    assert args["max_tokens"] == 450

async def test_empty_day_does_not_call_ai(monkeypatch):
    fake = client("not used")
    monkeypatch.setattr(analysis_service,"get_client",lambda:fake)
    text = await analysis_service.analyze_day({"meals":[]},{})
    assert "нет записей" in text
    fake.chat.completions.create.assert_not_called()

async def test_telegram_client_ignores_global_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY","http://should-never-be-used.invalid:9999")
    request = TelegramRequest()
    assert request._client._trust_env is False
    await request.shutdown()
