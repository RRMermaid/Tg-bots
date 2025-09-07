# from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
# from telegram.ext import (
#     ApplicationBuilder,
#     CommandHandler,
#     MessageHandler,
#     ConversationHandler,
#     filters,
#     ContextTypes,
# )

# BOT_TOKEN = "8049457368:AAFe4ZZTTBsjkPCvx7yNYqzf8NGRIXjddXY"
# ADMIN_ID = 579596451

# # Состояния разговора регистрации + помощь
# ASK_NAME, ASK_PHONE, ASK_PEOPLE_COUNT, ASK_READY, WAIT_PAYMENT_PHOTO, HELP_ASK_QUESTION = range(6)

# MAIN_MENU = [['Регистрация', 'Помощь', 'Войти в чат']]
# CHAT_LINK = "https://t.me/+00KDjrWIpj5kNzUy"

# async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     keyboard = ReplyKeyboardMarkup(MAIN_MENU, resize_keyboard=True)
#     await update.message.reply_text(
#         "Привет! Выбери действие из меню:",
#         reply_markup=keyboard
#     )

# async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     text = update.message.text

#     if text == 'Регистрация':
#         await update.message.reply_text("Введи Ф.И.О.:", reply_markup=ReplyKeyboardRemove())
#         return ASK_NAME

#     elif text == 'Помощь':
#         await update.message.reply_text("Введи свой вопрос:", reply_markup=ReplyKeyboardRemove())
#         return HELP_ASK_QUESTION

#     elif text == 'Войти в чат':
#         paid = context.user_data.get('paid', False)
#         if paid:
#             await update.message.reply_text(f"Вот ссылка для входа в чат:\n{CHAT_LINK}")
#         else:
#             await update.message.reply_text(
#                 "Для доступа в чат важно пройти регистрацию и отправить квитанцию об оплате.\n"
#                 "Пожалуйста, сначала зарегистрируйся и загрузи фото оплаты через пункт «Регистрация»."
#             )
#         return ConversationHandler.END

#     else:
#         await update.message.reply_text("Пожалуйста, выберите кнопку из меню.")
#         return ConversationHandler.END

# # Регистрация: запрос телефона
# async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     context.user_data['name'] = update.message.text.strip()
#     await update.message.reply_text("Введите номер телефона (например, +7xxxxxxxxxx):")
#     return ASK_PHONE

# # Регистрация: запрос количества человек
# async def ask_people_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     context.user_data['phone'] = update.message.text.strip()
#     await update.message.reply_text("ВсколькирОм ты собираешься ехать? =)")
#     return ASK_PEOPLE_COUNT

# # Регистрация: готовность к поездке и информация об оплате
# async def ask_ready(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     context.user_data['people_count'] = update.message.text.strip()
#     payment_info = (
#         "Ты готов(а) отправиться в путешествие?\n\n"
#         "Для того, чтобы забронировать мест(о/а) в замечательном катамаране, тебе важно сделать вступительный взнос 1000р на карту Т-банка по номеру 89097096321, получатель Руфина Х.\n\n"
#         "Нажми кнопку 'Готово' после оплаты."
#     )
#     keyboard = ReplyKeyboardMarkup([['Готово']], resize_keyboard=True, one_time_keyboard=True)
#     await update.message.reply_text(payment_info, reply_markup=keyboard)
#     return ASK_READY

# # Ожидание клика "Готово" перед запросом фото
# async def wait_payment_photo_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     text = update.message.text.strip()
#     if text != 'Готово':
#         await update.message.reply_text("Пожалуйста, нажми кнопку 'Готово' после оплаты.")
#         return ASK_READY

#     # Отправляем админу данные регистрации
#     reg_info = (
#         f"Новый участник зарегистрирован:\n"
#         f"Ф.И.О.: {context.user_data.get('name')}\n"
#         f"Телефон: {context.user_data.get('phone')}\n"
#         f"Количество человек: {context.user_data.get('people_count')}\n"
#     )
#     await context.bot.send_message(chat_id=ADMIN_ID, text=reg_info)

#     await update.message.reply_text("Пожалуйста, загрузи скриншот (фото) оплаты (чека):", reply_markup=ReplyKeyboardRemove())
#     return WAIT_PAYMENT_PHOTO

# # Обработка полученного фото оплаты
# async def photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     if not update.message.photo:
#         await update.message.reply_text("Пожалуйста, отправь фотографию или скриншот оплаты.")
#         return WAIT_PAYMENT_PHOTO

#     photo_file = update.message.photo[-1]
#     caption = f"Оплата от {context.user_data.get('name')}, тел.: {context.user_data.get('phone')}"
#     await context.bot.send_photo(chat_id=ADMIN_ID, photo=photo_file.file_id, caption=caption)

#     # Устанавливаем флаг оплаты для пользователя
#     context.user_data['paid'] = True

#     await update.message.reply_text(
#         f"Ураааа!!! Мы очень рады, что ты с нами!\n\nВот ссылка на чат:\n{CHAT_LINK}",
#         reply_markup=ReplyKeyboardMarkup(MAIN_MENU, resize_keyboard=True)
#     )
#     return ConversationHandler.END

# # Обработка вопроса в разделе помощь
# async def help_receive_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     question = update.message.text.strip()
#     user = update.message.from_user

#     msg = (
#         f"Вопрос от пользователя:\n"
#         f"Имя: {user.first_name} {user.last_name or ''}\n"
#         f"ID: {user.id}\n\n"
#         f"Вопрос:\n{question}"
#     )
#     await context.bot.send_message(chat_id=ADMIN_ID, text=msg)

#     await update.message.reply_text(
#         "Спасибо за вопрос! Мы сейчас соберемся, все порешаем, возможно по пути поругаемся, потом проведем ЧЧ, составим ответ и свяжемся с тобой в ближайшее время.",
#         reply_markup=ReplyKeyboardMarkup(MAIN_MENU, resize_keyboard=True)
#     )
#     return ConversationHandler.END

# async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     await update.message.reply_text("Действие отменено.", reply_markup=ReplyKeyboardMarkup(MAIN_MENU, resize_keyboard=True))
#     return ConversationHandler.END

# def main():
#     application = ApplicationBuilder().token(BOT_TOKEN).build()

#     conv_handler = ConversationHandler(
#         entry_points=[
#             CommandHandler('start', start),
#             MessageHandler(filters.Regex('^(Регистрация|Помощь|Войти в чат)$'), main_menu_handler)
#         ],
#         states={
#             ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
#             ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_people_count)],
#             ASK_PEOPLE_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_ready)],
#             ASK_READY: [MessageHandler(filters.Regex('^Готово$'), wait_payment_photo_request)],
#             WAIT_PAYMENT_PHOTO: [MessageHandler(filters.PHOTO, photo_received)],
#             HELP_ASK_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, help_receive_question)],
#         },
#         fallbacks=[CommandHandler('cancel', cancel)],
#     )

#     application.add_handler(conv_handler)

#     print("Бот запущен...")
#     application.run_polling()

# if __name__ == '__main__':
#     main()
