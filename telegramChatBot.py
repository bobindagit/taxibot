import json
import logging
from telegram import Update, Chat, ChatMember, ParseMode, ChatMemberUpdated
from telegram.ext import (
    Updater,
    CallbackContext,
    ChatMemberHandler,
    CallbackQueryHandler
)


class TelegramChatBot:

    def __init__(self, database):

        # Logging
        logging.basicConfig(
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
        )

        self.logger = logging.getLogger(__name__)

        # Reading file and getting settings
        with open('settings.json', 'r') as file:
            file_data = json.load(file)
            bot_token = file_data.get('bot_token_drivers')
            self.bot_chat_id = file_data.get('bot_group_id')
            file.close()

        self.database = database

        # Main telegram UPDATER
        self.updater = Updater(token=bot_token, use_context=True)
        self.dispatcher = self.updater.dispatcher

        # Handlers
        self.dispatcher.add_handler(ChatMemberHandler(self.track_chats, ChatMemberHandler.MY_CHAT_MEMBER))
        # Menu handlers
        self.dispatcher.add_handler(CallbackQueryHandler(self.accept_order, pattern='accept_order'))

        # Starting the bot
        self.updater.start_polling(allowed_updates=Update.ALL_TYPES)

        print('Telegram chat bot initialized!')

    def track_chats(self, update: Update, context: CallbackContext) -> None:

        """Tracks the chats the bot is in."""

        result = self.extract_status_change(update.my_chat_member)
        if result is None:
            return
        was_member, is_member = result

        # Let's check who is responsible for the change
        cause_name = update.effective_user.full_name

        # Handle chat types differently:
        chat = update.effective_chat
        if chat.type == Chat.PRIVATE:
            if not was_member and is_member:
                self.logger.info("%s started the bot", cause_name)
                context.bot_data.setdefault("user_ids", set()).add(chat.id)
            elif was_member and not is_member:
                self.logger.info("%s blocked the bot", cause_name)
                context.bot_data.setdefault("user_ids", set()).discard(chat.id)
        elif chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
            if not was_member and is_member:
                self.logger.info("%s added the bot to the group %s", cause_name, chat.title)
                context.bot_data.setdefault("group_ids", set()).add(chat.id)
            elif was_member and not is_member:
                self.logger.info("%s removed the bot from the group %s", cause_name, chat.title)
                context.bot_data.setdefault("group_ids", set()).discard(chat.id)
        else:
            if not was_member and is_member:
                self.logger.info("%s added the bot to the channel %s", cause_name, chat.title)
                context.bot_data.setdefault("channel_ids", set()).add(chat.id)
            elif was_member and not is_member:
                self.logger.info("%s removed the bot from the channel %s", cause_name, chat.title)
                context.bot_data.setdefault("channel_ids", set()).discard(chat.id)

    def extract_status_change(self, chat_member_update: ChatMemberUpdated,) -> tuple:

        """Takes a ChatMemberUpdated instance and extracts whether the 'old_chat_member' was a member
        of the chat and whether the 'new_chat_member' is a member of the chat. Returns None, if
        the status didn't change.
        """
        status_change = chat_member_update.difference().get("status")
        old_is_member, new_is_member = chat_member_update.difference().get("is_member", (None, None))

        if status_change is None:
            return None

        old_status, new_status = status_change
        was_member = (
            old_status
            in [
                ChatMember.MEMBER,
                ChatMember.CREATOR,
                ChatMember.ADMINISTRATOR,
            ]
            or (old_status == ChatMember.RESTRICTED and old_is_member is True)
        )
        is_member = (
            new_status
            in [
                ChatMember.MEMBER,
                ChatMember.CREATOR,
                ChatMember.ADMINISTRATOR,
            ]
            or (new_status == ChatMember.RESTRICTED and new_is_member is True)
        )

        return was_member, is_member

    def get_opened_orders(self) -> list:
        return self.database.db_orders.find({'status': 'open', 'drivers_notification_sent': False})

    def set_notification_flag(self, order_id: str) -> None:
        value_to_update = {"$set": {'drivers_notification_sent': True}}
        self.database.db_orders.update({'order_id': order_id}, value_to_update)

    def accept_order(self, update, context) -> None:
        message = update.effective_message.text_html
        order_id = message.partition('</b>')[2].partition('\n')[0].replace('№', '')
        driver_name = update.effective_user.name
        # Updating order status
        value_to_update = {"$set": {'status': "accepted"}}
        self.database.db_orders.update({'order_id': int(order_id)}, value_to_update)
        # Updating order driver's name
        value_to_update = {"$set": {'driver_name': driver_name}}
        self.database.db_orders.update({'order_id': int(order_id)}, value_to_update)
        # Message to chat
        query = update.callback_query
        query.answer()
        query.edit_message_text(
            text=f'{message}\n\n'
                 f'<b>Принят! Водитель: {driver_name}</b>',
            parse_mode=ParseMode.HTML)


if __name__ == '__main__':
    print('Only for import!')
