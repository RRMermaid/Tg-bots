def calculate_bmr(weight: float, height: int, age: int, gender: str) -> float:
    if gender == "Мужской":
        return 10 * weight + 6.25 * height - 5 * age + 5
    return 10 * weight + 6.25 * height - 5 * age - 161

def calculate_tdee(bmr: float, activity_level: int) -> float:
    factors = {1: 1.2, 2: 1.375, 3: 1.55, 4: 1.725, 5: 1.9}
    return bmr * factors.get(activity_level, 1.2)

def calculate_calorie_range(tdee: float, goal: str) -> tuple[float, float]:
    if goal == "Похудеть":
        upper = tdee
        lower = max(upper - upper * 0.2, upper - 500)
        return lower, upper
    if goal == "Удержать вес":
        return tdee - 100, tdee + 100
    return tdee, tdee + 300
