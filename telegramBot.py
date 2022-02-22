import json
import requests
from requests.auth import HTTPBasicAuth
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler
from telegram import KeyboardButton, ReplyKeyboardMarkup, ParseMode, InlineKeyboardButton, InlineKeyboardMarkup


# STEP NAMES
QUESTION = 'question'
TAXI_FROM = 'from'
TAXI_FROM_LOCATION = 'from_location'
TAXI_TO = 'to'
TAXI_TO_LOCATION = 'to_location'
TAXI_CONTACT = 'contacts'
TAXI_COMMENT = 'comment'

# TEXT DICTIONARY
with open('all_text.json', 'r', encoding='utf-8') as file:
    ALL_TEXT = json.load(file)
    file.close()

# ADMIN GROUP ID
with open('settings.json', 'r') as file:
    file_data = json.load(file)
    ADMIN_GROUP_ID = file_data.get('bot_admin_group_id')
    file.close()


class TelegramBot:

    def __init__(self, database):

        # Reading file and getting settings
        with open('settings.json', 'r') as file:
            file_data = json.load(file)
            bot_token = file_data.get('bot_token_user')
            file.close()

        self.database = database
        self.user_manager = UserManager(self.database.db_user_info, self.database.db_blacklist)
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
        # Comment menu handlers
        self.dispatcher.add_handler(CallbackQueryHandler(menu.no_comments, pattern='no_comments'))

        # Starting the bot
        self.updater.start_polling()

        print('USER BOT initialized!')


