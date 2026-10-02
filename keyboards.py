from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

gender_kb = ReplyKeyboardMarkup([["Мужской","Женский"]],resize_keyboard=True,one_time_keyboard=True)
activity_kb = ReplyKeyboardMarkup([["1","2","3","4","5"]],resize_keyboard=True,one_time_keyboard=True)
goal_kb = ReplyKeyboardMarkup([["Похудеть","Удержать вес","Набрать массу"]],resize_keyboard=True,one_time_keyboard=True)

def draft_keyboard(draft_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Сохранить",callback_data=f"meal:save:{draft_id}")],
        [InlineKeyboardButton("Уточнить",callback_data=f"meal:edit:{draft_id}"),
         InlineKeyboardButton("Отменить",callback_data=f"meal:cancel:{draft_id}")]])
