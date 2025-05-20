# Глобальные структуры
from collections import defaultdict
TOKEN = "7828449429:AAGIxxjqzT2moFMQT-IxoxpQP3jB_JDDtKo"

DEVELOPER_KEY = "111"

DEVELOPERS_FILE = "developers.csv"

FEEDBACK_URL = "https://docs.google.com/forms/d/e/1FAIpQLSeiqCu8jqbCxcoAidfPe4fa35AW1JzjbY0JJP4KqOQaLl5gWA/viewform?usp=header"

#google api
CREDENTIALS_FILE = "creds.json"
spreadsheet_ids= {
    "trackings": "1uZrt9P1Poiz3E07zzNQW6FDiYWggu5whq415tAzf8dw",
    "developers": "",
    "func_logs": "",
    "notis": "",
    "users_log": ""
}

price_history = {}
active_trackings = {}
timeframe_settings = {}
user_history = {}
unique_users = {}
valid_tickers = set()