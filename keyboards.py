from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

gender_kb = ReplyKeyboardMarkup([["Мужской","Женский"]],resize_keyboard=True,one_time_keyboard=True)
activity_kb = ReplyKeyboardMarkup([["1","2"],["3","4"]],resize_keyboard=True,one_time_keyboard=True)
goal_kb = ReplyKeyboardMarkup([["Похудеть","Удержать вес","Набрать массу"]],resize_keyboard=True,one_time_keyboard=True)
contact_kb = ReplyKeyboardMarkup(
    [[KeyboardButton("Поделиться контактом ☎️",request_contact=True)],["Пропустить"]],
    resize_keyboard=True,one_time_keyboard=True)
skip_kb = ReplyKeyboardMarkup([["Нет ограничений"]],resize_keyboard=True,one_time_keyboard=True)
skip_only_kb = ReplyKeyboardMarkup([["Пропустить"]],resize_keyboard=True,one_time_keyboard=True)
deficit_kb = ReplyKeyboardMarkup(
    [["Комфортный — 10%"],["Более быстрый — 20%"]],resize_keyboard=True,one_time_keyboard=True)
main_menu_kb = ReplyKeyboardMarkup([
    ["⚖️ Записать вес","📊 Анализ дня"],
    ["📅 Анализ недели","📈 Прогресс"],
    ["🥗 Рекомендации","⚙️ Настройки"],
],resize_keyboard=True)

def edit_meal_keyboard(draft_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Исправить",callback_data=f"meal:edit:{draft_id}")]])