class UserManager:

    def __init__(self, db_user_info, db_blacklist):
        self.db_user_info = db_user_info
        self.db_blacklist = db_blacklist

    def create_user(self, current_user: dict) -> None:
        user_link = current_user.link
        if not user_link:
            user_link = ''
        user_info = {'user_id': current_user.id,
                     'full_name': current_user.full_name,
                     'link': user_link,
                     'current_step': '',
                     'current_order_id': '',
                     'contacts': [],
                     'orders_count': 0,
                     'language': 'ru'}
        self.db_user_info.update({'user_id': current_user.id}, user_info, upsert=True)

    def remove_user(self, user_id: str) -> None:
        self.db_user_info.remove({'user_id': user_id})

    def get_user_field(self, user_id: str, field: str) -> str | list:
        return self.db_user_info.find({'user_id': user_id})[0].get(field)

    def set_user_field(self, user_id: str, field: str, new_value: str | list) -> None:
        value_to_update = {'$set': {field: new_value}}
        self.db_user_info.update({'user_id': user_id}, value_to_update)

    def user_banned(self, user_id: str) -> bool:
        return self.db_blacklist.find({'user_id': user_id}).count() > 0


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
            'user_notification_sent': False,
            TAXI_FROM: '',
            TAXI_FROM_LOCATION: '',
            TAXI_TO: '',
            TAXI_TO_LOCATION: '',
            TAXI_CONTACT: '',
            TAXI_COMMENT: ''
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
        order_message = f'[№{order.get("order_id")}] {order.get(TAXI_FROM)} -> {order.get(TAXI_TO)}'
        if order.get(TAXI_COMMENT):
            order_message += f' ({order.get(TAXI_COMMENT)})'
        return order_message


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
            [
                KeyboardButton(text='Заказать'),
                KeyboardButton(text='Отменить')
             ],
            [
                KeyboardButton(text='Цены'),
                KeyboardButton(text='🇷🇴 / 🇷🇺'),
                KeyboardButton(text='Контакты')
            ]
        ]
        self.reply_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True, one_time_keyboard=False)

    def menu_message(self, update, context) -> None:

        user_message = update.message.text
        user_id = update.effective_chat.id

        user_language = self.user_manager.get_user_field(user_id, 'language')
        current_step = self.user_manager.get_user_field(user_id, 'current_step')

        main_menu_text = ALL_TEXT.get('main_menu')

        # Blacklist check
        if self.user_manager.user_banned(user_id):
            return

        if user_message == main_menu_text.get('menu1_ru') or user_message == main_menu_text.get('menu1_ro'):
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text=ALL_TEXT.get('taxi_from').get(user_language),
                                     parse_mode=ParseMode.HTML)
            self.user_manager.set_user_field(user_id, 'current_step', TAXI_FROM)
        elif user_message == main_menu_text.get('menu2_ru') or user_message == main_menu_text.get('menu2_ro'):
            open_orders = self.orders_manager.get_open_orders(user_id)
            if open_orders.count() == 0:
                context.bot.send_message(chat_id=update.effective_chat.id,
                                         text=ALL_TEXT.get('no_open_orders').get(user_language))
            else:
                for open_order in open_orders:
                    self.orders_manager.set_order_field(open_order.get('order_id'), 'status', 'declined')
                context.bot.send_message(chat_id=update.effective_chat.id,
                                         text=ALL_TEXT.get('orders_have_been_declined').get(user_language))
        elif user_message == main_menu_text.get('menu3_ru') or user_message == main_menu_text.get('menu3_ro'):
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text='❇️ По району - <b>40 ЛЕЙ</b>\n'
                                          '❇️ Между районами - <b>50 ЛЕЙ</b>\n'
                                          '❇️ Через район - <b>60 ЛЕЙ</b>\n\n'
                                          '🌐 Тариф вне Кишинева - <b>5 ЛЕЙ/КМ</b>\n\n'
                                          '🕓 <i>Ожидание: 5 мин. бесплатно, далее - <b>1 ЛЕЙ/МИН.</b></i>\n\n'
                                          '‼️ Цены указаны приблизительно и могут варьироваться в зависимости от разных факторов!\n'
                                          '‼️ Советуем уточнять цену перед поездкой!',
                                     parse_mode=ParseMode.HTML)
        elif user_message == '🇷🇴 / 🇷🇺':
            current_language = self.user_manager.get_user_field(user_id, 'language')
            new_language = 'ro' if current_language == 'ru' else 'ru'
            self.user_manager.set_user_field(user_id, 'language', new_language)
            # Main menu buttons
            new_keyboard = [
                [
                    KeyboardButton(text=main_menu_text.get(f'menu1_{new_language}')),
                    KeyboardButton(text=main_menu_text.get(f'menu2_{new_language}'))
                ],
                [
                    KeyboardButton(text=main_menu_text.get(f'menu3_{new_language}')),
                    KeyboardButton(text='🇷🇴 / 🇷🇺'),
                    KeyboardButton(text=main_menu_text.get(f'menu4_{new_language}'))
                ]
            ]
            reply_markup = ReplyKeyboardMarkup(new_keyboard, resize_keyboard=True, one_time_keyboard=False)
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text=ALL_TEXT.get('language_change').get(new_language),
                                     reply_markup=reply_markup)
        elif user_message == main_menu_text.get('menu4_ru') or user_message == main_menu_text.get('menu4_ro'):
            message_for_user = ALL_TEXT.get('contacts').get(user_language)
            if not self.user_manager.get_user_field(user_id, 'link'):
                message_for_user += '\n' + ALL_TEXT.get('taxi_contact').get(f'special_{user_language}')
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text=message_for_user,
                                     parse_mode=ParseMode.HTML)
            self.user_manager.set_user_field(user_id, 'current_step', QUESTION)
        elif len(current_step) != 0:
            self.message_handler(user_id, user_message, current_step, update, context)
        else:
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text=ALL_TEXT.get('unknown_command').get(user_language))

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
            # Forward message to admins group
            context.bot.forward_message(chat_id=ADMIN_GROUP_ID,
                                        from_chat_id=update.message.chat_id,
                                        message_id=update.message.message_id)
        elif current_step == TAXI_FROM:
            self.taxi_from_handler(user_id, user_message, '', context)
        elif current_step == TAXI_TO:
            self.taxi_to_handler(user_id, user_message, '', context)
        elif current_step == TAXI_CONTACT:
            self.taxi_contact_handler(user_id, user_message, update)
        elif current_step == TAXI_COMMENT:
            self.taxi_comment_handler(user_id, user_message, context)

    def taxi_from_handler(self, user_id: str, address: str, full_location: str, context) -> None:

        user_link = self.user_manager.get_user_field(user_id, 'link')
        if user_link:
            user_name = user_link.replace('https://t.me/', '')
        else:
            user_name = ''

        order_id = self.orders_manager.create_order(user_id, user_name)

        self.orders_manager.set_order_field(order_id, TAXI_FROM, address)
        self.orders_manager.set_order_field(order_id, TAXI_FROM_LOCATION, full_location)

        self.user_manager.set_user_field(user_id, 'current_order_id', order_id)
        self.user_manager.set_user_field(user_id, 'current_step', TAXI_TO)

        user_language = self.user_manager.get_user_field(user_id, 'language')
        context.bot.send_message(chat_id=user_id,
                                 text=ALL_TEXT.get('taxi_to').get(user_language),
                                 parse_mode=ParseMode.HTML)

    def taxi_to_handler(self, user_id: str, address: str, full_location: str, context) -> None:

        order_id = self.user_manager.get_user_field(user_id, 'current_order_id')

        self.orders_manager.set_order_field(order_id, TAXI_TO, address)
        self.orders_manager.set_order_field(order_id, TAXI_TO_LOCATION, full_location)

        self.user_manager.set_user_field(user_id, 'current_step', TAXI_CONTACT)

        # Checking if username is hide
        user_language = self.user_manager.get_user_field(user_id, 'language')
        message_text = ALL_TEXT.get('taxi_contact').get(user_language)
        if not self.user_manager.get_user_field(user_id, 'link'):
            message_text += ALL_TEXT.get('taxi_contact').get(f'special_{user_language}')

        context.bot.send_message(chat_id=user_id,
                                 text=message_text,
                                 parse_mode=ParseMode.HTML)

    def taxi_contact_handler(self, user_id: str, user_message: str, update) -> None:

        order_id = self.user_manager.get_user_field(user_id, 'current_order_id')

        self.orders_manager.set_order_field(order_id, TAXI_CONTACT, user_message)
        self.user_manager.set_user_field(user_id, 'current_step', TAXI_COMMENT)

        # Updating contacts
        current_contacts = self.user_manager.get_user_field(user_id, 'contacts')
        if user_message not in current_contacts:
            current_contacts.append(user_message)
        self.user_manager.set_user_field(user_id, 'contacts', current_contacts)

        user_language = self.user_manager.get_user_field(user_id, 'language')
        text_comment = ALL_TEXT.get('taxi_comment')
        keyboard = [
            [
                InlineKeyboardButton(text_comment.get(f'button_{user_language}'), callback_data='no_comments')
            ]
        ]
        update.message.reply_text(text=text_comment.get(user_language),
                                  reply_markup=InlineKeyboardMarkup(keyboard),
                                  parse_mode=ParseMode.HTML)

    def taxi_comment_handler(self, user_id: str, user_message: str, context) -> None:

        order_id = self.user_manager.get_user_field(user_id, 'current_order_id')

        self.orders_manager.set_order_field(order_id, TAXI_COMMENT, user_message)

        self.user_manager.set_user_field(user_id, 'current_step', '')
        self.user_manager.set_user_field(user_id, 'current_order_id', '')

        self.orders_manager.set_order_field(order_id, 'status', 'open')

        user_language = self.user_manager.get_user_field(user_id, 'language')
        context.bot.send_message(chat_id=user_id,
                                 text=ALL_TEXT.get('open_order').get(user_language))

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

    def no_comments(self, update, context) -> None:
        
        query = update.callback_query
        query.answer()

        user_id = update.effective_chat.id
        self.taxi_comment_handler(user_id, '', context)


class TelegramHandlers:

    def __init__(self, user_manager: UserManager, menu: TelegramMenu):

        # Initializing menu
        self.menu = menu
        self.user_manager = user_manager

    def start(self, update, context) -> None:

        # Creating user
        current_user = update.effective_chat
        self.user_manager.create_user(current_user)

        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text=f'👋 <b>Привет, {current_user.full_name}!</b> 👋\n\n'
                                      f'🚕 С моей помощью можно удобно заказать такси\n'
                                      f'❓ <i>Есть вопрос или предложение? Связаться с администрацией можно по соответствующей кнопке</i>\n\n'
                                      f'📣 Хочешь быть в команде водителей? Свяжись с нами\n\n'
                                      f'Проблемы с ботом? Пропишите /start для перезапуска или свяжитесь с администрацией',
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
