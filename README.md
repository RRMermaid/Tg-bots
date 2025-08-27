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
