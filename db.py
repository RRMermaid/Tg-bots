"""Small synchronous repository, called off the asyncio loop via storage.query."""
import hashlib
import os
from contextlib import contextmanager
from calendar import monthrange
from datetime import datetime, timezone
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

def ensure_user(user_id, username=None, first_name=None):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users(id,telegram_username,telegram_first_name,legacy_user) "
            "VALUES (%s,%s,%s,FALSE) ON CONFLICT(id) DO UPDATE SET "
            "telegram_username=COALESCE(EXCLUDED.telegram_username,users.telegram_username), "
            "telegram_first_name=COALESCE(EXCLUDED.telegram_first_name,users.telegram_first_name)",
            (user_id,username,first_name))
    return load_user_data(user_id)

def load_user_data(user_id):
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM users WHERE id=%s", (user_id,))
        row = cur.fetchone()
    return dict(row) if row else {}

PROFILE_FIELDS = frozenset(("name","phone","timezone","tz_offset","age","gender","weight",
    "target_weight","height","activity","goal","focus_areas","limitations","deficit_percent",
    "calorie_lower","calorie_upper","goal_start_weight","milestones_reached",
    "morning_time","evening_time","interval_hours","reminders_enabled","profile_complete",
    "flow_step","onboarding_version","trial_started_at","trial_ends_at",
    "telegram_username","telegram_first_name"))

def save_user_data(user_id, data):
    keys = [key for key in data if key in PROFILE_FIELDS]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO users(id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
        if keys:
            # Names are exclusively from the fixed allowlist above.
            assignments = ", ".join(f"{key}=%s" for key in keys)
            values = tuple(Json(data[key]) if key == "focus_areas" else data[key] for key in keys)
            cur.execute(f"UPDATE users SET {assignments} WHERE id=%s", values+(user_id,))

def mark_new_user_notified(user_id):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET new_user_notified=TRUE WHERE id=%s", (user_id,))

def add_calendar_months(value, months):
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year,month)[1])
    return value.replace(year=year,month=month,day=day)

def activate_trial(user_id, started_at=None, months=None):
    started_at = started_at or datetime.now(timezone.utc)
    months = months or config.TRIAL_MONTHS
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT trial_started_at,trial_ends_at FROM users WHERE id=%s FOR UPDATE", (user_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError("Unknown user")
        if row["trial_started_at"] is None:
            ends_at = add_calendar_months(started_at,months)
            cur.execute("UPDATE users SET trial_started_at=%s,trial_ends_at=%s WHERE id=%s",
                        (started_at,ends_at,user_id))
            return started_at,ends_at
        return row["trial_started_at"],row["trial_ends_at"]

def access_active(user_id, instant=None):
    instant = instant or datetime.now(timezone.utc)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT (trial_ends_at>%s) OR EXISTS (SELECT 1 FROM access_grants g "
            "WHERE g.user_id=users.id AND g.starts_at<=%s AND (g.ends_at IS NULL OR g.ends_at>%s)) "
            "FROM users WHERE id=%s", (instant,instant,instant,user_id))
        row = cur.fetchone()
        return bool(row and row[0])

def add_access_grant(user_id, kind, starts_at=None, ends_at=None, code=None, details=None):
    starts_at = starts_at or datetime.now(timezone.utc)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO access_grants(user_id,kind,starts_at,ends_at,code,details) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
            (user_id,kind,starts_at,ends_at,code,Json(details or {})))
        return cur.fetchone()[0]

def save_weight(user_id, day, weight):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO weights(user_id,date,weight) VALUES (%s,%s,%s) "
                    "ON CONFLICT(user_id,date) DO UPDATE SET weight=EXCLUDED.weight",
                    (user_id,day,weight))
        cur.execute("UPDATE users SET weight=%s WHERE id=%s", (weight,user_id))

def save_checkin(user_id, day, sleep_hours=None, note=None):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO daily_checkins(user_id,date,sleep_hours,note) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT(user_id,date) DO UPDATE SET "
            "sleep_hours=COALESCE(EXCLUDED.sleep_hours,daily_checkins.sleep_hours), "
            "note=COALESCE(EXCLUDED.note,daily_checkins.note)",
            (user_id,day,sleep_hours,note))

def get_checkin(user_id, day):
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM daily_checkins WHERE user_id=%s AND date=%s", (user_id,day))
        row = cur.fetchone()
        return dict(row) if row else None

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

def save_clarification(user_id, source_key, payload):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO pending_meals(user_id,source_key,payload,state) VALUES (%s,%s,%s,'clarifying') "
            "ON CONFLICT(user_id,source_key) DO NOTHING", (user_id,source_key,Json(payload)))
    return get_draft(user_id,source_key=source_key)

