#режим разработчика
import csv
import logging
import os

import pandas as pd
from apscheduler.triggers.interval import IntervalTrigger
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
from datetime import datetime, timedelta

from storage import active_trackings, unique_users

#режим разработчика
DEVELOPER_KEY = "111"  # Замените на реальный ключ
DEVELOPERS_FILE = "developers.csv"

def is_developer(user_id: int) -> bool:
    try:
        with open(DEVELOPERS_FILE, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)
            developers = [int(row[1]) for row in reader]
            logging.info(f"Developers list: {developers}")  # Логируем список
            return user_id in developers
    except Exception as e:
        logging.error(f"Developer check error: {e}")
        return False

async def dev_menu(update: Update, context: CallbackContext):
    q = update.callback_query
    await q.answer()

    if not is_developer(q.from_user.id):
        await q.edit_message_text("⛔ Доступ запрещен")
        return

    buttons = [
        [InlineKeyboardButton("📊 Статистика использования", callback_data="dev_stats")],
        [InlineKeyboardButton("⚙️ Управление задачами", callback_data="jobs_page_0")],
        [InlineKeyboardButton("👥 Список разработчиков", callback_data="dev_list")],
        [InlineKeyboardButton("👥 Уникальные пользователи", callback_data="show_unique_users")],
        [InlineKeyboardButton("📈 Анализ логов", callback_data="dev_analyze")],
        [InlineKeyboardButton("📜 Активные трекеры", callback_data="trackers_page_0")],
        [InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")]
    ]

    await q.edit_message_text(
        text="💻 Меню разработчика",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def dev_stats(update: Update, context: CallbackContext):
    q = update.callback_query
    await q.answer()

    # Сбор статистики
    stats = await generate_usage_stats()

    # Формирование сообщения
    msg = (
        "📊 Статистика использования:\n\n"
        f"👥 Активные пользователи:\n"
        f"- За день: {stats['users_day']}\n"
        f"- За неделю: {stats['users_week']}\n"
        f"- За месяц: {stats['users_month']}\n\n"

        f"🔔 Трекеры:\n"
        f"- Регулярные: {stats['regular_trackers']}\n"
        f"- Пороговые: {stats['threshold_trackers']}\n"
        f"- Топ тикеры: {', '.join(stats['top_tickers'])}\n\n"

        f"⚙ Нагрузка:\n"
        f"- Среднее время ответа: {stats['avg_response_time']} сек\n"
        f"- Вызовов/час: {stats['calls_per_hour']}"
    )

    # Кнопка возврата
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="dev_menu")]])

    await q.edit_message_text(text=msg, reply_markup=kb)


