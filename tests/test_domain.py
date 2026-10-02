from datetime import date, datetime, timezone
import math
import pytest
from domain.tz import parse_tz,timezone_name,day_bounds,parse_clock
from domain.meals import split_meals,validate_nutrition,manual_nutrition
from handlers.start_flow import numeric
from services.scheduler import due_reminders

UTC = timezone.utc

@pytest.mark.parametrize("text,expected",[
    ("Тюмень","Asia/Yekaterinburg"),("Москва","Europe/Moscow"),
    ("Asia/Yekaterinburg","Asia/Yekaterinburg"),("UTC+5","UTC+05:00"),
    ("UTC-03:30","UTC-03:30"),("Europe/Berlin","Europe/Berlin")])
def test_timezone_roundtrip(text,expected):
    assert timezone_name(parse_tz(text)) == expected
    assert parse_tz(expected) is not None

@pytest.mark.parametrize("text",["09:30","UTC+25","UTC+14:30","UTC-3:99","Atlantis",""])
def test_invalid_timezone(text):
    assert parse_tz(text) is None

@pytest.mark.parametrize("day,hours",[(date(2026,3,29),23),(date(2026,10,25),25)])
def test_day_bounds_respect_dst(day,hours):
    start,end = day_bounds(day,{"timezone":"Europe/Berlin"})
    assert (end-start).total_seconds() == hours*3600

def test_local_day_crosses_utc_date():
    start,end = day_bounds(date(2026,10,2),{"timezone":"Asia/Yekaterinburg"})
    assert start == datetime(2026,10,1,19,tzinfo=UTC)
    assert end == datetime(2026,10,2,19,tzinfo=UTC)

@pytest.mark.parametrize("text",["24:00","8:99","abc","-1:30"])
def test_invalid_clock(text):
    with pytest.raises(ValueError):
        parse_clock(text)

def test_untimed_food_uses_message_time():
    received = datetime(2026,10,1,22,30,tzinfo=UTC)
    parts = split_meals("два яйца",received,{"timezone":"Asia/Yekaterinburg"})
    assert parts[0]["time"].date() == date(2026,10,2)
    assert parts[0]["time"].hour == 3

def test_multiple_meals_and_yesterday():
    received = datetime(2026,10,2,17,tzinfo=UTC)
    parts = split_meals("вчера 09:00 яйца; 13:00 гречка",received,{"timezone":"Asia/Yekaterinburg"})
    assert [p["raw"] for p in parts] == ["яйца","гречка"]
    assert all(p["time"].date() == date(2026,10,1) for p in parts)

@pytest.mark.parametrize("text",["25:00 яйца","23:00 яйца","9:00","еда 9:00 яйца","x"*4001,
                                 "вчера яйца"," ".join(f"{h}:00 яйца" for h in range(9))])
def test_invalid_meal_input(text):
    with pytest.raises(ValueError):
        split_meals(text,datetime(2026,10,2,17,tzinfo=UTC),{"timezone":"Asia/Yekaterinburg"})

def sample():
    return {"is_food":True,"calories":350,"protein_g":20,"fat_g":10,"carbs_g":45,
            "items":[{"name":"Гречка","grams":150}]}

@pytest.mark.parametrize("field,value",[
    ("calories",-1),("calories",True),("calories","350"),("protein_g",math.nan),
    ("carbs_g",math.inf),("calories",20001),("is_food","yes"),("items",{})])
def test_invalid_model_data_rejected(field,value):
    data = sample()
    data[field] = value
    with pytest.raises(ValueError):
        validate_nutrition(data)

def test_unknown_macros_stay_unknown():
    data = sample()
    data["protein_g"] = None
    assert validate_nutrition(data)["protein_g"] is None
    assert manual_nutrition("350 ккал")["fat_g"] is None

def test_half_kilo_halva_is_recordable():
    data = sample()
    data.update(calories=2500,items=[{"name":"Халва","grams":500}])
    parsed = validate_nutrition(data)
    assert parsed["items"] == [{"name":"халва","grams":500.0}]
    assert parsed["calories"] == 2500

def test_negative_manual_calories_rejected():
    with pytest.raises(ValueError):
        manual_nutrition("-350 ккал")

@pytest.mark.parametrize("text",["nan","inf","0","-80","4000"])
def test_invalid_weight(text):
    with pytest.raises(ValueError):
        numeric(text,20,400)

def user(**values):
    return {"id":42,"timezone":"Asia/Yekaterinburg","profile_complete":True,
            "reminders_enabled":True,"morning_time":"08:00","evening_time":"21:00",
            "interval_hours":4,**values}

def test_morning_follows_user_clock():
    due = due_reminders(user(),datetime(2026,10,2,3,5,tzinfo=UTC))
    assert due[0][:2] == ("morning","2026-10-02")
    assert not due_reminders(user(),datetime(2026,10,2,7,tzinfo=UTC))

def test_food_reminder_and_quiet_hours():
    stamp = datetime(2026,10,2,7,tzinfo=UTC)
    u = user(last_meal_time=stamp,last_meal_id=5)
    due = due_reminders(u,stamp.replace(hour=11))
    assert ("meal","5") in [entry[:2] for entry in due]
    assert not due_reminders(u,stamp.replace(hour=20))

@pytest.mark.parametrize("values",[{"reminders_enabled":False},{"timezone":None},{"profile_complete":False}])
def test_disabled_or_unconfirmed_never_notified(values):
    assert due_reminders(user(**values),datetime(2026,10,2,3,5,tzinfo=UTC)) == []