def get_active_draft(user_id, state):
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM pending_meals WHERE user_id=%s AND state=%s ORDER BY id DESC LIMIT 1",
                    (user_id,state))
        row = cur.fetchone()
        return dict(row) if row else None

def update_draft(user_id, draft_id, payload, state):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE pending_meals SET payload=%s,state=%s WHERE user_id=%s AND id=%s",
                    (Json(payload),state,user_id,draft_id))
        return cur.rowcount == 1

def abandon_active_drafts(user_id):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE pending_meals SET state='confirmed' WHERE user_id=%s AND state='editing'", (user_id,))
        cur.execute("UPDATE pending_meals SET state='cancelled' WHERE user_id=%s AND state='clarifying'", (user_id,))

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
                "INSERT INTO meals(user_id,time,calories,protein,fat,carbs,raw,meal_kind,items,estimated,"
                "source_key,reminder_minutes,composition_comment) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(user_id,source_key) DO NOTHING",
                (user_id,stamp,meal["calories"],meal.get("protein_g"),meal.get("fat_g"),
                 meal.get("carbs_g"),meal["raw"],meal["meal_kind"],Json(meal["items"]),
                 meal["estimated"],f'{draft["source_key"]}:{i}',meal.get("reminder_minutes",180),
                 meal.get("comment")))
        cur.execute("UPDATE pending_meals SET state='confirmed' WHERE id=%s", (draft_id,))
        return True

def start_edit_draft(user_id, draft_id):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE pending_meals SET state='confirmed' WHERE user_id=%s AND state='editing'", (user_id,))
        cur.execute("UPDATE pending_meals SET state='editing' WHERE id=%s AND user_id=%s AND state='confirmed'",
                    (draft_id,user_id))
        return cur.rowcount == 1

def replace_draft(user_id, draft_id, payload):
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM pending_meals WHERE id=%s AND user_id=%s FOR UPDATE", (draft_id,user_id))
        draft = cur.fetchone()
        if not draft or draft["state"] != "editing":
            return False
        prefix = draft["source_key"]+":%"
        cur.execute("DELETE FROM meals WHERE user_id=%s AND source_key LIKE %s", (user_id,prefix))
        cur.execute("DELETE FROM water_entries WHERE user_id=%s AND source_key LIKE %s", (user_id,prefix))
        for i, meal in enumerate(payload):
            stamp = datetime.fromisoformat(meal["time"])
            source = f'{draft["source_key"]}:{i}'
            if meal.get("water_ml"):
                cur.execute("INSERT INTO water_entries(user_id,time,ml,source_key) VALUES (%s,%s,%s,%s)",
                            (user_id,stamp,meal["water_ml"],source))
            else:
                cur.execute(
                    "INSERT INTO meals(user_id,time,calories,protein,fat,carbs,raw,meal_kind,items,estimated,"
                    "source_key,reminder_minutes,composition_comment) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (user_id,stamp,meal["calories"],meal.get("protein_g"),meal.get("fat_g"),
                     meal.get("carbs_g"),meal["raw"],meal["meal_kind"],Json(meal["items"]),
                     meal["estimated"],source,meal.get("reminder_minutes",180),meal.get("comment")))
        cur.execute("UPDATE pending_meals SET payload=%s,state='confirmed' WHERE id=%s", (Json(payload),draft_id))
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

def reminder_users(instant=None):
    instant = instant or datetime.now(timezone.utc)
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT u.*, m.id AS last_meal_id, m.time AS last_meal_time, "
            "m.reminder_minutes AS last_meal_reminder_minutes FROM users u "
            "LEFT JOIN LATERAL (SELECT id,time,reminder_minutes FROM meals WHERE user_id=u.id "
            "ORDER BY time DESC,id DESC LIMIT 1) m ON TRUE "
            "WHERE u.profile_complete AND u.timezone IS NOT NULL AND u.reminders_enabled "
            "AND (u.trial_ends_at>%s OR EXISTS (SELECT 1 FROM access_grants g WHERE g.user_id=u.id "
            "AND g.starts_at<=%s AND (g.ends_at IS NULL OR g.ends_at>%s)))", (instant,instant,instant))
        return [dict(row) for row in cur.fetchall()]

def expired_trial_users(instant=None):
    instant = instant or datetime.now(timezone.utc)
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT u.*, EXISTS (SELECT 1 FROM access_grants g WHERE g.user_id=u.id "
            "AND g.starts_at<=%s AND (g.ends_at IS NULL OR g.ends_at>%s)) AS active_grant "
            "FROM users u WHERE u.profile_complete AND u.trial_ends_at IS NOT NULL "
            "AND u.trial_ends_at<=%s", (instant,instant,instant))
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
