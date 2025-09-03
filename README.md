# Nalegke Bot
Телеграм-бот для учёта калорий и контроля питания. Использует OpenAI API для оценки КБЖУ и напоминания о приёмах пищи.

## 🚀 Установка
Клонируйте репозиторий и перейдите в папку проекта:
```bash
git clone https://github.com/твоя-ссылка-на-репозиторий.git
cd Tg-bots
```

Создайте и активируйте виртуальное окружение:
```bash
python -m venv venv
.\venv\Scripts\activate    # Windows PowerShell
source venv/bin/activate   # Linux/macOS
```

Установите зависимости:
```bash
pip install -r requirements.txt
```

## ⚙️ Настройки
Создайте файл `.env` в корне проекта и добавьте туда свои ключи:
```env
TELEGRAM_BOT_TOKEN=твой_токен_бота
OPENAI_API_KEY=твой_api_ключ_openai
OPENAI_MODEL_ID=gpt-4o-mini
```

Если используете прокси (например, Hiddify):
```env
HTTP_PROXY=socks5h://127.0.0.1:12334
```

## ▶️ Запуск
```bash
python Nalegke-bot.py
```

## 📱 Команды бота
- `/start` — начало работы и ввод данных профиля  
- `/cancel` — завершение диалога  
- Ввод еды текстом: `200 гречки`, `350 ккал` и т.п.  
- Автоматическая оценка КБЖУ через OpenAI

📖 Документация по проекту Telegram-бота «Налегке»

Ниже приведена структура проекта с пояснениями по каждому файлу, а также список функций и их назначение.

📁 Корень проекта
Nalegke-bot.py

Главный запускатель бота.

main() — запускает приложение Telegram, настраивает ConversationHandler, регистрирует обработчики команд (/start, /help, /analyze_day), запускает polling.

config.py

Настройки окружения и OpenAI клиента.

build_http_client_for_openai() — возвращает httpx-клиент с прокси для OpenAI, если задан OPENAI_PROXY_URL.

db.py

Работа с PostgreSQL.

get_connection() — создаёт подключение к базе.

create_tables() — создаёт таблицы users, weights, meals.

save_user_data(user_id, data) — сохраняет/обновляет профиль пользователя.

load_user_data(user_id) — загружает профиль пользователя.

save_weight(user_id, date_obj, weight) — сохраняет вес за дату.

save_meal(...) — сохраняет приём пищи (калории, БЖУ, время, текст).

analyze_user_day(user_id, date_obj) — анализирует день: интервалы между приёмами пищи, «вредная еда», изменения веса.

nutrition.py

Справочник по питанию и психологии.

nutrition_blocks — словарь с текстовыми блоками (основы питания, режим, тяга к сладкому, психология).

prompts.py

Генерация промптов для OpenAI.

build_evening_prompt(meals, weight_trend) — формирует подробный текстовый запрос к GPT для анализа дня.

states.py

Состояния бота (ConversationHandler).

class BotState(IntEnum) — набор состояний (регистрация, ввод данных, мониторинг).

texts.py

Сообщения для пользователя.

HELLO — приветствие.

ASK_LOCAL_TIME — просьба ввести текущее время.

HELP — справка по функциям бота.

logging_config.py

Логирование.

setup_logging() — включает логирование уровня INFO, пишет в bot.log и консоль.

📁 handlers (обработчики)
analyze.py

analyze_day_command(update, context) — команда /analyze_day: получает еду и тренд веса из БД, вызывает сервис анализа, отправляет отчёт.

meals.py

record_meal(update, context) — обработка текста про еду:

если указаны калории → записывает вручную;

если нет → отправляет в GPT, получает калории и БЖУ;

сохраняет в БД;

ставит напоминание о следующем приёме пищи.

misc.py

help_command(update, context) — выводит справку.

cancel(update, context) — завершает диалог, убирает клавиатуру.

handle_weight(update, context) — сохраняет вес.

on_error(update, context) — логирует ошибки.

reminders.py

Фоновые напоминания:

reminder_4h(context) — напомнить покушать через 4 часа.

morning_weight_request_user(context) — запросить вес утром.

evening_report_user(context) — подвести итоги дня (калории, БЖУ, советы).

start_flow.py

Пошаговая регистрация:

start() — начало, приветствие.

handle_contact_or_skip() — обработка контакта или «пропустить».

handle_local_time() — сохраняет смещение часового пояса.

handle_morning_hour() — выбор времени утреннего отчёта.

handle_evening_hour() — выбор времени вечернего отчёта.

ask_gender() — спрашивает пол.

ask_age() — спрашивает возраст.

ask_weight() — спрашивает вес.

ask_height() — спрашивает рост.

ask_activity() — спрашивает уровень активности.

ask_goal() — спрашивает цель (похудеть, удержать, набрать).

show_calorie_corridor() — считает BMR, TDEE, диапазон калорий, сохраняет в БД.

📁 services
analysis_service.py

analyze_day(meals, weight_trend) — генерирует промпт и вызывает GPT для анализа дневного рациона.

openai_service.py

get_client() — инициализирует OpenAI-клиент с прокси.

estimate_meal_nutrition(text) — GPT оценивает текст про еду, возвращает JSON с калориями и БЖУ.

scheduler.py

schedule_user_jobs(app, user_id) — ставит ежедневные задачи:

утром запрос веса,

вечером итог дня.

storage.py

users_data — глобальный кэш данных пользователей (dict).

class MealEntry — dataclass для хранения записи приёма пищи (время, калории, БЖУ, тип блюда).

📁 domain
calories.py

calculate_bmr(weight, height, age, gender) — считает базовый обмен (формула Mifflin-St Jeor).

calculate_tdee(bmr, activity_level) — энергозатраты с учётом активности.

calculate_calorie_range(tdee, goal) — диапазон калорий в зависимости от цели.

tz.py

parse_tz(text) — разбирает строку в timezone (UTC+3, Europe/Moscow).

now_local(tzinfo) — возвращает текущее время в указанной зоне.