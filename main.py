from database import Database
from telegramBot import TelegramBot
from telegramChatBot import TelegramChatBot


def main():

    database = Database()

    telegram_bot = TelegramBot(database)
    telegram_chat_bot = TelegramChatBot(database)


if __name__ == '__main__':
    main()
