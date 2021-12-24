import json
import requests
from datetime import datetime
from datetime import timedelta
import time
from requests.auth import HTTPBasicAuth
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler
from telegram import KeyboardButton, ReplyKeyboardMarkup, ParseMode, InlineKeyboardButton, InlineKeyboardMarkup


# STEP NAMES
QUESTION = 'question'
TAXI_FROM = 'from'
TAXI_FROM_LOCATION = 'from_location'
TAXI_TO = 'to'
TAXI_TO_LOCATION = 'to_location'
TAXI_TIME = 'time'
TAXI_CONTACT = 'contacts'


class TelegramBot:

    def __init__(self, database):

        # Reading file and getting settings
        with open('settings.json', 'r') as file:
            file_data = json.load(file)
            bot_token = file_data.get('bot_token_user')
            file.close()

        self.database = database
        self.user_manager = UserManager(self.database.db_user_info)
        self.orders_manager = OrdersManager(database.db_orders)

        # Main telegram UPDATER
        self.updater = Updater(token=bot_token, use_context=True)
        self.dispatcher = self.updater.dispatcher

        # Initializing Menu object
        menu = TelegramMenu(self.user_manager, self.orders_manager)

        # Initializing Handler object
        handlers = TelegramHandlers(self.user_manager, menu)

        # Handlers
        self.dispatcher.add_handler(CommandHandler('start', handlers.start))
        self.dispatcher.add_handler(CommandHandler('stop', handlers.stop))
        self.dispatcher.add_handler(MessageHandler(Filters.text, menu.menu_message))
        self.dispatcher.add_handler(MessageHandler(Filters.location, menu.location_message))
        self.dispatcher.add_handler(MessageHandler(Filters.command, handlers.unknown))
        self.dispatcher.add_handler(CallbackQueryHandler(self.orders_manager.decline_order, pattern='decline_order'))
        # Time menu handlers
        self.dispatcher.add_handler(CallbackQueryHandler(menu.time1, pattern='time1'))
        self.dispatcher.add_handler(CallbackQueryHandler(menu.time2, pattern='time2'))
        self.dispatcher.add_handler(CallbackQueryHandler(menu.time3, pattern='time3'))

        # Starting the bot
        self.updater.start_polling()

        print('Telegram bot initialized!')


class UserManager:

    def __init__(self, db_user_info):
        self.db_user_info = db_user_info

    def create_user(self, current_user: dict) -> None:
        user_info = {'user_id': current_user.id,
                     'full_name': current_user.full_name,
                     'link': current_user.link,
                     'current_step': '',
                     'current_order_id': '',
                     'contacts': [],
                     'orders_count': 0}
        self.db_user_info.update({'user_id': current_user.id}, user_info, upsert=True)

    def remove_user(self, user_id: str) -> None:
        self.db_user_info.remove({'user_id': user_id})

    def get_user_field(self, user_id: str, field: str) -> str | list:
        return self.db_user_info.find({'user_id': user_id})[0].get(field)

    def set_user_field(self, user_id: str, field: str, new_value: str | list) -> None:
        value_to_update = {'$set': {field: new_value}}
        self.db_user_info.update({'user_id': user_id}, value_to_update)


