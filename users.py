#---загрузка инфы о пользователях
import csv
import logging
import os
from datetime import datetime, timedelta
from functools import wraps

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    CallbackContext,
    filters,
)

from config import user_history
from storage import unique_users, save_user_history


def load_existing_users():
    """Загрузка существующих пользователей при запуске"""
    '''unique_users.clear()
    try:
        with open('unique_users.csv', 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            try:
                next(reader)  # Пропускаем заголовок
            except StopIteration:
                return
            for row in reader:
                unique_users.add(int(row[1]))
    except FileNotFoundError:
        pass'''
    try:
        with open('unique_users.csv', 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # Пропуск заголовка
            for row in reader:
                if len(row) >= 3:
                    user_id = row[1]
                    unique_users[user_id] = (row[0], row[2])
    except FileNotFoundError:
        logging.info("Файл unique_users.csv не найден, будет создан новый")

async def log_user_info(update: Update):
    user = update.effective_user
    user_id = user.id
    username = user.username or "N/A"

    # Создаем запись с временной меткой
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    record = [timestamp, user_id, username]

    # Записываем в CSV файл
    with open('users_log.csv', 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        # Если файл пустой - записываем заголовки
        if f.tell() == 0:
            writer.writerow(["Дата", "User ID", "Username"])
        writer.writerow(record)

async def log_unique_users(update: Update):
    user = update.effective_user
    uid = user.id
    uname = user.username or 'не указан'

    # Загружаем актуальные данные из файла
    existing_users = set()
    if os.path.exists('unique_users.csv'):
        with open('unique_users.csv', 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            '''next(reader)  # Пропускаем заголовок'''
            try:
                next(reader)  # Пропускаем заголовок
            except StopIteration:
                pass
            else:
                for row in reader:
                    if row:  # Проверка на пустые строки
                        existing_users.add(int(row[1]))

    # Если пользователь новый
    if uid not in existing_users:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Обновляем память и файл
        unique_users[uid] = (now, uname)

        # Режим дописывания (добавляем только новые записи)
        with open('unique_users.csv', 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if f.tell() == 0:
                writer.writerow(['Дата регистрации', 'User ID', 'Username'])
            writer.writerow([now, uid, uname])

#---логирование всех вызовов
def log_function(function_type: str):
    """Декоратор для логирования вызовов функций"""

    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, context: CallbackContext):
            # Логирование перед выполнением функции
            await log_function_call(update, function_type)

            # Вызов оригинальной функции
            return await func(update, context)

        return wrapper

    return decorator

async def log_function_call(update: Update, function_type: str):
    """Логирует вызов функции в файл"""
    user = update.effective_user
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    user_id = user.id if user else 0
    username = user.username if user and user.username else 'не указан'

    with open('function_logs.csv', 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if f.tell() == 0:
            writer.writerow(['Дата', 'User ID', 'Username', 'Function Type'])

        writer.writerow([timestamp, user_id, username, function_type])

def update_history(chat_id: int, ticker: str):
    lst = user_history.setdefault(str(chat_id), [])
    if ticker in lst: lst.remove(ticker)
    lst.insert(0, ticker)
    user_history[str(chat_id)] = lst[:5]
    save_user_history(user_history)