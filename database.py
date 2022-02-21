import json
import certifi
from pymongo import MongoClient


class Database:

    def __init__(self):

        # Reading file and getting settings
        with open('settings.json', 'r') as file:
            file_data = json.load(file)
            client = MongoClient(file_data.get('mongodb_connection'), tlsCAFile=certifi.where())
            file.close()

        # Getting all resources
        self.db_user_info = client.taxi_bot['taxi_user_info']
        self.db_orders = client.taxi_bot['taxi_orders']
        self.db_blacklist = client.taxi_bot['taxi_blacklist']


if __name__ == '__main__':
    print('Only for import!')
