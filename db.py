import os
import psycopg2
from datetime import timedelta
from typing import Dict, Any

# Берём готовую DSN-строку и доверяем psycopg2 разбор параметров (sslmode, таймауты и т.д.)
DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    conn = psycopg2.connect(DATABASE_URL)
    conn.set_client_encoding("UTF8")
    return conn


def create_tables():
    """Создаёт таблицы, если их ещё нет. time хранится как TIMESTAMPTZ."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id       BIGINT PRIMARY KEY,
                name     TEXT,
                phone    TEXT,
                tz       TEXT,
                age      INT,
                gender   TEXT,
                weight   FLOAT,
                height   INT,
                activity INT,
                goal     TEXT
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS weights (
                user_id BIGINT REFERENCES users(id),
                date    DATE NOT NULL,
                weight  FLOAT NOT NULL,
                PRIMARY KEY(user_id, date)
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS meals (
                id        SERIAL PRIMARY KEY,
                user_id   BIGINT REFERENCES users(id),
                time      TIMESTAMPTZ NOT NULL,
                calories  INT,
                protein   FLOAT,
                fat       FLOAT,
                carbs     FLOAT,
                raw       TEXT,
                meal_kind TEXT,
                portion   FLOAT DEFAULT 1.0,
                oil_extra INT   DEFAULT 0
            );
            """
        )
        # Полезный индекс для частых выборок по пользователю и дате/времени
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_meals_user_time
            ON meals (user_id, time);
            """
        )


def save_user_data(user_id: int, data: Dict[str, Any]):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (id, name, phone, tz, age, gender, weight, height, activity, goal)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name     = EXCLUDED.name,
                phone    = EXCLUDED.phone,
                tz       = EXCLUDED.tz,
                age      = EXCLUDED.age,
                gender   = EXCLUDED.gender,
                weight   = EXCLUDED.weight,
                height   = EXCLUDED.height,
                activity = EXCLUDED.activity,
                goal     = EXCLUDED.goal;
            """,
            (
                user_id,
                data.get("name"),
                data.get("phone"),
                str(data.get("tzinfo")),
                data.get("age"),
                data.get("gender"),
                data.get("weight"),
                data.get("height"),
                data.get("activity"),
                data.get("goal"),
            ),
        )


def load_user_data(user_id: int) -> Dict[str, Any]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, phone, tz, age, gender, weight, height, activity, goal
            FROM users
            WHERE id = %s
            """,
            (user_id,),
        )
        row = cur.fetchone()
    if row is None:
        return {}
    keys = ("id", "name", "phone", "tz", "age", "gender", "weight", "height", "activity", "goal")
    return dict(zip(keys, row))


def save_weight(user_id: int, date_obj, weight: float):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO weights (user_id, date, weight)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, date) DO UPDATE SET weight = EXCLUDED.weight
            """,
            (user_id, date_obj, weight),
        )


def save_meal(
    user_id: int,
    time_obj,
    calories: int,
    protein,
    fat,
    carbs,
    raw: str,
    meal_kind: str,
    portion: float = 1.0,
    oil_extra: int = 0,
):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO meals (user_id, time, calories, protein, fat, carbs, raw, meal_kind, portion, oil_extra)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                time_obj,  # aware datetime (tzinfo) разрешён TIMESTAMPTZ
                calories,
                protein,
                fat,
                carbs,
                raw,
                meal_kind,
                portion,
                oil_extra,
            ),
        )


def analyze_user_day(user_id: int, date_obj):
    """Простой совет по режиму за указанный день."""
    with get_connection() as conn, conn.cursor() as cur:
        # Приёмы пищи за день
        cur.execute(
            """
            SELECT time, raw
            FROM meals
            WHERE user_id = %s AND time::date = %s
            ORDER BY time
            """,
            (user_id, date_obj),
        )
        meals = cur.fetchall()

        # Промежутки между приёмами
        time_gaps = []
        for i in range(1, len(meals)):
            gap = (meals[i][0] - meals[i - 1][0]).total_seconds() / 3600.0
            time_gaps.append(gap)

        long_gaps = [g for g in time_gaps if g > 5]
        advice = ""
        if long_gaps:
            advice += "Попробуйте питаться чаще, чтобы уровень энергии был стабильным.\n"

        # Очень грубая эвристика по 'быстрой еде'
        fast_food_keywords = ["фастфуд", "пицца", "бургеры", "кока-кола"]
        bad_meals = [m for m in meals if m[1] and any(w in m[1].lower() for w in fast_food_keywords)]

        # Сравнение веса (сегодня vs вчера)
        cur.execute("SELECT weight FROM weights WHERE user_id = %s AND date = %s", (user_id, date_obj))
        weight_today = cur.fetchone()
        cur.execute(
            "SELECT weight FROM weights WHERE user_id = %s AND date = %s",
            (user_id, date_obj - timedelta(days=1)),
        )
        weight_yesterday = cur.fetchone()

    if weight_today and weight_yesterday and weight_today[0] > weight_yesterday[0] and bad_meals:
        advice += (
            "Вчера вы употребляли продукты, которые могли способствовать набору веса. Будьте внимательны.\n"
        )

    return advice
