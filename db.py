import os
import psycopg2
from datetime import date, timedelta

DATABASE_URL = os.getenv("DATABASE_URL")

def get_connection():
    return psycopg2.connect(DATABASE_URL)

def create_tables():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            name TEXT,
            phone TEXT,
            tz TEXT,
            age INT,
            gender TEXT,
            weight FLOAT,
            height INT,
            activity INT,
            goal TEXT
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS weights (
            user_id BIGINT REFERENCES users(id),
            date DATE NOT NULL,
            weight FLOAT NOT NULL,
            PRIMARY KEY(user_id, date)
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS meals (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(id),
            time TIMESTAMP NOT NULL,
            calories INT,
            protein FLOAT,
            fat FLOAT,
            carbs FLOAT,
            raw TEXT,
            meal_kind TEXT,
            portion FLOAT DEFAULT 1.0,
            oil_extra INT DEFAULT 0
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

def save_user_data(user_id, data):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (id, name, phone, tz, age, gender, weight, height, activity, goal)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            phone = EXCLUDED.phone,
            tz = EXCLUDED.tz,
            age = EXCLUDED.age,
            gender = EXCLUDED.gender,
            weight = EXCLUDED.weight,
            height = EXCLUDED.height,
            activity = EXCLUDED.activity,
            goal = EXCLUDED.goal;
    """, (
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
    ))
    conn.commit()
    cur.close()
    conn.close()

def load_user_data(user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, phone, tz, age, gender, weight, height, activity, goal FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row is None:
        return {}
    keys = ("id", "name", "phone", "tz", "age", "gender", "weight", "height", "activity", "goal")
    return dict(zip(keys, row))

def save_weight(user_id, date_obj, weight):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO weights (user_id, date, weight)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, date) DO UPDATE SET weight=EXCLUDED.weight
    """, (user_id, date_obj, weight))
    conn.commit()
    cur.close()
    conn.close()

def save_meal(user_id, time_obj, calories, protein, fat, carbs, raw, meal_kind, portion=1.0, oil_extra=0):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO meals (user_id, time, calories, protein, fat, carbs, raw, meal_kind, portion, oil_extra)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (user_id, time_obj, calories, protein, fat, carbs, raw, meal_kind, portion, oil_extra))
    conn.commit()
    cur.close()
    conn.close()

def analyze_user_day(user_id, date_obj):
    conn = get_connection()
    cur = conn.cursor()

    # Получаем приемы пищи за выбранный день, сортируем по времени
    cur.execute("""
        SELECT time, raw FROM meals
        WHERE user_id = %s AND time::date = %s
        ORDER BY time
    """, (user_id, date_obj))
    meals = cur.fetchall()

    # Анализируем промежутки между приемами
    time_gaps = []
    for i in range(1, len(meals)):
        gap = (meals[i][0] - meals[i-1][0]).total_seconds() / 3600.0  # часы
        time_gaps.append(gap)

    long_gaps = [gap for gap in time_gaps if gap > 5]
    advice = ""
    if long_gaps:
        advice += "Попробуйте питаться чаще, чтобы уровень энергии был стабильным.\n"

    # Анализируем "вредные" продукты
    fast_food_keywords = ['фастфуд', 'пицца', 'бургеры', 'кока-кола']
    bad_meals = [meal for meal in meals if any(word in meal[1].lower() for word in fast_food_keywords)]

    # Сравниваем веса
    cur.execute("""
        SELECT weight FROM weights WHERE user_id = %s AND date = %s
    """, (user_id, date_obj))
    weight_today = cur.fetchone()
    cur.execute("""
        SELECT weight FROM weights WHERE user_id = %s AND date = %s
    """, (user_id, date_obj - timedelta(days=1)))
    weight_yesterday = cur.fetchone()

    if weight_today and weight_yesterday and weight_today[0] > weight_yesterday[0] and bad_meals:
        advice += "Вчера вы употребляли продукты, которые могли способствовать набору веса. Будьте внимательны.\n"

    cur.close()
    conn.close()
    return advice
