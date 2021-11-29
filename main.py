import time
import urllib.parse
import json

import requests
from requests.auth import HTTPBasicAuth

from telegram import ParseMode, InlineKeyboardButton, InlineKeyboardMarkup

from database import Database
from telegramBot import TelegramBot
from telegramChatBot import TelegramChatBot


def main():

    # Map.md Token
    with open('settings.json', 'r') as file:
        file_data = json.load(file)
        mapmd_token = file_data.get('mapmd_token')
        file.close()

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
            from_message = order.get('from')
            to_message = order.get('to')
            order_from = f'<a href="https://yandex.ru/maps/?l=map&text={generate_address_url(from_message)}">{from_message}</a>'
            order_to = f'<a href="https://yandex.ru/maps/?l=map&text={generate_address_url(to_message)}">{to_message}</a>'
            order_from_to = f'<a href="{generate_route_url(from_message, to_message, mapmd_token)}">🌍 Маршрут</a>'
            message = f'‼️ <b>Новый заказ</b> ‼️ №{order.get("order_id")}\n\n' \
                      f'{order_from} ➡️ {order_to}\n' \
                      f'{order_from_to}\n' \
                      f'🕓 Время: {order.get("time")}\n' \
                      f'📞 Связь: {order.get("contacts")}\n' \
                      f'💬 @{order.get("user_name")}'
            telegram_chat_bot.updater.bot.send_message(chat_id=telegram_chat_bot.bot_chat_id,
                                                       text=message,
                                                       parse_mode=ParseMode.HTML,
                                                       reply_markup=reply_markup,
                                                       disable_web_page_preview=True)
            telegram_chat_bot.set_notification_flag(order.get('order_id'))


def generate_address_url(address: str) -> str:

    if address.find('CHISINAU') == -1:
        address = 'Chisinau, ' + address

    return urllib.parse.quote(address)


def generate_route_url(from_message: str, to_message: str, token: str) -> str:

    from_structure = get_address_structure(from_message, token)
    from_lat = from_structure.get('latitude')
    from_lon = from_structure.get('longitude')

    to_structure = get_address_structure(to_message, token)
    to_lat = to_structure.get('latitude')
    to_lon = to_structure.get('longitude')

    return f'https://yandex.ru/maps/?rtext={from_lat},{from_lon}~{to_lat},{to_lon}&rtt=auto'


def get_address_structure(address: str, token: str) -> dict:

    url = f'https://map.md/api/companies/webmap/search?q={address}'
    headers = {'Content-Type': 'application/json'}
    request = requests.get(url=url,
                           auth=HTTPBasicAuth(token, ''),
                           headers=headers)

    if request.status_code == 200:
        request_json = request.json()
        centroid = request_json.get('selected').get('centroid')
        return {
            'latitude': centroid.get('lat'),
            'longitude': centroid.get('lon')
        }
    else:
        return {
            'latitude': 0,
            'longitude': 0
        }


if __name__ == '__main__':
    main()
