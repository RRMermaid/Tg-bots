# test_openai_proxy.py
import os
import requests
import httpx
from openai import OpenAI
from dotenv import load_dotenv

# 1) Загружаем .env из текущей папки
load_dotenv()

API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    raise RuntimeError("❌ OPENAI_API_KEY не найден. Проверь .env и запуск скрипта из корня проекта.")

# 2) Быстрая проверка формата ключа (не критично, но полезно)
if not (API_KEY.startswith("sk-") and len(API_KEY) > 20):
    print("⚠️ Похоже, ключ выглядит необычно. Убедись, что в .env указан реальный ключ: OPENAI_API_KEY=sk-...")

def test_proxy_reachable(proxy_url: str) -> bool:
    """Проверяем, доступен ли прокси для обычного HTTP-запроса (наружный IP)."""
    try:
        proxies = {"http": proxy_url, "https": proxy_url}
        r = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=10)
        r.raise_for_status()
        print(f"[OK] {proxy_url} -> IP:", r.json())
        return True
    except Exception as e:
        print(f"[FAIL] {proxy_url} -> {e}")
        return False

def make_httpx_client(proxy_url: str) -> httpx.Client:
    """Создаёт httpx-клиент через HTTPTransport с прокси (современный синтаксис httpx)."""
    transport = httpx.HTTPTransport(proxy=proxy_url)  # ключевой момент: proxy в транспорт
    return httpx.Client(transport=transport, timeout=60.0)

def main():
    # 3) Пробуем оба варианта на 12334: сначала SOCKS5, потом HTTP
    candidates = [
        "socks5h://127.0.0.1:12334",  # требует httpx[socks]
        "http://127.0.0.1:12334",
    ]

    working_proxy = None
    for url in candidates:
        if test_proxy_reachable(url):
            working_proxy = url
            break

    if not working_proxy:
        print("❌ Не удалось подключиться ни через SOCKS5, ни через HTTP-прокси на 127.0.0.1:12334.")
        print("   Проверь, что клиент (Hiddify и т.п.) запущен и порт действительно открыт.")
        return

    print(f"✅ Используем {working_proxy} для OpenAI")

    # 4) httpx-клиент с прокси
    http_client = make_httpx_client(working_proxy)
    client = OpenAI(api_key=API_KEY, http_client=http_client)

    try:
        # возьми актуальную модель; если у тебя в .env есть OPENAI_MODEL_ID — можешь прочитать оттуда
        model = os.getenv("OPENAI_MODEL_ID", "gpt-4o-mini")
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Привет! Проверка через локальный прокси."}],
        )
        print("✅ Ответ OpenAI:", resp.choices[0].message.content)
    except Exception as e:
        print("❌ Ошибка при вызове OpenAI API:", e)
        print("   Частые причины: неверный OPENAI_API_KEY, блокировка трафика прокси, или модель недоступна.")

if __name__ == "__main__":
    main()
