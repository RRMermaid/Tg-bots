import os
import requests
import httpx
from openai import OpenAI

api_key = os.getenv("OPENAI_API_KEY", "your_api_key_here")

def test_proxy(proxy_url: str) -> bool:
    """Проверяем, работает ли данный прокси для HTTP-запросов"""
    try:
        proxies = {"http": proxy_url, "https": proxy_url}
        r = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=10)
        print(f"[OK] {proxy_url} -> IP:", r.json())
        return True
    except Exception as e:
        print(f"[FAIL] {proxy_url} -> {e}")
        return False


# Кандидаты: SOCKS5 и HTTP на порту 12334
candidates = [
    "socks5h://127.0.0.1:12334",  # SOCKS5 (нужен PySocks: pip install pysocks)
    "http://127.0.0.1:12334",     # HTTP
]

working_proxy = None
for url in candidates:
    if test_proxy(url):
        working_proxy = url
        break

if not working_proxy:
    print("❌ Не удалось подключиться ни через один вариант прокси.")
else:
    print(f"✅ Используем {working_proxy} для OpenAI")

    # Создаём httpx-клиент с прокси
    http_client = httpx.Client(transport=httpx.HTTPTransport(proxy=working_proxy), timeout=60.0)
    client = OpenAI(api_key=api_key, http_client=http_client)

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": "Привет, проверка через Hiddify"}],
        )
        print("Ответ OpenAI:", response.choices[0].message.content)
    except Exception as e:
        print("Ошибка при вызове OpenAI API:", e)
