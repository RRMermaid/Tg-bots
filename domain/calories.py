ACTIVITY_FACTORS = {1: 1.2, 2: 1.375, 3: 1.462, 4: 1.55}


def calculate_bmr(weight: float, height: int, age: int, gender: str) -> float:
    if gender == "Мужской":
        return 10 * weight + 6.25 * height - 5 * age + 5
    return 10 * weight + 6.25 * height - 5 * age - 161

def calculate_tdee(bmr: float, activity_level: int) -> float:
    return bmr * ACTIVITY_FACTORS.get(activity_level, 1.2)

def calculate_calorie_range(tdee: float, goal: str, deficit_percent: int = 10) -> tuple[float, float]:
    if goal == "Похудеть":
        if deficit_percent not in (10, 20):
            raise ValueError("Дефицит должен быть 10% или 20%.")
        standard_upper = tdee * 0.9
        lower = standard_upper - 400
        upper = tdee * (1 - deficit_percent / 100)
        # With extremely high expenditure the two user rules can cross. Keep a valid
        # corridor without moving the chosen upper boundary.
        lower = min(lower, upper)
        return lower, upper
    if goal == "Удержать вес":
        return tdee - 100, tdee + 100
    return tdee, tdee + 300


def calorie_corridor(profile: dict, weight: float | None = None) -> tuple[int, int]:
    current_weight = float(weight if weight is not None else profile["weight"])
    bmr = calculate_bmr(current_weight, int(profile["height"]), int(profile["age"]), profile["gender"])
    tdee = calculate_tdee(bmr, int(profile["activity"]))
    low, high = calculate_calorie_range(tdee, profile["goal"], int(profile.get("deficit_percent") or 10))
    return round(low), round(high)


def reached_milestones(start_weight: float, current_weight: float, goal: str) -> int:
    if goal == "Похудеть":
        return max(0, int((start_weight - current_weight) // 5))
    if goal == "Набрать массу":
        return max(0, int((current_weight - start_weight) // 5))
    return 0
