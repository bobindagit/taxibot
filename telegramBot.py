import json
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler
from telegram import KeyboardButton, ReplyKeyboardMarkup, ParseMode, InlineKeyboardButton, InlineKeyboardMarkup


# STEP NAMES
QUESTION = 'question'
TAXI_FROM = 'from'
TAXI_TO = 'to'
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
        self.dispatcher.add_handler(MessageHandler(Filters.command, handlers.unknown))

        self.dispatcher.add_handler(CallbackQueryHandler(self.orders_manager.decline_order, pattern='decline_order'))

        # Starting the bot
        self.updater.start_polling()

        print('Telegram bot initialized!')


class UserManager:

    def __init__(self, db_user_info):
        self.db_user_info = db_user_info

    def add_user(self, user_info: dict) -> None:
        user_id = user_info.get('user_id')
        self.db_user_info.update({'user_id': user_id}, user_info, upsert=True)

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

    def set_order_field(self, order_id: str, order_field: str, new_value: str) -> None:
        value_to_update = {"$set": {order_field: new_value}}
        self.db_orders.update({'order_id': order_id}, value_to_update)

    def get_order_info(self, order_id: str) -> dict:
        return self.db_orders.find({'order_id': order_id})[0]

    def get_open_orders(self, user_id: str) -> list:
        return self.db_orders.find({'user_id': user_id, 'status': 'open'})

    def generate_order_message(self, order: dict) -> str:
        return f'[№{order.get("order_id")}] {order.get(TAXI_FROM)} -> {order.get(TAXI_TO)} ({order.get(TAXI_TIME)})'

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
            TAXI_TO: '',
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

        self.user_manager = user_manager
        self.orders_manager = orders_manager

        # Main menu buttons
        main_keyboard = [
            [KeyboardButton(text='Заказать такси'),
             KeyboardButton(text='Активные заказы'),
             KeyboardButton(text='Вопрос / Предложение')]
        ]
        self.reply_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True, one_time_keyboard=False)

    def menu_message(self, update, context) -> None:

        user_message = update.message.text.upper()
        user_id = update.effective_chat.id

        current_step = self.user_manager.get_user_field(user_id, 'current_step')

        if user_message == 'ЗАКАЗАТЬ ТАКСИ':
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text="Откуда Вас забрать?")
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
        elif user_message == 'ВОПРОС / ПРЕДЛОЖЕНИЕ':
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text="Напишите Ваш вопрос или предложение")
            self.user_manager.set_user_field(user_id, 'current_step', QUESTION)
        elif len(current_step) != 0:
            self.message_handler(user_id, user_message, current_step, context)
        else:
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text="Я не знаю такой команды")

    def message_handler(self, user_id: str, user_message: str, current_step: str, context) -> None:

        if current_step == QUESTION:
            user_name = self.user_manager.get_user_field(user_id, 'link').replace('https://t.me/', '@')
            question = f'<b>Поступил вопрос/предложение от {user_name}</b>\n\n' \
                       f'{user_message}'
            # bobtb
            context.bot.send_message(chat_id='360152058',
                                     text=question,
                                     parse_mode=ParseMode.HTML)
            # # metallity
            # context.bot.send_message(chat_id='496337433',
            #                          text=question,
            #                          parse_mode=ParseMode.HTML)
        elif current_step == TAXI_FROM:
            user_name = self.user_manager.get_user_field(user_id, 'link')
            order_id = self.orders_manager.create_order(user_id, user_name.replace('https://t.me/', ''))
            self.user_manager.set_user_field(user_id, 'current_order_id', order_id)
            self.orders_manager.set_order_field(order_id, TAXI_FROM, user_message)
            self.user_manager.set_user_field(user_id, 'current_step', TAXI_TO)
            context.bot.send_message(chat_id=user_id,
                                     text="Куда Вас отвезти?")
        elif current_step == TAXI_TO:
            order_id = self.user_manager.get_user_field(user_id, 'current_order_id')
            self.orders_manager.set_order_field(order_id, TAXI_TO, user_message)
            self.user_manager.set_user_field(user_id, 'current_step', TAXI_TIME)
            context.bot.send_message(chat_id=user_id,
                                     text="Во сколько Вас забрать? (Пример: 17:30)")
        elif current_step == TAXI_TIME:
            order_id = self.user_manager.get_user_field(user_id, 'current_order_id')
            self.orders_manager.set_order_field(order_id, TAXI_TIME, user_message)
            self.user_manager.set_user_field(user_id, 'current_step', TAXI_CONTACT)
            context.bot.send_message(chat_id=user_id,
                                     text="Как с Вами связаться?")
        elif current_step == TAXI_CONTACT:
            order_id = self.user_manager.get_user_field(user_id, 'current_order_id')
            self.orders_manager.set_order_field(order_id, TAXI_CONTACT, user_message)
            self.user_manager.set_user_field(user_id, 'current_step', '')
            self.user_manager.set_user_field(user_id, 'current_order_id', '')
            current_contacts = self.user_manager.get_user_field(user_id, 'contacts')
            if user_message not in current_contacts:
                current_contacts.append(user_message)
            self.user_manager.set_user_field(user_id, 'contacts', current_contacts)
            self.orders_manager.set_order_field(order_id, 'status', 'open')
            context.bot.send_message(chat_id=user_id,
                                     text="Заявка отправлена! Ожидайте ответа")


class TelegramHandlers:

    def __init__(self, user_manager: UserManager, menu: TelegramMenu):

        # Initializing menu
        self.menu = menu
        self.user_manager = user_manager

    def start(self, update, context) -> None:

        # Adding user ID
        current_user = update.effective_chat
        user_info = {'user_id': current_user.id,
                     'full_name': current_user.full_name,
                     'link': current_user.link,
                     'current_step': '',
                     'current_order_id': '',
                     'contacts': []}
        self.user_manager.add_user(user_info)

        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text="Привет! С моей помощью можно удобно заказать такси!",
                                 reply_markup=self.menu.reply_markup)

    def stop(self, update, context) -> None:

        self.user_manager.remove_user(update.effective_chat.id)

        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text='Чтобы вновь пользоваться мной - введи /start')

    def unknown(self, update, context) -> None:

        context.bot.send_message(chat_id=update.effective_chat.id,
                                 text="Я не знаю такой команды")


if __name__ == '__main__':
    print('Only for import!')
