from openai import OpenAI
from prompts import build_evening_prompt

client = OpenAI()

def analyze_day(meals: list[str], weight_trend: str = "нет данных") -> str:
    """
    Делает вечерний анализ рациона через GPT
    """
    prompt = build_evening_prompt(meals, weight_trend)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Ты нутрициолог. Объясняй просто и с заботой."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content
