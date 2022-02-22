import urllib.parse
import json

import requests
from requests.auth import HTTPBasicAuth

from telegram import ParseMode, InlineKeyboardButton, InlineKeyboardMarkup

from database import Database
from telegramBot import TelegramBot
from telegramChatBot import TelegramChatBot

# TEXT DICTIONARY
with open('all_text.json', 'r', encoding='utf-8') as file:
    ALL_TEXT = json.load(file)
    file.close()


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
        [InlineKeyboardButton(text='Принять', callback_data='accept_order')]
    ]
    reply_markup = InlineKeyboardMarkup(order_keyboard, resize_keyboard=True, one_time_keyboard=False)

    # Main loop
    while True:

        # USER bot
        accepted_orders = database.db_orders.find({'status': 'accepted', 'user_notification_sent': False})
        for order in accepted_orders:
            user_id = order.get('user_id')
            user_language = telegram_bot.user_manager.get_user_field(user_id, 'language')
            order_info = ALL_TEXT.get('accepted_order').get(user_language).replace('{order.from}', order.get('from')).replace('{order.to}', order.get('to')).replace('{order.driver_name}', order.get('driver_name'))
            telegram_bot.updater.bot.send_message(chat_id=user_id,
                                                  text=order_info,
                                                  parse_mode=ParseMode.HTML)
            telegram_bot.orders_manager.set_order_field(order.get('order_id'), 'user_notification_sent', True)
            # Updating orders count
            current_orders_count = telegram_bot.user_manager.get_user_field(user_id, 'orders_count')
            telegram_bot.user_manager.set_user_field(user_id, 'orders_count', current_orders_count + 1)

        # DRIVERS CHAT bot
        # New orders
        opened_orders = telegram_chat_bot.get_orders('open')
        for order in opened_orders:
            order_id = order.get('order_id')
            message_for_drivers = generate_message_for_drivers(order, mapmd_token)
            # Message to drivers chat
            message_sent = telegram_chat_bot.updater.bot.send_message(chat_id=telegram_chat_bot.bot_chat_id,
                                                                      text=message_for_drivers,
                                                                      parse_mode=ParseMode.HTML,
                                                                      reply_markup=reply_markup,
                                                                      disable_web_page_preview=True)
            # Update info of the order
            telegram_bot.orders_manager.set_order_field(order_id, 'message_id', message_sent.message_id)
            telegram_bot.orders_manager.set_order_field(order_id, 'drivers_notification_sent', True)
        # Declined orders
        declined_orders = telegram_chat_bot.get_orders('declined')
        for order in declined_orders:
            telegram_chat_bot.updater.bot.delete_message(chat_id=telegram_chat_bot.bot_chat_id,
                                                         message_id=order.get('message_id'))


def generate_message_for_drivers(order: dict, mapmd_token: str) -> str:

    from_message = order.get('from')
    to_message = order.get('to')

    from_location = order.get('from_location')
    to_location = order.get('to_location')

    from_geo = len(from_location) != 0
    to_geo = len(to_location) != 0

    # Checking if we got addresses from geolocation
    if from_geo:
        from_message_modified = from_message.replace('Chișinău,', '').replace('Chisinau,', '').strip()
        order_from = f'<a href="https://yandex.ru/maps/?pt={from_location}&z=18&l=map">{from_message_modified}</a>'
    else:
        order_from = f'<a href="https://yandex.ru/maps/?l=map&text={convert_address_url(from_message)}">{from_message}</a>'

    if to_geo:
        to_message_modified = to_message.replace('Chișinău,', '').replace('Chisinau,', '').strip()
        order_to = f'<a href="https://yandex.ru/maps/?pt={to_location}&z=18&l=map">{to_message_modified}</a>'
    else:
        order_to = f'<a href="https://yandex.ru/maps/?l=map&text={convert_address_url(to_message)}">{to_message}</a>'

    # Route
    order_from_to = f'<a href="{generate_route_url(from_message, to_message, from_location, to_location, mapmd_token)}"> ➡️ </a>'

    message = f'‼️ <b>Новый заказ</b> ‼️ №{order.get("order_id")}\n\n' \
              f'{order_from} {order_from_to} {order_to}\n' \
              f'📞 Связь: {order.get("contacts")}\n'

    if order.get("user_name"):
        message += f'💬 @{order.get("user_name")}\n'

    if order.get("comment"):
        message += f'🕓 Комментарий: <i>{order.get("comment")}</i>'

    return message


def convert_address_url(address: str) -> str:

    if address.find('CHISINAU') == -1:
        address = 'Chisinau, ' + address

    return urllib.parse.quote(address)


def generate_route_url(from_message: str, to_message: str, from_location: str, to_location: str, token: str) -> str:

    if len(from_location) == 0:
        from_structure = get_address_structure(from_message, token)
        from_lat = from_structure.get('latitude')
        from_lon = from_structure.get('longitude')
    else:
        from_structure = from_location.split(',')
        from_lat = from_structure[1]
        from_lon = from_structure[0]

    if len(to_location) == 0:
        to_structure = get_address_structure(to_message, token)
        to_lat = to_structure.get('latitude')
        to_lon = to_structure.get('longitude')
    else:
        to_structure = to_location.split(',')
        to_lat = to_structure[1]
        to_lon = to_structure[0]

    return f'https://yandex.ru/maps/?rtext={from_lat},{from_lon}~{to_lat},{to_lon}&rtt=auto'


def get_address_structure(address: str, token: str) -> dict:

    url = f'https://map.md/api/companies/webmap/search?q={address}'
    headers = {'Content-Type': 'application/json'}
    request = requests.get(url=url,
                           auth=HTTPBasicAuth(token, ''),
                           headers=headers)

    if request.status_code == 200:
        request_json = request.json()
        try:
            centroid = request_json.get('selected').get('centroid')
            return {
                'latitude': centroid.get('lat'),
                'longitude': centroid.get('lon')
            }
        except:
            return {
                'latitude': 0,
                'longitude': 0
            }
    else:
        return {
            'latitude': 0,
            'longitude': 0
        }


if __name__ == '__main__':
    main()