async def generate_usage_stats():
    now = datetime.now()
    stats = {
        'users_day': 0,
        'users_week': 0,
        'users_month': 0,
        'regular_trackers': 0,
        'threshold_trackers': 0,
        'top_tickers': [],
        'avg_response_time': 0.0,
        'calls_per_hour': 0
    }

    # Статистика пользователей
    try:
        with open('unique_users.csv', 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # Пропуск заголовка

            for row in reader:
                reg_date = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                if (now - reg_date).days <= 1: stats['users_day'] += 1
                if (now - reg_date).days <= 7: stats['users_week'] += 1
                if (now - reg_date).days <= 30: stats['users_month'] += 1
    except FileNotFoundError:
        pass

    # Статистика трекеров
    ticker_counts = {}
    for user_data in active_trackings.values():
        for ticker, settings in user_data.items():
            if 'regular' in settings: stats['regular_trackers'] += 1
            if 'threshold' in settings: stats['threshold_trackers'] += 1
            ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1

    stats['top_tickers'] = sorted(ticker_counts, key=lambda x: ticker_counts[x], reverse=True)[:5]

    # Статистика нагрузки
    try:
        with open('function_logs.csv', 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # Пропуск заголовка

            timestamps = []
            for row in reader:
                timestamps.append(datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S"))

            if timestamps:
                time_diff = (max(timestamps) - min(timestamps)).total_seconds()
                stats['avg_response_time'] = round(time_diff / len(timestamps), 2)
                stats['calls_per_hour'] = round(len(timestamps) / (time_diff / 3600) if time_diff > 0 else 0)
    except FileNotFoundError:
        pass

    return stats

async def show_developers(update: Update, context: CallbackContext):
    q = update.callback_query
    await q.answer()
    logging.info("--- START SHOW DEVELOPERS HANDLER ---")

    try:
        logging.info(f"Trying to open developers file: {os.path.abspath(DEVELOPERS_FILE)}")
        if not os.path.exists(DEVELOPERS_FILE):
            raise FileNotFoundError

        with open(DEVELOPERS_FILE, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # Пропускаем заголовок
            developers = list(reader)

            if not developers:
                msg = "🚫 Список разработчиков пуст"
            else:
                msg = "👨💻 Список разработчиков:\n\n" + "\n".join(
                    [f"{i+1}. {row[0]} | ID: `{row[1]}` | @{row[2]}"
                     for i, row in enumerate(developers)]
                )

    except FileNotFoundError:
        msg = "❌ Файл с разработчиками не найден"
        logging.error("Файл developers.csv отсутствует")

    except Exception as e:
        msg = "⚠️ Ошибка при чтении списка"
        logging.error(f"Ошибка в show_developers: {str(e)}")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Назад", callback_data="dev_menu")]
    ])

    try:
        await q.edit_message_text(
            text=msg,
            reply_markup=kb,
            parse_mode=None
        )
    except Exception as e:
        logging.error(f"Ошибка отправки сообщения: {str(e)}")


async def show_unique_users(update: Update, context: CallbackContext):
    q = update.callback_query
    await q.answer()

    try:
        with open('unique_users.csv', 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # Пропуск заголовка

            users = []
            for row in reader:
                users.append(f"{row[0]} | ID: {row[1]} | @{row[2] or 'нет'}")

            if not users:
                msg = "🚫 Нет зарегистрированных пользователей"
            else:
                msg = "👤 Уникальные пользователи:\n\n" + "\n".join(users[:50])  # Первые 50 записей

                if len(users) > 50:
                    msg += "\n\n...и еще {} пользователей".format(len(users) - 50)

    except FileNotFoundError:
        msg = "❌ Файл с пользователями не найден"
    except Exception as e:
        msg = f"⚠️ Ошибка: {str(e)}"
        logging.error(f"Error in show_unique_users: {e}")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Назад", callback_data="dev_menu")]
    ])

    await q.edit_message_text(
        text=msg,
        reply_markup=kb,
        parse_mode="HTML"
    )

async def dev_analyze(update: Update, context: CallbackContext):
    q = update.callback_query
    await q.answer()

    try:
        df = pd.read_csv('function_logs.csv')
        analysis = df.groupby(['Function Type', 'Username']).size().to_string()
        msg = f"📊 Анализ использования:\n\n<pre>{analysis}</pre>"
    except Exception as e:
        msg = f"❌ Ошибка анализа: {str(e)}"

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="dev_menu")]])
    await q.edit_message_text(text=msg, reply_markup=kb, parse_mode="HTML")

async def show_active_trackings(update: Update, context: CallbackContext):
    q = update.callback_query
    await q.answer()

    page = int(q.data.split("_")[-1])
    per_page = 30
    all_trackers = []

    try:
        with open("trackings.txt", "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                parts = line.split("-")
                if len(parts) not in [4, 5]:
                    continue

                chat_id = parts[0]
                tracking_type = parts[1]
                ticker = parts[2]

                if tracking_type == "follow_stock":
                    threshold = parts[3]
                    interval = parts[4]
                    tracker_info = f"👤 {chat_id} | {ticker} | Порог: {threshold}% каждые {interval} мин"
                elif tracking_type == "set_stock":
                    interval = parts[3]
                    tracker_info = f"👤 {chat_id} | {ticker} | Регулярные: каждые {interval} мин"
                else:
                    continue

                all_trackers.append(tracker_info)

    except FileNotFoundError:
        await q.edit_message_text("📭 Файл с трекерами не найден")
        return

    # Пагинация
    total_pages = (len(all_trackers) // per_page) + 1
    start = page * per_page
    end = start + per_page
    current_page = all_trackers[start:end]

    # Формирование сообщения
    msg_header = f"📜 Активные трекеры (стр. {page + 1}/{total_pages}):\n\n"
    msg = msg_header + "\n".join(current_page) if current_page else "🚫 Нет активных трекеров"

    # Создание кнопок навигации
    buttons = []
    if len(all_trackers) > per_page:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data=f"trackers_page_{page - 1}"))
        if end < len(all_trackers):
            nav_buttons.append(InlineKeyboardButton("Вперед ▶️", callback_data=f"trackers_page_{page + 1}"))
        if nav_buttons:
            buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton("🔙 В меню", callback_data="dev_menu")])

    await q.edit_message_text(
        text=msg,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML"
    )

