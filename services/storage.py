from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# in-memory кэш над БД
users_data: dict[int, dict[str, Any]] = {}

@dataclass
class MealEntry:
    time: datetime
    calories: int
    raw: str
    protein: float | None = None
    fat: float | None = None
    carbs: float | None = None
    meal_kind: str = "plate"
    auto: bool = False
