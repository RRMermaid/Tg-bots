from concurrent.futures import ThreadPoolExecutor
from datetime import date,datetime,timedelta,timezone
import pytest
import db
from domain.tz import day_bounds
from services.analysis_service import day_summary,history_summary,food_patterns
from handlers.reminders import send_notification
from types import SimpleNamespace
from unittest.mock import AsyncMock

UTC = timezone.utc

def test_patch_profile_preserves_timezone(database,profile):
    database.save_user_data(42,{"name":"Другое имя"})
    saved = database.load_user_data(42)
    assert saved["timezone"] == "Asia/Yekaterinburg"
    assert saved["morning_time"] == "08:00"

def test_connection_released(database):
    with database.get_connection() as connection:
        assert connection.closed == 0
    assert connection.closed != 0

def test_idempotent_draft_and_confirm(database,profile,meal_payload):
    first = database.save_draft(42,"tg:42:1",meal_payload)
    second = database.save_draft(42,"tg:42:1",meal_payload)
    assert first["id"] == second["id"]
    assert database.confirm_draft(42,first["id"])
    assert not database.confirm_draft(42,first["id"])
    start,end = day_bounds(date(2026,10,2),profile)
    assert len(database.load_meals(42,start,end)) == 1

def test_concurrent_confirm_saves_one_row(database,profile,meal_payload):
    draft = database.save_draft(42,"tg:42:1",meal_payload)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _:database.confirm_draft(42,draft["id"]),range(2)))
    assert sorted(results) == [False,True]
    start,end = day_bounds(date(2026,10,2),profile)
    assert len(database.load_meals(42,start,end)) == 1

def test_another_user_cannot_confirm_or_read(database,profile,meal_payload):
    database.ensure_user(43)
    draft = database.save_draft(42,"tg:42:1",meal_payload)
    assert database.get_draft(43,draft_id=draft["id"]) is None
    assert not database.confirm_draft(43,draft["id"])
    assert database.get_draft(42,draft_id=draft["id"])["state"] == "pending"

def test_failed_batch_rolls_back_all_records(database,profile,meal_payload):
    broken = {**meal_payload[0],"time":"invalid"}
    draft = database.save_draft(42,"tg:42:1",meal_payload+[broken])
    with pytest.raises(ValueError):
        database.confirm_draft(42,draft["id"])
    start,end = day_bounds(date(2026,10,2),profile)
    assert database.load_meals(42,start,end) == []
    assert database.get_draft(42,draft_id=draft["id"])["state"] == "pending"

def test_cancellation_never_adds_meal(database,profile,meal_payload):
    draft = database.save_draft(42,"tg:42:1",meal_payload)
    assert database.cancel_draft(42,draft["id"])
    assert not database.confirm_draft(42,draft["id"])

def test_user_local_day_selected_in_sql(database,profile,meal_payload):
    # UTC evening belongs to the next day in UTC+5.
    entry = {**meal_payload[0],"time":"2026-10-01T21:00:00+00:00"}
    draft = database.save_draft(42,"tg:42:1",[entry])
    database.confirm_draft(42,draft["id"])
    summary = day_summary(42,date(2026,10,2),profile)
    assert summary["totals"]["meals"] == 1
    assert summary["meals"][0]["local_time"] == "02:00"
    assert day_summary(42,date(2026,10,1),profile)["totals"]["meals"] == 0

def test_unknown_macros_not_reported_as_complete(database,profile,meal_payload):
    entry = {**meal_payload[0],"protein_g":None,"items":[],"estimated":False}
    draft = database.save_draft(42,"tg:42:1",[entry])
    database.confirm_draft(42,draft["id"])
    summary = day_summary(42,date(2026,10,2),profile)
    assert summary["totals"]["protein_missing"] == 1

def test_water_does_not_reset_meal_interval(database,profile,meal_payload):
    water = {"time":"2026-10-02T16:00:00+05:00","raw":"вода 250 мл","water_ml":250}
    draft = database.save_draft(42,"tg:42:1",meal_payload+[water])
    database.confirm_draft(42,draft["id"])
    user = database.reminder_users()[0]
    assert user["last_meal_time"].astimezone(timezone(timedelta(hours=5))).hour == 12
    assert day_summary(42,date(2026,10,2),profile)["totals"]["water_ml"] == 250

def test_weight_upsert_and_profile_persist(database,profile):
    database.save_weight(42,date(2026,10,2),80.2)
    database.save_weight(42,date(2026,10,2),80.3)
    assert database.get_weights(42,date(2026,10,1),date(2026,10,3)) == [(date(2026,10,2),80.3)]
    assert database.load_user_data(42)["weight"] == 80.3

def test_trial_and_future_access_grants(database,profile):
    before = datetime(2026,12,31,tzinfo=UTC)
    after = datetime(2027,1,2,tzinfo=UTC)
    assert database.access_active(42,before)
    assert not database.access_active(42,after)
    database.add_access_grant(42,"gift",starts_at=after,ends_at=after+timedelta(days=30))
    assert database.access_active(42,after+timedelta(days=1))
    expired = database.expired_trial_users(after+timedelta(days=1))
    assert len(expired) == 1 and expired[0]["active_grant"] is True

