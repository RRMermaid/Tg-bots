import os
import httpx
from openai import OpenAI, DefaultHttpxClient

api_key = os.getenv("OPENAI_API_KEY", "your_api_key_here")  # поставьте ваш ключ здесь или в env

proxy_url = "http://77.110.99.102:12334"  # замените на адрес вашего прокси

http_client = DefaultHttpxClient(proxy=proxy_url)

client = OpenAI(api_key=api_key, http_client=http_client)

try:
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": "Привет, тест через прокси"}],
    )
    print("Ответ:", response.choices[0].message.content)
except Exception as e:
    print("Ошибка при вызове OpenAI API:", e)
