from telegram import ReplyKeyboardMarkup, KeyboardButton

gender_kb = ReplyKeyboardMarkup([["Мужской", "Женский"]], one_time_keyboard=True, resize_keyboard=True)
activity_kb = ReplyKeyboardMarkup([["1", "2", "3", "4", "5"]], one_time_keyboard=True, resize_keyboard=True)
goal_kb = ReplyKeyboardMarkup([["Похудеть", "Удержать вес", "Набрать массу"]], one_time_keyboard=True, resize_keyboard=True)

contact_kb = ReplyKeyboardMarkup(
    [[KeyboardButton("Поделиться контактом ☎️", request_contact=True)], ["Пропустить"]],
    resize_keyboard=True, one_time_keyboard=True
)

def hour_kb(start=6, end=23):
    rows, row = [], []
    for h in range(start, end + 1):
        row.append(f"{h:02d}:00")
        if len(row) == 4:
            rows.append(row); row = []
    if row: rows.append(row)
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)
