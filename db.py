"""Small synchronous repository, called off the asyncio loop via storage.query."""
import hashlib
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import psycopg2
from psycopg2.extras import Json, RealDictCursor
import config

@contextmanager
def get_connection():
    dsn = os.getenv("DATABASE_URL") or config.DATABASE_URL
    params = {"connect_timeout": 10, "options": "-c timezone=UTC -c statement_timeout=15000"}
    if not dsn:
        if not os.getenv("PGHOST"):
            raise RuntimeError("Set DATABASE_URL or PGHOST/PGDATABASE/PGUSER/PGPASSWORD")
        params.update({k: os.getenv(v) for k, v in (
            ("host","PGHOST"),("port","PGPORT"),("dbname","PGDATABASE"),
            ("user","PGUSER"),("password","PGPASSWORD")) if os.getenv(v)})
    conn = psycopg2.connect(dsn, **params) if dsn else psycopg2.connect(**params)
    try:
        with conn:
            yield conn
    finally:
        conn.close()

def create_tables():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(728191120)")
        cur.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now())")
        for path in sorted((Path(__file__).parent/"migrations").glob("*.sql")):
            cur.execute("SELECT 1 FROM schema_migrations WHERE name=%s", (path.name,))
            if cur.fetchone():
                continue
            cur.execute(path.read_text(encoding="utf-8"))
            cur.execute("INSERT INTO schema_migrations(name) VALUES (%s)", (path.name,))

def ensure_user(user_id):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO users(id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
    return load_user_data(user_id)

def load_user_data(user_id):
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM users WHERE id=%s", (user_id,))
        row = cur.fetchone()
    return dict(row) if row else {}

PROFILE_FIELDS = frozenset(("name","phone","timezone","tz_offset","age","gender","weight",
    "height","activity","goal","morning_time","evening_time","interval_hours",
    "reminders_enabled","profile_complete","flow_step"))

def save_user_data(user_id, data):
    keys = [key for key in data if key in PROFILE_FIELDS]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO users(id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
        if keys:
            # Names are exclusively from the fixed allowlist above.
            assignments = ", ".join(f"{key}=%s" for key in keys)
            cur.execute(f"UPDATE users SET {assignments} WHERE id=%s",
                        tuple(data[key] for key in keys)+(user_id,))

def save_weight(user_id, day, weight):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO weights(user_id,date,weight) VALUES (%s,%s,%s) "
                    "ON CONFLICT(user_id,date) DO UPDATE SET weight=EXCLUDED.weight",
                    (user_id,day,weight))
        cur.execute("UPDATE users SET weight=%s WHERE id=%s", (weight,user_id))

def get_weights(user_id, start, end):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT date,weight FROM weights WHERE user_id=%s AND date BETWEEN %s AND %s ORDER BY date",
                    (user_id,start,end))
        return cur.fetchall()

def get_draft(user_id, draft_id=None, source_key=None):
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        if draft_id is not None:
            cur.execute("SELECT * FROM pending_meals WHERE user_id=%s AND id=%s", (user_id,draft_id))
        else:
            cur.execute("SELECT * FROM pending_meals WHERE user_id=%s AND source_key=%s", (user_id,source_key))
        row = cur.fetchone()
    return dict(row) if row else None

def save_draft(user_id, source_key, payload):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO pending_meals(user_id,source_key,payload) VALUES (%s,%s,%s) "
                    "ON CONFLICT(user_id,source_key) DO NOTHING",
                    (user_id,source_key,Json(payload)))
    return get_draft(user_id,source_key=source_key)

def cancel_draft(user_id, draft_id):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE pending_meals SET state='cancelled' WHERE id=%s AND user_id=%s AND state='pending'",
                    (draft_id,user_id))
        return cur.rowcount == 1

def confirm_draft(user_id, draft_id):
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM pending_meals WHERE id=%s AND user_id=%s FOR UPDATE", (draft_id,user_id))
        draft = cur.fetchone()
        if not draft or draft["state"] != "pending":
            return False
        for i, meal in enumerate(draft["payload"]):
            stamp = datetime.fromisoformat(meal["time"])
            if stamp.tzinfo is None:
                raise ValueError("Meal time must have a timezone")
            if meal.get("water_ml"):
                cur.execute("INSERT INTO water_entries(user_id,time,ml,source_key) VALUES (%s,%s,%s,%s) "
                            "ON CONFLICT(user_id,source_key) DO NOTHING",
                            (user_id,stamp,meal["water_ml"],f'{draft["source_key"]}:{i}'))
                continue
            cur.execute(
                "INSERT INTO meals(user_id,time,calories,protein,fat,carbs,raw,meal_kind,items,estimated,source_key) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id,source_key) DO NOTHING",
                (user_id,stamp,meal["calories"],meal.get("protein_g"),meal.get("fat_g"),
                 meal.get("carbs_g"),meal["raw"],meal["meal_kind"],Json(meal["items"]),
                 meal["estimated"],f'{draft["source_key"]}:{i}'))
        cur.execute("UPDATE pending_meals SET state='confirmed' WHERE id=%s", (draft_id,))
        return True

def load_meals(user_id, start, end):
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM meals WHERE user_id=%s AND time >= %s AND time < %s ORDER BY time,id",
                    (user_id,start,end))
        return [dict(row) for row in cur.fetchall()]

def load_water(user_id, start, end):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COALESCE(SUM(ml),0) FROM water_entries WHERE user_id=%s AND time >= %s AND time < %s",
                    (user_id,start,end))
        return cur.fetchone()[0]

def reminder_users():
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT u.*, m.id AS last_meal_id, m.time AS last_meal_time FROM users u "
            "LEFT JOIN LATERAL (SELECT id,time FROM meals WHERE user_id=u.id ORDER BY time DESC,id DESC LIMIT 1) m ON TRUE "
            "WHERE u.profile_complete AND u.timezone IS NOT NULL AND u.reminders_enabled")
        return [dict(row) for row in cur.fetchall()]

def claim_notification(user_id, kind, key):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO notification_claims(user_id,kind,dedupe_key) VALUES (%s,%s,%s) "
                    "ON CONFLICT DO NOTHING", (user_id,kind,key))
        return cur.rowcount == 1

def finish_notification(user_id, kind, key, success):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE notification_claims SET status=%s WHERE user_id=%s AND kind=%s AND dedupe_key=%s",
                    ("sent" if success else "failed",user_id,kind,key))
        if success:
            cur.execute("INSERT INTO notifications(user_id,kind) VALUES (%s,%s)", (user_id,kind))

def load_last_notifications(user_id, limit=10):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT kind,sent_at FROM notifications WHERE user_id=%s ORDER BY sent_at DESC LIMIT %s",
                    (user_id,limit))
        return cur.fetchall()

@contextmanager
def single_instance(token):
    """Hold an advisory lock for this Telegram bot for the lifetime of the process."""
    key = int.from_bytes(hashlib.sha256(token.encode()).digest()[:8], "big", signed=True)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (key,))
        if not cur.fetchone()[0]:
            raise RuntimeError("Another Nalegke instance already runs against this database")
        conn.commit()
        yield

if __name__ == "__main__":
    create_tables()
    print("Database migrations applied.")
