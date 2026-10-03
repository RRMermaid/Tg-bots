import json
from datetime import datetime,timezone,date
from telegram import Update
from telegram.ext import ExtBot
from telegram.request import BaseRequest
from unittest.mock import AsyncMock
import pytest
import app
from handlers import meals
from domain.tz import day_bounds

class TelegramStub(BaseRequest):
    def __init__(self):
        self.sent = []
    async def initialize(self):
        pass
    async def shutdown(self):
        pass
    async def do_request(self,url,method,request_data=None,**kwargs):
        endpoint = url.rsplit("/",1)[-1]
        parameters = request_data.parameters if request_data else {}
        if endpoint == "getMe":
            result = {"id":99999,"is_bot":True,"first_name":"Test","username":"nalegke_test_bot"}
        elif endpoint == "sendMessage":
            self.sent.append(parameters["text"])
            result = {"message_id":len(self.sent),"date":1790960400,
                      "chat":{"id":42,"type":"private"},"text":parameters["text"]}
        else:
            result = True
        return 200,json.dumps({"ok":True,"result":result}).encode()

def text_update(application,text,message_id=1):
    return Update.de_json({"update_id":message_id,"message":{
        "message_id":message_id,"date":int(datetime(2026,10,2,17,tzinfo=timezone.utc).timestamp()),
        "chat":{"id":42,"type":"private"},"from":{"id":42,"is_bot":False,"first_name":"Тест"},
        "text":text,**({"entities":[{"type":"bot_command","offset":0,"length":len(text.split()[0])}]}
                       if text.startswith("/") else {})}},application.bot)

@pytest.fixture
async def telegram_app(database):
    request = TelegramStub()
    bot = ExtBot("123456:FAKE_TOKEN_FOR_OFFLINE_TESTS",request=request,get_updates_request=request)
    application = app.build_application(bot=bot)
    await application.initialize()
    yield application,request
    await application.shutdown()

async def test_numeric_weight_is_not_consumed_as_food(telegram_app,profile,database,monkeypatch):
    application,request = telegram_app
    estimator = AsyncMock(side_effect=AssertionError("Weight must not call GPT"))
    monkeypatch.setattr(meals,"estimate_meal_nutrition",estimator)
    await application.process_update(text_update(application,"80,2"))
    assert database.get_weights(42,date(2026,10,2),date(2026,10,2))[0][1] == 80.2
    estimator.assert_not_called()
    assert "сохранён" in request.sent[-1]

async def test_plain_food_estimated_once_and_saved_automatically(telegram_app,profile,database,monkeypatch):
    application,request = telegram_app
    estimate = {"is_food":True,"calories":350,"protein_g":20,"fat_g":10,"carbs_g":45,
                "items":[{"name":"гречка","grams":150}],"estimated":True,
                "meal_kind":"meal","assumptions":"Порция оценена."}
    estimator = AsyncMock(return_value=estimate)
    monkeypatch.setattr(meals,"estimate_meal_nutrition",estimator)
    update = text_update(application,"150 г гречки",3)
    await application.process_update(update)
    await application.process_update(update)
    estimator.assert_awaited_once()
    draft = database.get_draft(42,source_key="tg:42:3")
    assert draft and draft["state"] == "confirmed"
    start,end = day_bounds(date(2026,10,2),profile)
    assert database.load_meals(42,start,end)[0]["raw"] == "150 г гречки"
    # A fresh app shares no state with the previous app; SQL still prevents duplicates.
    restarted = app.build_application(bot=application.bot)
    assert restarted.user_data == {}
    assert not database.confirm_draft(42,draft["id"])

async def test_manual_input_does_not_call_gpt(telegram_app,profile,database,monkeypatch):
    application,_ = telegram_app
    estimator = AsyncMock(side_effect=AssertionError("No GPT for manual calories"))
    monkeypatch.setattr(meals,"estimate_meal_nutrition",estimator)
    await application.process_update(text_update(application,"350 ккал"))
    estimator.assert_not_called()
    draft = database.get_draft(42,source_key="tg:42:1")
    assert draft["state"] == "confirmed" and draft["payload"][0]["protein_g"] is None

async def test_missing_portion_is_asked_before_ai(telegram_app,profile,database,monkeypatch):
    application,request = telegram_app
    estimator = AsyncMock(side_effect=AssertionError("AI must wait for a portion"))
    monkeypatch.setattr(meals,"estimate_meal_nutrition",estimator)
    await application.process_update(text_update(application,"макароны с котлетой",7))
    estimator.assert_not_called()
    draft = database.get_draft(42,source_key="tg:42:7")
    assert draft["state"] == "clarifying"
    assert "Уточни" in request.sent[-1]

async def test_name_step_keeps_timezone_and_survives_new_application(telegram_app,database):
    application,_ = telegram_app
    database.save_user_data(42,{"timezone":"Asia/Yekaterinburg","flow_step":"name","morning_time":"09:30"})
    await application.process_update(text_update(application,"Руфина"))
    profile = database.load_user_data(42)
    assert profile["timezone"] == "Asia/Yekaterinburg"
    assert profile["morning_time"] == "09:30"
    assert profile["flow_step"] == "contact"
    await application.process_update(text_update(application,"Пропустить",2))
    assert database.load_user_data(42)["flow_step"] == "timezone"

async def test_start_for_existing_user_does_not_reset_profile(telegram_app,profile,database):
    application,_ = telegram_app
    await application.process_update(text_update(application,"/start"))
    saved = database.load_user_data(42)
    assert saved["timezone"] == profile["timezone"] and saved["profile_complete"]
    assert saved["flow_step"] is None

async def test_reminder_settings_saved_with_minutes(telegram_app,profile,database):
    application,_ = telegram_app
    await application.process_update(text_update(application,"/reminders 08:30 21:15 4"))
    saved = database.load_user_data(42)
    assert saved["morning_time"] == "08:30" and saved["evening_time"] == "21:15"

async def test_pause_does_not_disable_diary(telegram_app,profile,database):
    application,_ = telegram_app
    await application.process_update(text_update(application,"/pause"))
    assert not database.load_user_data(42)["reminders_enabled"]
    await application.process_update(text_update(application,"350 ккал",2))
    assert database.get_draft(42,source_key="tg:42:2") is not None

async def test_ai_failure_does_not_create_fake_zero_meal(telegram_app,profile,database,monkeypatch):
    application,request = telegram_app
    monkeypatch.setattr(meals,"estimate_meal_nutrition",AsyncMock(return_value=None))
    await application.process_update(text_update(application,"2 яйца"))
    assert database.get_draft(42,source_key="tg:42:1") is None
    assert "не получилось рассчитать" in request.sent[-1]

async def test_only_one_general_text_handler(telegram_app):
    from telegram.ext import MessageHandler
    application,_ = telegram_app
    general = [h for handlers in application.handlers.values() for h in handlers
               if isinstance(h,MessageHandler) and h.callback == app.handle_text]
    assert len(general) == 1