def test_edit_replaces_instead_of_duplicating(database,profile,meal_payload):
    draft = database.save_draft(42,"tg:42:edit",meal_payload)
    assert database.confirm_draft(42,draft["id"])
    assert database.start_edit_draft(42,draft["id"])
    replacement = [{**meal_payload[0],"raw":"рис","calories":300,
                    "items":[{"name":"рис","grams":150}]}]
    assert database.replace_draft(42,draft["id"],replacement)
    start,end = day_bounds(date(2026,10,2),profile)
    meals = database.load_meals(42,start,end)
    assert len(meals) == 1 and meals[0]["raw"] == "рис" and meals[0]["calories"] == 300

def test_partial_diary_and_short_weight_history_are_not_overinterpreted(database,profile,meal_payload):
    draft = database.save_draft(42,"tg:42:1",meal_payload)
    database.confirm_draft(42,draft["id"])
    database.save_weight(42,date(2026,10,2),80)
    stats = history_summary(42,date(2026,10,2),profile)
    assert stats["logged_days"] == 1
    assert stats["recent_week"]["average_weight"] is None
    assert food_patterns(42,date(2026,10,2),profile) == []

def test_food_associations_require_comparison_days(database,profile,meal_payload):
    base = date(2026,9,25)
    for i in range(7):
        database.save_weight(42,base+timedelta(days=i),80-0.1*i)
    for i in range(6):
        stamp = datetime(2026,9,25,12,tzinfo=UTC)+timedelta(days=i)
        food = "шаурма" if i%2 == 0 else "гречка"
        entry = {**meal_payload[0],"time":stamp.isoformat(),"items":[{"name":food,"grams":300}]}
        draft = database.save_draft(42,f"tg:42:{i}",[entry])
        database.confirm_draft(42,draft["id"])
    patterns = food_patterns(42,date(2026,10,2),profile)
    assert len(patterns) == 2
    assert patterns[0]["with_days"] == patterns[0]["without_days"] == 3

def test_notification_claim_survives_restart_and_is_concurrent(database,profile):
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _:database.claim_notification(42,"morning","2026-10-02"),range(4)))
    assert claims.count(True) == 1
    assert not database.claim_notification(42,"morning","2026-10-02")
    assert database.claim_notification(42,"morning","2026-10-03")

async def test_notification_network_failure_not_repeated(database,profile):
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=TimeoutError))
    instant = datetime(2026,10,2,8,tzinfo=timezone(timedelta(hours=5)))
    with pytest.raises(TimeoutError):
        await send_notification(bot,profile,"morning","2026-10-02",instant)
    assert not await send_notification(bot,profile,"morning","2026-10-02",instant)
    assert bot.send_message.call_count == 1
    with db.get_connection() as conn,conn.cursor() as cur:
        cur.execute("SELECT status FROM notification_claims")
        assert cur.fetchone()[0] == "failed"

def test_single_instance_lock_rejects_second_process(database):
    with database.single_instance("FAKE_TEST_TOKEN"):
        with pytest.raises(RuntimeError):
            with database.single_instance("FAKE_TEST_TOKEN"):
                pytest.fail("second instance acquired the lock")
    with database.single_instance("FAKE_TEST_TOKEN"):
        pass

def test_additive_migration_keeps_legacy_data(database):
    with database.get_connection() as conn,conn.cursor() as cur:
        cur.execute("DROP TABLE schema_migrations,daily_checkins,access_grants,notification_claims,"
                    "water_entries,pending_meals,notifications,meals,weights,users CASCADE")
        cur.execute("CREATE TABLE users(id BIGINT PRIMARY KEY,name TEXT,phone TEXT,tz_offset INT DEFAULT 0,age INT,gender TEXT,weight FLOAT,height INT,activity INT,goal TEXT)")
        cur.execute("CREATE TABLE meals(id SERIAL PRIMARY KEY,user_id BIGINT REFERENCES users(id),time TIMESTAMPTZ NOT NULL,calories INT,protein FLOAT,fat FLOAT,carbs FLOAT,raw TEXT,meal_kind TEXT,portion FLOAT DEFAULT 1,oil_extra INT DEFAULT 0)")
        cur.execute("INSERT INTO users VALUES(42,'Legacy',NULL,300,34,'Женский',80,165,2,'Похудеть')")
        cur.execute("INSERT INTO meals(user_id,time,calories,raw) VALUES(42,'2026-10-02T12:00:00+05:00',350,'старый дневник')")
    database.create_tables()
    database.create_tables()
    profile = database.load_user_data(42)
    assert profile["name"] == "Legacy" and profile["profile_complete"]
    assert profile["timezone"] is None
    with database.get_connection() as conn,conn.cursor() as cur:
        cur.execute("SELECT calories,raw FROM meals")
        assert cur.fetchone() == (350,"старый дневник")
