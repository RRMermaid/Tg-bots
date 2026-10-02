import os
import sys
from pathlib import Path
from urllib.parse import urlparse
import pytest
import db

@pytest.fixture(scope="session")
def postgres_uri(tmp_path_factory):
    uri = os.getenv("TEST_DATABASE_URL")
    if uri:
        if not urlparse(uri).path.endswith("_test"):
            pytest.fail("TEST_DATABASE_URL must point to a dedicated database ending in _test")
        yield uri
        return
    if os.getenv("CI"):
        pytest.fail("SQL integration tests require TEST_DATABASE_URL in CI")
    if sys.platform != "linux" or os.geteuid() == 0:
        pytest.skip("Use TEST_DATABASE_URL for isolated PostgreSQL integration tests")
    import pgserver
    server = pgserver.get_server(Path(tmp_path_factory.mktemp("pg"))/"data",cleanup_mode="delete")
    yield server.get_uri()
    server.cleanup()

@pytest.fixture
def database(postgres_uri, monkeypatch):
    monkeypatch.setenv("DATABASE_URL",postgres_uri)
    db.create_tables()
    with db.get_connection() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE pending_meals, meals, weights, water_entries, notification_claims, notifications, users RESTART IDENTITY CASCADE")
    return db

@pytest.fixture
def profile(database):
    fields = {"name":"Тест","timezone":"Asia/Yekaterinburg","age":34,"gender":"Женский",
              "weight":80.0,"height":165,"activity":2,"goal":"Похудеть",
              "profile_complete":True,"flow_step":None}
    database.save_user_data(42,fields)
    return database.load_user_data(42)

def payload(time="2026-10-02T12:00:00+05:00",raw="гречка"):
    return [{"time":time,"raw":raw,"calories":350,"protein_g":20,"fat_g":10,"carbs_g":45,
             "meal_kind":"meal","items":[{"name":"гречка","grams":150}],"estimated":True}]

@pytest.fixture
def meal_payload():
    return payload()