async def show_jobs(update: Update, context: CallbackContext):
    q = update.callback_query
    await q.answer()

    page = int(q.data.split("_")[-1])
    per_page = 10
    jobs = []

    # Читаем актуальные данные из файла
    with open("trackings.txt", "r") as f:
        active_trackings = {line.strip() for line in f if line.strip()}

    for job in context.application.job_queue.jobs():
        # Определяем тип задачи
        job_type = "Неизвестный тип"
        if "send_price_" in job.name:
            job_type = "📅 Регулярное обновление"
        elif "follow" in job.name:
            job_type = "🚨 Проверка порога"
        elif "cleanup_archive_job" in job.name:
            job_type = "🔄 Фоновый сбор"

        # Получаем интервал
        interval = "Однократная"
        if job.job and isinstance(job.job.trigger, IntervalTrigger):
            interval_sec = job.job.trigger.interval.total_seconds()
            interval = f"{interval_sec} сек"

        # Статус задачи
        status = "🟢 Активна" if job.enabled else "🔴 Остановлена"

        jobs.append(
            f"{job_type}\n{job.name}\nИнтервал: {interval} | Статус: {status}"
        )

    # Пагинация
    total_pages = (len(jobs) // per_page) + 1
    start = page * per_page
    end = start + per_page
    current_page = jobs[start:end]

    # Формируем сообщение
    msg = f"⚙️ Активные задачи (стр. {page + 1}/{total_pages}):\n\n" + "\n\n".join(current_page)

    # Создаем клавиатуру
    buttons = []
    for i, job in enumerate(context.application.job_queue.jobs()[start:end]):
        buttons.append([InlineKeyboardButton(
            f"Управление {i + 1}",
            callback_data=f"job_action_{page}_{i}_{job.name}"
        )])

    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data=f"jobs_page_{page - 1}"))
    if end < len(jobs):
        nav_buttons.append(InlineKeyboardButton("Вперед ▶️", callback_data=f"jobs_page_{page + 1}"))
    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="dev_menu")])

    await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_job_action(update: Update, context: CallbackContext):
    q = update.callback_query
    await q.answer()

    _, page, idx, job_name = q.data.split("_", 3)
    job = next((j for j in context.application.job_queue.jobs() if j.name == job_name), None)

    if not job:
        await q.edit_message_text("❌ Задача не найдена")
        return

    buttons = [
        [InlineKeyboardButton("⏸ Остановить" if job.enabled else "▶️ Возобновить",
                              callback_data=f"toggle_{job_name}")],
        [InlineKeyboardButton("▶️ Запустить сейчас", callback_data=f"run_{job_name}")],
        [InlineKeyboardButton("🔙 К списку", callback_data=f"jobs_page_{page}")]
    ]

    await q.edit_message_text(
        f"Управление задачей:\n{job.name}\nСтатус: {'🟢 Активна' if job.enabled else '🔴 Остановлена'}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def execute_job_action(update: Update, context: CallbackContext):
    q = update.callback_query
    await q.answer()

    action, job_name = q.data.split("_", 1)
    job = next((j for j in context.application.job_queue.jobs() if j.name == job_name), None)

    if not job:
        await q.edit_message_text("❌ Задача не найдена")
        return

    if action == "toggle":
        job.enabled = not job.enabled
        status = "остановлена" if not job.enabled else "возобновлена"
        await q.answer(f"✅ Задача {status}")
    elif action == "run":
        job.run(context.application)
        await q.answer("✅ Задача запущена вручную")

    # Обновляем интерфейс
    await show_jobs(update, context)