class OrdersManager:

    def __init__(self, db_orders):
        self.db_orders = db_orders

    def create_order(self, user_id: str, user_name: str) -> str:
        new_order = {
            'order_id': self.generate_new_order_id(),
            'message_id': 0,
            'user_id': user_id,
            'user_name': user_name,
            'status': 'new',
            'driver_name': '',
            'drivers_notification_sent': False,
            'drivers_notification_declined_sent': False,
            'user_notification_sent': False,
            TAXI_FROM: '',
            TAXI_FROM_LOCATION: '',
            TAXI_TO: '',
            TAXI_TO_LOCATION: '',
            TAXI_TIME: '',
            TAXI_CONTACT: ''
        }
        self.db_orders.insert(new_order)
        return new_order.get('order_id')

    def generate_new_order_id(self) -> str:
        if self.db_orders.count() == 0:
            return 1
        else:
            all_orders = self.db_orders.find()
            return all_orders[all_orders.count() - 1].get('order_id') + 1

    def set_order_field(self, order_id: str, order_field: str, new_value: str) -> None:
        value_to_update = {"$set": {order_field: new_value}}
        self.db_orders.update({'order_id': order_id}, value_to_update)

    def get_order_info(self, order_id: str) -> dict:
        return self.db_orders.find({'order_id': order_id})[0]

    def get_open_orders(self, user_id: str) -> list:
        return self.db_orders.find({'user_id': user_id, 'status': 'open'})

    def generate_order_message(self, order: dict) -> str:
        return f'[№{order.get("order_id")}] {order.get(TAXI_FROM)} -> {order.get(TAXI_TO)} ({order.get(TAXI_TIME)})'

    def decline_order(self, update, context) -> None:
        message = update.effective_message.text_html
        order_id = message.partition(']')[0].replace('[№', '')
        # Updating order status
        value_to_update = {"$set": {'status': "declined"}}
        self.db_orders.update({'order_id': int(order_id)}, value_to_update)
        # Message to chat
        query = update.callback_query
        query.answer()
        query.edit_message_text(
            text=f'❌ {message} <b>ОТМЕНЕН</b>',
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True)


