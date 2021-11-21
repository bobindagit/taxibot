import time
from database import Database
from telegramBot import TelegramBot
from telegramChatBot import TelegramChatBot
from telegram import ParseMode, InlineKeyboardButton, InlineKeyboardMarkup


def main():

    database = Database()

    telegram_bot = TelegramBot(database)
    telegram_chat_bot = TelegramChatBot(database)

    # Menu
    order_keyboard = [
        [InlineKeyboardButton(text='Принять заказ', callback_data='accept_order')]
    ]
    reply_markup = InlineKeyboardMarkup(order_keyboard, resize_keyboard=True, one_time_keyboard=False)

    # Main loop
    while True:
        time.sleep(5)
        # Telegram USER bot
        # Checking status of orders
        accepted_orders = database.db_orders.find({'status': 'accepted', 'user_notification_sent': False})
        for order in accepted_orders:
            order_info = f'Ваш заказ {order.get("from")} -> {order.get("to")} <b>принят</b>!\nВодитель: {order.get("driver_name")}'
            telegram_bot.updater.bot.send_message(chat_id=order.get('user_id'),
                                                  text=order_info,
                                                  parse_mode=ParseMode.HTML)
            telegram_bot.orders_manager.set_order_field(order.get('order_id'), 'user_notification_sent', True)
        # Telegram DRIVERS bot
        # Checking for new orders
        opened_orders = telegram_chat_bot.get_opened_orders()
        for order in opened_orders:
            message = f'<b>Новый заказ!</b> №{order.get("order_id")}\n' \
                      f'<b>*</b> {order.get("from")} -> {order.get("to")}\n' \
                      f'<b>*</b> Время: {order.get("time")}\n' \
                      f'<b>*</b> Связь: {order.get("contacts")}\n' \
                      f'<b>*</b> @{order.get("user_name")}'
            telegram_chat_bot.updater.bot.send_message(chat_id=telegram_chat_bot.bot_chat_id,
                                                       text=message,
                                                       parse_mode=ParseMode.HTML,
                                                       reply_markup=reply_markup)
            telegram_chat_bot.set_notification_flag(order.get('order_id'))


if __name__ == '__main__':
    main()