class TelegramMenu:

    def __init__(self, user_manager: UserManager, orders_manager: OrdersManager):

        # Map.md Token
        with open('settings.json', 'r') as file:
            file_data = json.load(file)
            self.mapmd_token = file_data.get('mapmd_token')
            file.close()

        self.user_manager = user_manager
        self.orders_manager = orders_manager

        # Main menu buttons
        main_keyboard = [
            [KeyboardButton(text='Заказать такси'),
             KeyboardButton(text='Активные заказы'),
             KeyboardButton(text='Цены'),
             KeyboardButton(text='Вопрос / Предложение')]
        ]
        self.reply_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True, one_time_keyboard=False)

    def menu_message(self, update, context) -> None:

        user_message = update.message.text.upper()
        user_id = update.effective_chat.id

        current_step = self.user_manager.get_user_field(user_id, 'current_step')

        if user_message == 'ЗАКАЗАТЬ ТАКСИ':
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text='Откуда поедем?\n(<b>прикрепите геопозицию или напишите сообщение</b>)',
                                     parse_mode=ParseMode.HTML)
            self.user_manager.set_user_field(user_id, 'current_step', TAXI_FROM)
        elif user_message == 'АКТИВНЫЕ ЗАКАЗЫ':
            open_orders = self.orders_manager.get_open_orders(user_id)
            if open_orders.count() == 0:
                context.bot.send_message(chat_id=update.effective_chat.id,
                                         text='Нет активных заказов')
            else:
                order_keyboard = [
                    [InlineKeyboardButton(text='Отменить', callback_data='decline_order')]
                ]
                reply_markup = InlineKeyboardMarkup(order_keyboard, resize_keyboard=True, one_time_keyboard=False)
                for open_order in open_orders:
                    context.bot.send_message(chat_id=update.effective_chat.id,
                                             text=self.orders_manager.generate_order_message(open_order),
                                             reply_markup=reply_markup)
        elif user_message == 'ЦЕНЫ':
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text='❇️ По району - <b>40 ЛЕЙ</b>\n'
                                          '❇️ Между районами - <b>50 ЛЕЙ</b>\n'
                                          '❇️ Через район - <b>60 ЛЕЙ</b>\n\n'
                                          '🌐 Тариф вне Кишинева - <b>5 ЛЕЙ/КМ</b>\n\n'
                                          '🕓 <i>Ожидание: 5 мин. бесплатно, далее - <b>1 ЛЕЙ/МИН.</b></i>\n\n'
                                          '‼️ Цены указаны приблизительно и могут варьироваться в зависимости от разных факторов!\n'
                                          '‼️ Советуем уточнять цену перед поездкой!',
                                     parse_mode=ParseMode.HTML)
        elif user_message == 'ВОПРОС / ПРЕДЛОЖЕНИЕ':
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text='Напишите Ваш вопрос или предложение')
            self.user_manager.set_user_field(user_id, 'current_step', QUESTION)
        elif len(current_step) != 0:
            self.message_handler(user_id, user_message, current_step, update, context)
        else:
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text='Я не знаю такой команды')

    def location_message(self, update, context) -> None:

        user_id = update.effective_chat.id

        location = update.message.location
        latitude = location.latitude
        longitude = location.longitude
        full_location = f'{longitude},{latitude}'
        address = self.get_address_from_location(latitude, longitude)

        current_step = self.user_manager.get_user_field(user_id, 'current_step')

        if current_step == TAXI_FROM:
            self.taxi_from_handler(user_id, address, full_location, context)
        elif current_step == TAXI_TO:
            self.taxi_to_handler(user_id, address, full_location, update)

    def message_handler(self, user_id: str, user_message: str, current_step: str, update, context) -> None:

        if current_step == QUESTION:
            user_name = self.user_manager.get_user_field(user_id, 'link').replace('https://t.me/', '@')
            question = f'<b>Поступил вопрос/предложение от {user_name}</b>\n\n' \
                       f'{user_message}'
            # bobtb
            context.bot.send_message(chat_id='360152058',
                                     text=question,
                                     parse_mode=ParseMode.HTML)
        elif current_step == TAXI_FROM:
            self.taxi_from_handler(user_id, user_message, '', context)
        elif current_step == TAXI_TO:
            self.taxi_to_handler(user_id, user_message, '', update)
        elif current_step == TAXI_TIME:
            self.taxi_time_handler(user_id, user_message, context)
        elif current_step == TAXI_CONTACT:
            self.taxi_contact_handler(user_id, user_message, context)

    def taxi_from_handler(self, user_id: str, address: str, full_location: str, context) -> None:

        user_name = self.user_manager.get_user_field(user_id, 'link')
        order_id = self.orders_manager.create_order(user_id, user_name.replace('https://t.me/', ''))

        self.orders_manager.set_order_field(order_id, TAXI_FROM, address)
        self.orders_manager.set_order_field(order_id, TAXI_FROM_LOCATION, full_location)

        self.user_manager.set_user_field(user_id, 'current_order_id', order_id)
        self.user_manager.set_user_field(user_id, 'current_step', TAXI_TO)

        context.bot.send_message(chat_id=user_id,
                                 text='Куда поедем?\n(<b>прикрепите геопозицию или напишите сообщение</b>)',
                                 parse_mode=ParseMode.HTML)

    def taxi_to_handler(self, user_id: str, address: str, full_location: str, update) -> None:

        order_id = self.user_manager.get_user_field(user_id, 'current_order_id')

        self.orders_manager.set_order_field(order_id, TAXI_TO, address)
        self.orders_manager.set_order_field(order_id, TAXI_TO_LOCATION, full_location)

        self.user_manager.set_user_field(user_id, 'current_step', TAXI_TIME)

        keyboard = [
            [InlineKeyboardButton('Ближайшее время', callback_data='time1')],
            [InlineKeyboardButton('15 мин', callback_data='time2'),
            InlineKeyboardButton('20 мин', callback_data='time3'),
            InlineKeyboardButton('25 мин', callback_data='time4')]
        ]
        update.message.reply_text(text='Во сколько Вас забрать? Выберите вариант или напишите свой',
                                    reply_markup=InlineKeyboardMarkup(keyboard))
        #context.bot.send_message(chat_id=user_id,
        #                         text='Во сколько Вас забрать? Выберите вариант или напишите свой (Пример: 17:30)',
        #                         reply_markup=InlineKeyboardMarkup(keyboard))

    def taxi_time_handler(self, user_id: str, user_message: str, context) -> None:

        order_id = self.user_manager.get_user_field(user_id, 'current_order_id')

        self.orders_manager.set_order_field(order_id, TAXI_TIME, user_message)
        self.user_manager.set_user_field(user_id, 'current_step', TAXI_CONTACT)

        context.bot.send_message(chat_id=user_id,
                                 text='Как с Вами связаться?')

    def taxi_contact_handler(self, user_id: str, user_message: str, context) -> None:

        order_id = self.user_manager.get_user_field(user_id, 'current_order_id')

        self.orders_manager.set_order_field(order_id, TAXI_CONTACT, user_message)

        self.user_manager.set_user_field(user_id, 'current_step', '')
        self.user_manager.set_user_field(user_id, 'current_order_id', '')

        # Updating contacts
        current_contacts = self.user_manager.get_user_field(user_id, 'contacts')
        if user_message not in current_contacts:
            current_contacts.append(user_message)
        self.user_manager.set_user_field(user_id, 'contacts', current_contacts)

        self.orders_manager.set_order_field(order_id, 'status', 'open')

        context.bot.send_message(chat_id=user_id,
                                 text='🔔 Заявка отправлена! Ожидайте ответа...')

    def get_address_from_location(self, latitude: str, longitude: str) -> str:

        url = f'https://map.md/api/companies/webmap/near?lat={latitude}&lon={longitude}'
        headers = {'Content-Type': 'application/json'}
        request = requests.get(url=url,
                               auth=HTTPBasicAuth(self.mapmd_token, ''),
                               headers=headers)

        if request.status_code == 200:
            request_json = request.json()
            try:
                building = request_json.get('building')
                city = building.get('location').replace('Chişinău', 'Chisinau')
                street = building.get('street_name')
                number = building.get('number')
                return f'{city}, {street} {number}'
            except:
                return 'Не определен'
        else:
            return 'Не определен'

    def time1(self, update, context) -> None:
        
        query = update.callback_query
        query.answer()

        user_id = update.effective_chat.id
        self.taxi_time_handler(user_id, 'Ближайшее время', context)

    def time2(self, update, context) -> None:

        query = update.callback_query
        query.answer()

        user_id = update.effective_chat.id

        current_time = datetime.now()
        final_time = current_time + timedelta(minutes=15)

        self.taxi_time_handler(user_id, final_time.strftime("%H:%M"), context)

    def time3(self, update, context) -> None:
        
        query = update.callback_query
        query.answer()

        user_id = update.effective_chat.id

        current_time = datetime.now()
        final_time = current_time + timedelta(minutes=20)

        self.taxi_time_handler(user_id, final_time.strftime("%H:%M"), context)
    
    def time4(self, update, context) -> None:
        
        query = update.callback_query
        query.answer()

        user_id = update.effective_chat.id

        current_time = datetime.now()
        final_time = current_time + timedelta(minutes=25)

        self.taxi_time_handler(user_id, final_time.strftime("%H:%M"), context)

class TelegramHandlers:

    def __init__(self, user_manager: UserManager, menu: TelegramMenu):

        # Initializing menu
        self.menu = menu
        self.user_manager = user_manager

    def start(self, update, context) -> None:

        # Creating users
        current_user = update.effective_chat
        self.user_manager.create_user(current_user)

        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text=f'👋 <b>Привет, {current_user.full_name}!</b> 👋\n\n'
                                      f'🚕 С моей помощью можно удобно заказать такси\n'
                                      f'❓ <i>Есть вопрос или предложение? Связаться с администрацией можно по соответствующей кнопке</i>\n\n'
                                      f'📣 Хочешь быть в команде водителей? Свяжись с нами',
                                 reply_markup=self.menu.reply_markup,
                                 parse_mode=ParseMode.HTML)

    def stop(self, update, context) -> None:

        self.user_manager.remove_user(update.effective_chat.id)

        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text='Чтобы вновь удобно заказывать такси - введи /start')

    def unknown(self, update, context) -> None:

        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text="Я не знаю такой команды")


if __name__ == '__main__':
    print('Only for import!')
