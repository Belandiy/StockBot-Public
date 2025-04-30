import os
import ssl
import logging
import asyncio
import time
import random
from datetime import datetime, timedelta
from io import BytesIO
from PIL import Image

from collections import defaultdict

import watchdog
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from watchdog.observers import Observer
from webdriver_manager.chrome import ChromeDriverManager
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
import csv

from config import (
    price_history, active_trackings, timeframe_settings,
    user_history, unique_users, valid_tickers
)
from storage import (
    active_trackings, price_history, timeframe_settings, user_history, unique_users,
    log_notification, save_tracking, remove_tracking, load_trackings, save_timeframe, load_timeframes,
    save_price_to_archive, get_price_from_archive, cleanup_archive_files, check_price_cache,
    save_user_history, load_user_history, TRACKING_FILE
)
from localDev import (
    is_developer, dev_menu, dev_stats, generate_usage_stats,
    show_developers, show_unique_users, dev_analyze, show_active_trackings,
    show_jobs, handle_job_action, execute_job_action
)
from users import (
    load_existing_users, log_user_info, log_unique_users, log_function, log_function_call, update_history
)
from archive import (
    cleanup_archive_job, TickerFileHandler, load_tickers, is_ticker_valid
)
from screenshot import capture_chart_screenshot


# SSL & logging
ssl._create_default_https_context = ssl._create_unverified_context
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# Bot token
TOKEN = "7956229366:AAEZ5rJbZo5O5bJPxLGh3oB0PDlgRgEhtLg"

#режим разработчика
DEVELOPER_KEY = "111"  # Замените на реальный ключ
DEVELOPERS_FILE = "developers.csv"

FEEDBACK_URL = "https://docs.google.com/forms/d/e/1FAIpQLSeiqCu8jqbCxcoAidfPe4fa35AW1JzjbY0JJP4KqOQaLl5gWA/viewform?usp=header"  #обратная связь



'''# Глобальные структуры
price_history = cn.price_history
active_trackings = cn.active_trackings
timeframe_settings = cn.timeframe_settings
user_history = cn.user_history
unique_users = cn.unique_users  # mapping user_id -> (registration_date, username)
valid_tickers = cn.valid_tickers'''

# Файлы тикеров
TICKERS_RU_FILE = "tickers-RU.txt"
TICKERS_USA_FILE = "tickers-USA.txt"
TICKERS_CRYPTO_FILE = "tickers-crypto.txt"
TICKERS_ETF = "tickers_ETF.txt"
TICKERS_INDEXES = "tickers_indexes.txt"


# Conversation states
(
    MAIN_MENU, REGULAR_SET_TICKER, REGULAR_SET_INTERVAL,
    THRESHOLD_SET_TICKER, THRESHOLD_SET_PERCENT, MANUAL_THRESHOLD_INPUT_PERCENT, THRESHOLD_SET_INTERVAL,
    DELETE_MENU, DELETE_REGULAR, DELETE_THRESHOLD,
    TIMEFRAME_CHOOSE,
    MANUAL_TICKER_INPUT_REGULAR, MANUAL_TICKER_INPUT_THRESHOLD,
    DEV_MENU, DEV_STATS, DEV_ANALYZE, DEV_LIST, TRACKERS_LIST
) = range(18)


# Скриншот графика
'''async def capture_chart_screenshot(ticker: str, chat_id: int) -> BytesIO | None:
    tf = timeframe_settings.get(chat_id, "1")
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1920,1080")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    try:
        driver.get(f"https://www.tradingview.com/chart/?symbol={ticker}&interval={tf}")
        WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.chart-container")))
        await asyncio.sleep(3)
        chart = driver.find_element(By.CSS_SELECTOR, "div.chart-container")
        png = chart.screenshot_as_png
        buf = BytesIO()
        Image.open(BytesIO(png)).save(buf, format="PNG")
        buf.seek(0)
        return buf
    except Exception as e:
        logging.error(f"Screenshot error: {e}")
        return None
    finally:
        driver.quit()'''


#подгрузка новых тикеров, если они есть
observer = Observer()
observer.schedule(TickerFileHandler(), path=".", recursive=False)
observer.start()








# Парсер цены
def sync_get_stock_price(ticker: str) -> float:
    opts = Options(); opts.add_argument("--headless=new")
    drv = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    try:
        drv.get(f"https://www.tradingview.com/symbols/{ticker}/")
        WebDriverWait(drv, 5).until(EC.presence_of_element_located(
            (By.XPATH, "//div[contains(@class,'lastContainer')]//span[contains(@class,'last')]")
        ))
        text = drv.find_element(By.XPATH,
            "//div[contains(@class,'lastContainer')]//span[contains(@class,'last')]"
        ).text.replace(",", "")
        price = float(text)
        save_price_to_archive(ticker, price)
        return price
    except Exception as e:
        logging.error(f"Error fetching {ticker}: {e}")
        return None
    finally:
        drv.quit()
        time.sleep(random.uniform(2,5))

async def fetch_fresh_price(ticker: str) -> float:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sync_get_stock_price, ticker)

async def get_stock_price(ticker: str) -> float:
    p = get_price_from_archive(ticker, datetime.now())
    if p is not None:
        return p
    p = check_price_cache(ticker)
    if p is not None:
        return p
    return await fetch_fresh_price(ticker)

'''def update_history(chat_id: int, ticker: str):
    lst = user_history.setdefault(str(chat_id), [])
    if ticker in lst: lst.remove(ticker)
    lst.insert(0, ticker)
    user_history[str(chat_id)] = lst[:5]
    save_user_history(user_history)'''






# Регистрация задач из storage.load_trackings
def start_job(application, chat_id, ticker, job_type, interval, threshold=None):
    if job_type == "regular":
        application.job_queue.run_repeating(
            send_price_update, interval*60,
            data={"chat_id":chat_id, "ticker":ticker, "interval":interval},
            name=f"send_price_{chat_id}_{ticker}"
        )
        active_trackings.setdefault(chat_id, {})[ticker] = {"regular":{"interval":interval}}
    else:
        application.job_queue.run_repeating(
            check_price_changes, interval*60,
            data={"chat_id":chat_id, "ticker":ticker, "threshold":threshold, "interval":interval},
            name=f"follow_{chat_id}_{ticker}"
        )
        active_trackings.setdefault(chat_id, {})[ticker] = {"threshold":{"threshold":threshold, "interval":interval}}

# ————————————— Обработчики —————————————

'''async def start(update: Update, context: CallbackContext):
    kb = [
        [InlineKeyboardButton("📅 Регулярные уведомления", callback_data="reg_notif")],
        [InlineKeyboardButton("🚨 Отслеживание изменений", callback_data="threshold_notif")],
        [InlineKeyboardButton("🗑 Удалить отслеживание", callback_data="delete_menu")],
        [InlineKeyboardButton("⏱ Настройка таймфрейма", callback_data="set_timeframe")],
        [InlineKeyboardButton("📋 Активные отслеживания", callback_data="list_trackings")],
    ]
    await update.message.reply_text("📊 Главное меню:", reply_markup=InlineKeyboardMarkup(kb))
    return MAIN_MENU'''
@log_function('main_menu')
async def start(update: Update, context: CallbackContext):
    await log_user_info(update)
    await log_unique_users(update)

    kb = [
        [InlineKeyboardButton("📅 Регулярные уведомления", callback_data="reg_notif")],
        [InlineKeyboardButton("🚨 Отслеживание изменений", callback_data="threshold_notif")],
        [InlineKeyboardButton("🗑 Удалить отслеживание", callback_data="delete_menu")],
        [InlineKeyboardButton("⏱ Настройка таймфрейма", callback_data="set_timeframe")],
        [InlineKeyboardButton("📋 Активные отслеживания", callback_data="list_trackings")],
        [InlineKeyboardButton("📝 Обратная связь", url=FEEDBACK_URL)]
    ]

    # Добавляем кнопку разработчика если пользователь авторизован
    if is_developer(update.effective_user.id):
        kb.append([InlineKeyboardButton("💻 Меню разработчика", callback_data="dev_menu")])

    reply_markup = InlineKeyboardMarkup(kb)

    # Проверяем тип апдейта (сообщение или callback)
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(text="📊 Главное меню:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("📊 Главное меню:", reply_markup=reply_markup)

    return MAIN_MENU

async def reload_tickers(update: Update, context: CallbackContext):
    load_tickers()
    await update.message.reply_text(f"✅ Тикеры обновлены ({len(valid_tickers)})")

@log_function('timeframe_choose')
async def timeframe_choose(update: Update, context: CallbackContext):
    q = update.callback_query; await q.answer()
    buttons = [
        [InlineKeyboardButton("1 мин", callback_data="tf_1"), InlineKeyboardButton("5 мин", callback_data="tf_5")],
        [InlineKeyboardButton("15 мин", callback_data="tf_15"), InlineKeyboardButton("1 час", callback_data="tf_60")],
        [InlineKeyboardButton("4 часа", callback_data="tf_240"), InlineKeyboardButton("1 день", callback_data="tf_1D")],
        [InlineKeyboardButton("« Назад", callback_data="main_menu")],
    ]
    await q.edit_message_text("⏱ Выберите таймфрейм:", reply_markup=InlineKeyboardMarkup(buttons))
    return TIMEFRAME_CHOOSE

async def set_timeframe(update: Update, context: CallbackContext):
    q = update.callback_query; await q.answer()
    val = q.data.split("_",1)[1]
    timeframe_settings[ q.message.chat.id ] = val
    save_timeframe(q.message.chat.id, val)
    await q.edit_message_text(f"✅ Таймфрейм установлен: {val}")
    return ConversationHandler.END

'''async def regular_set_ticker(update: Update, context: CallbackContext):
    q = update.callback_query; await q.answer()
    tickers = sorted(valid_tickers)[:5]
    buttons = [[InlineKeyboardButton(t, callback_data=f"reg_ticker_{t}")] for t in tickers]
    buttons += [[InlineKeyboardButton("📝 Ручной ввод", callback_data="manual_ticker_reg")],
                [InlineKeyboardButton("« Назад", callback_data="cancel")]]
    await q.edit_message_text("📋 Выберите тикер:", reply_markup=InlineKeyboardMarkup(buttons))
    return REGULAR_SET_TICKER'''
@log_function('regular_set_ticker')
async def regular_set_ticker(update: Update, context: CallbackContext):
    q = update.callback_query; await q.answer()
    chat_id = q.message.chat.id
    history = user_history.get(str(chat_id), [])
    recent = history[:5]
    buttons = [[InlineKeyboardButton(t, callback_data=f"reg_ticker_{t}")] for t in recent]
    buttons.append([InlineKeyboardButton("📝 Ручной ввод", callback_data="manual_ticker_reg")])
    buttons.append([InlineKeyboardButton("« Назад", callback_data='main_menu')])
    await q.edit_message_text("📋 Ваши последние тикеры:", reply_markup=InlineKeyboardMarkup(buttons))
    return REGULAR_SET_TICKER

@log_function('manual_ticker_input')
async def manual_ticker_input(update: Update, context: CallbackContext):
    q = update.callback_query; await q.answer()
    typ = q.data.split("_")[-1]  # reg или thr
    context.user_data["tracking_type"] = typ
    await q.edit_message_text("📝 Введите тикер вручную:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Отмена", callback_data="cancel")]]))
    return MANUAL_TICKER_INPUT_REGULAR if typ=="reg" else MANUAL_TICKER_INPUT_THRESHOLD

@log_function('handle_manual_ticker')
async def handle_manual_ticker(update: Update, context: CallbackContext):
    txt = update.message.text.strip().upper()
    typ = context.user_data.get("tracking_type")

    # Проверка на ключ разработчика
    if txt == DEVELOPER_KEY:
        user = update.effective_user
        if is_developer(user.id):
            await update.message.reply_text("🔓 Вы уже разработчик!")
            return await start(update, context)

        # Запись в файл разработчиков
        with open(DEVELOPERS_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if f.tell() == 0:
                writer.writerow(["Дата", "User ID", "Username"])
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                user.id,
                user.username or "N/A"
            ])
        await update.message.reply_text("🔓 Режим разработчика активирован!")
        return await start(update, context)


    if not is_ticker_valid(txt):
        await update.message.reply_text("❌ Тикер не найден, попробуйте ещё раз:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Отмена", callback_data="cancel")]]))
        return MANUAL_TICKER_INPUT_REGULAR if typ=="reg" else MANUAL_TICKER_INPUT_THRESHOLD
    context.user_data[f"{typ}_ticker"] = txt
    if typ=="reg":
        return await regular_set_interval(update, context)
    else:
        return await threshold_set_percent(update, context)

@log_function('regular_set_interval')
async def regular_set_interval(update: Update, context: CallbackContext):
    if update.callback_query:
        q = update.callback_query; await q.answer()
        ticker = q.data.split("_")[-1]
        context.user_data["reg_ticker"] = ticker
        dest = q.edit_message_text
    else:
        ticker = context.user_data["reg_ticker"]
        dest = update.message.reply_text
    buttons = [
        [InlineKeyboardButton("1 мин", callback_data="reg_int_1"), InlineKeyboardButton("5 мин", callback_data="reg_int_5"), InlineKeyboardButton("15 мин", callback_data="reg_int_15")],
        [InlineKeyboardButton("30 мин", callback_data="reg_int_30"), InlineKeyboardButton("60 мин", callback_data="reg_int_60")],
        [InlineKeyboardButton("« Назад", callback_data="reg_notif")]
    ]
    await dest(f"⏳ Интервал для {ticker}:", reply_markup=InlineKeyboardMarkup(buttons))
    return REGULAR_SET_INTERVAL

@log_function('regular_confirm')
async def regular_confirm(update: Update, context: CallbackContext):
    q = update.callback_query; await q.answer()
    interval = int(q.data.split("_")[-1])
    ticker = context.user_data["reg_ticker"]
    chat_id = q.message.chat.id
    context.application.job_queue.run_repeating(
        send_price_update, interval*60,
        data={"chat_id":chat_id,"ticker":ticker,"interval":interval},
        name=f"send_price_{chat_id}_{ticker}"
    )
    active_trackings.setdefault(chat_id, {})[ticker] = {"regular":{"interval":interval}}
    save_tracking(chat_id, "set_stock", ticker, interval)
    await q.edit_message_text(f"✅ Регулярные уведомления для {ticker} каждые {interval} мин активированы!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("В меню", callback_data="main_menu")]]))
    return ConversationHandler.END

'''async def threshold_set_ticker(update: Update, context: CallbackContext):
    q = update.callback_query; await q.answer()
    tickers = sorted(valid_tickers)[:5]
    buttons = [[InlineKeyboardButton(t, callback_data=f"thr_ticker_{t}")] for t in tickers]
    buttons += [[InlineKeyboardButton("📝 Другой тикер", callback_data="manual_ticker_thr")],[InlineKeyboardButton("« Назад", callback_data="cancel")]]
    await q.edit_message_text("🔔 Выберите тикер:", reply_markup=InlineKeyboardMarkup(buttons))
    return THRESHOLD_SET_TICKER'''
@log_function('threshold_set_ticker')
async def threshold_set_ticker(update: Update, context: CallbackContext):
    q = update.callback_query; await q.answer()
    chat_id = q.message.chat.id
    history = user_history.get(str(chat_id), [])
    recent = history[:5]
    buttons = [[InlineKeyboardButton(t, callback_data=f"thr_ticker_{t}")] for t in recent]
    buttons.append([InlineKeyboardButton("📝 Ручной ввод", callback_data="manual_ticker_thr")])
    buttons.append([InlineKeyboardButton("« Назад", callback_data="main_menu")])
    await q.edit_message_text("🔔 Ваши последние тикеры:", reply_markup=InlineKeyboardMarkup(buttons))
    return THRESHOLD_SET_TICKER

@log_function('threshold_set_percent')
async def threshold_set_percent(update: Update, context: CallbackContext):
    q = update.callback_query; await q.answer()
    '''ticker = q.data.split("_")[-1]
    context.user_data["thr_ticker"] = ticker'''
    ticker = context.user_data.get("thr_ticker")

    # Получаем тикер из callback_data или user_data
    if q.data.startswith("thr_ticker_"):
        ticker = q.data.split("_")[-1]
        context.user_data["thr_ticker"] = ticker

    buttons = [
        [InlineKeyboardButton("1%", callback_data="thr_percent_1"),
         InlineKeyboardButton("3%", callback_data="thr_percent_3")],
        [InlineKeyboardButton("5%", callback_data="thr_percent_5"),
         InlineKeyboardButton("10%", callback_data="thr_percent_10")],
        [InlineKeyboardButton("📝 Ввести вручную", callback_data="thr_percent_manual")],
        [InlineKeyboardButton("« Назад", callback_data="threshold_notif")]
    ]
    await q.edit_message_text(f"📉 Порог для {ticker}:", reply_markup=InlineKeyboardMarkup(buttons))

    return THRESHOLD_SET_PERCENT

@log_function('manual_percent_input')
async def manual_percent_input(update: Update, context: CallbackContext):
    q = update.callback_query; await q.answer()
    await q.edit_message_text(
        "Введите процентный порог (например, 2.5):",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Отмена", callback_data="threshold_notif")]])
    )
    return MANUAL_THRESHOLD_INPUT_PERCENT

@log_function('handle_manual_threshold_input')
async def handle_manual_threshold_input(update: Update, context: CallbackContext):
    text = update.message.text.strip().replace("%", "")
    try:
        val = float(text)
        if val <= 0:
            raise ValueError
        context.user_data["thr_threshold"] = val
        return await threshold_set_interval(update, context)
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Введите число больше 0 (например, 2.5):")
        return MANUAL_THRESHOLD_INPUT_PERCENT




'''async def threshold_set_interval(update: Update, context: CallbackContext):
    q = update.callback_query; await q.answer()
    threshold = float(q.data.split("_")[-1])
    context.user_data["thr_threshold"] = threshold
    buttons = [
        [InlineKeyboardButton("1 мин", callback_data="thr_int_1"), InlineKeyboardButton("5 мин", callback_data="thr_int_5"), InlineKeyboardButton("15 мин", callback_data="thr_int_15")],
        [InlineKeyboardButton("30 мин", callback_data="thr_int_30"), InlineKeyboardButton("60 мин", callback_data="thr_int_60")],
        [InlineKeyboardButton("« Назад", callback_data="thr_ticker_")]
    ]
    await q.edit_message_text(f"⏳ Интервал для {context.user_data['thr_ticker']}:", reply_markup=InlineKeyboardMarkup(buttons))
    return THRESHOLD_SET_INTERVAL'''
@log_function('threshold_set_interval')
async def threshold_set_interval(update: Update, context: CallbackContext):
    # Если пришёл callback — парсим оттуда, иначе берём из user_data
    if update.callback_query:
        q = update.callback_query; await q.answer()
        # из callback_data вида thr_percent_5 или thr_percent_3
        threshold = float(q.data.split("_")[-1])
        context.user_data["thr_threshold"] = threshold
        dest = q.edit_message_text
    else:
        # вызывается из handle_manual_threshold_input
        threshold = context.user_data["thr_threshold"]
        dest = update.message.reply_text

    ticker = context.user_data["thr_ticker"]
    buttons = [
        [InlineKeyboardButton("1 мин", callback_data="thr_int_1"),
         InlineKeyboardButton("5 мин", callback_data="thr_int_5"),
         InlineKeyboardButton("15 мин", callback_data="thr_int_15")],
        [InlineKeyboardButton("30 мин", callback_data="thr_int_30"),
         InlineKeyboardButton("60 мин", callback_data="thr_int_60")],
        [InlineKeyboardButton("« Назад", callback_data="thr_back_to_percent")]
        #[InlineKeyboardButton("« Назад", callback_data="threshold_notif")
    ]
    await dest(f"⏳ Интервал для {ticker} при пороге {threshold}%:", reply_markup=InlineKeyboardMarkup(buttons))
    return THRESHOLD_SET_INTERVAL

@log_function('threshold_confirm')
async def threshold_confirm(update: Update, context: CallbackContext):
    q = update.callback_query; await q.answer()
    interval = int(q.data.split("_")[-1])
    ticker = context.user_data["thr_ticker"]
    threshold = context.user_data["thr_threshold"]
    chat_id = q.message.chat.id
    context.application.job_queue.run_repeating(
        check_price_changes, interval*60,
        data={"chat_id":chat_id,"ticker":ticker,"threshold":threshold,"interval":interval},
        name=f"follow_{chat_id}_{ticker}"
    )
    active_trackings.setdefault(chat_id, {})[ticker] = {"threshold":{"threshold":threshold,"interval":interval}}
    save_tracking(chat_id, "follow_stock", ticker, threshold, interval)
    #await q.edit_message_text(f"✅ Отслеживание {ticker}: порог {threshold}% каждые {interval} мин!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("В меню", callback_data="main_menu")]]))
    # Добавляем кнопку с явным указанием main_menu
    menu_button = [[InlineKeyboardButton("В меню", callback_data="main_menu")]]

    await q.edit_message_text(
        f"✅ Отслеживание {ticker}: порог {threshold}% каждые {interval} мин!",
        reply_markup=InlineKeyboardMarkup(menu_button)
    )

    return ConversationHandler.END

@log_function('delete_menu')
async def delete_menu(update: Update, context: CallbackContext):
    q = update.callback_query; await q.answer()
    kb = [[InlineKeyboardButton("Удалить регулярные", callback_data="del_reg")],
          [InlineKeyboardButton("Удалить пороговые", callback_data="del_threshold")],
          [InlineKeyboardButton("« Назад", callback_data="main_menu")]]
    await q.edit_message_text("🗑 Выберите тип удаления:", reply_markup=InlineKeyboardMarkup(kb))
    return DELETE_MENU

@log_function('delete_regular_list')
async def delete_regular_list(update: Update, context: CallbackContext):
    q = update.callback_query; await q.answer()
    chat_id = q.message.chat.id
    buttons = []

    # Читаем данные напрямую из файла
    if os.path.exists(TRACKING_FILE):
        with open(TRACKING_FILE, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("-")
                if len(parts) < 4 or int(parts[0]) != chat_id:
                    continue
                if parts[1] == "set_stock":
                    ticker = parts[2]
                    interval = parts[3]
                    buttons.append([InlineKeyboardButton(
                        f"❌ {ticker} ({interval} мин)",
                        callback_data=f"delreg_{ticker}"
                    )])

    for t,d in active_trackings.get(chat_id,{}).items():
        if "regular" in d:
            iv = d["regular"]["interval"]
            buttons.append([InlineKeyboardButton(f"❌ {t} ({iv} мин)", callback_data=f"delreg_{t}")])
    if not buttons:
        await q.edit_message_text(
            text = "🚫 У вас нет активных регулярных уведомлений",
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("← Назад", callback_data='del_menu')]
            ])
        )
        return DELETE_MENU
    buttons.append([InlineKeyboardButton("« Назад", callback_data="del_menu")])
    #await q.edit_message_text("📋 Регулярные:", reply_markup=InlineKeyboardMarkup(buttons))
    # удаляем старое
    await context.bot.delete_message(q.message.chat.id, q.message.message_id)
    # отправляем новое меню
    await context.bot.send_message(
        q.message.chat.id,
        text = "📋 Регулярные:",
        reply_markup = InlineKeyboardMarkup(buttons)
    )
    return DELETE_REGULAR

@log_function('delete_regular_confirm')
async def delete_regular_confirm(update: Update, context: CallbackContext):
    q = update.callback_query; await q.answer()
    ticker = q.data.split("_")[-1]; chat_id=q.message.chat.id
    remove_tracking(chat_id, "set_stock", ticker)
    for job in context.application.job_queue.get_jobs_by_name(f"set_{chat_id}_{ticker}"):
        job.schedule_removal()
    active_trackings[chat_id].pop(ticker, None)
    await q.answer(f"✅ {ticker} удалён")
    return await delete_regular_list(update, context)

@log_function('delete_threshold_list')
async def delete_threshold_list(update: Update, context: CallbackContext):
    q = update.callback_query; await q.answer()
    chat_id = q.message.chat.id
    buttons = []
    for t,d in active_trackings.get(chat_id,{}).items():
        if "threshold" in d:
            th=d["threshold"]
            buttons.append([InlineKeyboardButton(f"❌ {t} ({th['threshold']}%/{th['interval']} мин)", callback_data=f"delthr_{t}")])
    if not buttons:
        await q.edit_message_text(
            text = "🚫 У вас нет активных отслеживаний изменений",
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("← Назад", callback_data='del_menu')]
            ])
        )
        return DELETE_MENU
    buttons.append([InlineKeyboardButton("« Назад", callback_data="del_menu")])
    await q.edit_message_text("📋 Порог:", reply_markup=InlineKeyboardMarkup(buttons))
    return DELETE_THRESHOLD

@log_function('delete_threshold_confirm')
async def delete_threshold_confirm(update: Update, context: CallbackContext):
    q = update.callback_query; await q.answer()
    ticker = q.data.split("_")[-1]; chat_id=q.message.chat.id
    remove_tracking(chat_id, "follow_stock", ticker)
    for job in context.application.job_queue.get_jobs_by_name(f"follow_{chat_id}_{ticker}"):
        job.schedule_removal()
    active_trackings[chat_id].pop(ticker, None)
    await q.answer(f"✅ {ticker} удалён")
    return await delete_threshold_list(update, context)

@log_function('list_trackings')
async def list_trackings(update: Update, context: CallbackContext):
    '''q = update.callback_query; await q.answer()
    chat_id = q.message.chat.id
    regs=[]; ths=[]
    for t,d in active_trackings.get(chat_id,{}).items():
        if "regular" in d: regs.append(f"• {t} — каждые {d['regular']['interval']} мин")
        if "threshold" in d: ths.append(f"• {t} — {d['threshold']['threshold']}% каждые {d['threshold']['interval']} мин")
    msg=["📋 Активные:"]
    if regs: msg+=["\n📅 Регулярные:"]+regs
    if ths: msg+=["\n🚨 Порог:"]+ths
    kb=[[InlineKeyboardButton("« Назад", callback_data="main_menu")]]
    await q.edit_message_text("\n".join(msg) if regs or ths else "🚫 Нет активных", reply_markup=InlineKeyboardMarkup(kb))'''
    q = update.callback_query;
    await q.answer()
    chat_id = q.message.chat.id
    regs = []
    ths = []

    # Получаем данные из файла вместо глобальной переменной
    if os.path.exists(TRACKING_FILE):
        with open(TRACKING_FILE, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("-")
                if len(parts) < 4 or int(parts[0]) != chat_id:
                    continue

                if parts[1] == "set_stock":
                    ticker = parts[2]
                    interval = parts[3]
                    regs.append(f"• {ticker} — каждые {interval} мин")
                elif parts[1] == "follow_stock":
                    ticker = parts[2]
                    threshold = parts[3]
                    interval = parts[4]
                    ths.append(f"• {ticker} — {threshold}% каждые {interval} мин")

    # Формирование сообщения
    msg = ["📋 Активные отслеживания:"]
    if regs: msg += ["\n📅 Регулярные:"] + regs
    if ths: msg += ["\n🚨 Пороговые:"] + ths
    msg = "\n".join(msg) if regs or ths else "🚫 Нет активных отслеживаний"

    kb = [[InlineKeyboardButton("« Назад", callback_data="main_menu")]]
    await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))

async def cancel(update: Update, context: CallbackContext):
    q = update.callback_query; await q.answer()
    await q.edit_message_text("🚫 Отменено")
    return ConversationHandler.END

async def unknown_command(update: Update, context: CallbackContext):
    await update.message.reply_text("🔍 Используйте /start")

# Периодические задачи
async def send_price_update(context: CallbackContext):
    job = context.job; d=job.data
    chat_id,ticker,interval = d["chat_id"],d["ticker"],d["interval"]
    price = await get_stock_price(ticker)
    if price is None: return
    key=(chat_id,ticker)
    lst=price_history.setdefault(key,[]); now=datetime.now(); lst.append((now,price))
    prev=lst[-2][1] if len(lst)>1 else None
    ago30=next((p for t,p in reversed(lst) if t<=now-timedelta(minutes=30)),None)
    msg=""

    if prev:
        delta=(price-prev)/prev*100
        msg+=("📈 " if delta>=0 else "📉 ")+f"{ticker}\n"
        msg+=f"{'▲ Рост' if delta>=0 else '▼ Спад'} {abs(delta):.2f}%\nПредыдущая ({interval} мин): {prev:.2f}\n"
    else:
        msg+=f"{ticker}\nПредыдущая: N/A\n"

    msg+=f"30 мин назад: {ago30:.2f}\n" if ago30 else "30 мин назад: N/A\n"
    msg+=f"Текущая: {price:.2f}"
    kb=[[InlineKeyboardButton("❌ Остановить",callback_data=f"delreg_{ticker}")]]
    img=await capture_chart_screenshot(ticker,chat_id)
    if img:
        await context.bot.send_photo(chat_id, img, caption=msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    else:
        await context.bot.send_message(chat_id, msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    log_notification(chat_id, ticker, "REGULAR", str(price))
    update_history(chat_id, ticker)

async def check_price_changes(context: CallbackContext):
    job=context.job; d=job.data
    chat_id,ticker,thr,interval = d["chat_id"],d["ticker"],d["threshold"],d["interval"]
    price=await get_stock_price(ticker)
    if price is None: return
    key=(chat_id,ticker)
    lst=price_history.setdefault(key,[]); prev=lst[-1][1] if lst else None
    lst.append((datetime.now(),price))
    if prev and abs((price-prev)/prev*100)>=thr:
        delta=(price-prev)/prev*100
        msg=f"🚨 *{ticker}* — {'▲ Рост' if delta>=0 else '▼ Снижение'} {abs(delta):.2f}%\nПредыдущая: {prev:.2f}\nТекущая: {price:.2f}"
        kb=[[InlineKeyboardButton("❌ Остановить",callback_data=f"delthr_{ticker}")]]
        img=await capture_chart_screenshot(ticker,chat_id)
        if img:
            await context.bot.send_photo(chat_id, img, caption=msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        else:
            await context.bot.send_message(chat_id, msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        log_notification(chat_id, ticker, "THRESHOLD", f"{abs(delta):.2f}%")
        update_history(chat_id, ticker)

def setup_handlers(app):
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [
                #CallbackQueryHandler(start, pattern='^main_menu$'),
                CallbackQueryHandler(regular_set_ticker, pattern="^reg_notif$"),
                CallbackQueryHandler(threshold_set_ticker, pattern="^threshold_notif$"),
                CallbackQueryHandler(delete_menu, pattern="^delete_menu$"),
                CallbackQueryHandler(timeframe_choose, pattern="^set_timeframe$"),
                CallbackQueryHandler(list_trackings, pattern="^list_trackings$"),
                CallbackQueryHandler(dev_menu, pattern="^dev_menu$")
            ],
            REGULAR_SET_TICKER: [
                CallbackQueryHandler(regular_set_interval, pattern="^reg_ticker_"),
                CallbackQueryHandler(manual_ticker_input, pattern="^manual_ticker_reg$"),
                CallbackQueryHandler(start, pattern='^main_menu$')
            ],
            REGULAR_SET_INTERVAL: [
                CallbackQueryHandler(regular_confirm, pattern="^reg_int_"),
                CallbackQueryHandler(regular_set_ticker, pattern='^reg_notif$')
            ],
            THRESHOLD_SET_TICKER: [
                CallbackQueryHandler(threshold_set_percent, pattern="^thr_ticker_"),
                CallbackQueryHandler(manual_ticker_input, pattern="^manual_ticker_thr$"),
                CallbackQueryHandler(start, pattern='^main_menu$')
            ],
            THRESHOLD_SET_PERCENT: [
                CallbackQueryHandler(manual_percent_input, pattern="^thr_percent_manual$"),
                CallbackQueryHandler(threshold_set_interval, pattern="^thr_percent_[0-9]"),
                CallbackQueryHandler(threshold_set_ticker, pattern="^threshold_notif$")
            ],
            MANUAL_THRESHOLD_INPUT_PERCENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manual_threshold_input),
                CallbackQueryHandler(threshold_set_ticker, pattern="^threshold_notif$")
            ],
            THRESHOLD_SET_INTERVAL: [
                CallbackQueryHandler(threshold_confirm, pattern="^thr_int_"),
                CallbackQueryHandler(threshold_set_percent, pattern="^thr_back_to_percent$")
                #CallbackQueryHandler(threshold_set_percent, pattern="^thr_ticker_")
            ],
            DELETE_MENU: [
                CallbackQueryHandler(delete_regular_list, pattern="^del_reg$"),
                CallbackQueryHandler(delete_threshold_list, pattern="^del_threshold$"),
                CallbackQueryHandler(delete_menu, pattern='^delete_menu$'),
                CallbackQueryHandler(start, pattern='^main_menu$')
            ],
            DELETE_REGULAR: [
                CallbackQueryHandler(delete_regular_confirm, pattern="^delreg_"),
                CallbackQueryHandler(delete_menu, pattern='^del_menu$')
            ],
            DELETE_THRESHOLD: [
                CallbackQueryHandler(delete_threshold_confirm, pattern="^delthr_"),
                CallbackQueryHandler(delete_menu, pattern='^del_menu$')
            ],
            TIMEFRAME_CHOOSE: [
                CallbackQueryHandler(set_timeframe, pattern="^tf_"),
                CallbackQueryHandler(start, pattern='^main_menu$')
            ],
            MANUAL_TICKER_INPUT_REGULAR: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manual_ticker),
                CallbackQueryHandler(start, pattern='^main_menu$')
            ],
            MANUAL_TICKER_INPUT_THRESHOLD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manual_ticker),
                CallbackQueryHandler(start, pattern='^main_menu$')
            ],
            DEV_MENU:[
                CallbackQueryHandler(dev_stats, pattern="^dev_stats$"),
                CallbackQueryHandler(show_developers, pattern="^dev_list$"),
                CallbackQueryHandler(show_unique_users, pattern="^show_unique_users$"),
                CallbackQueryHandler(dev_analyze, pattern="^dev_analyze$"),
                CallbackQueryHandler(dev_menu, pattern="^dev_menu$"),
                CallbackQueryHandler(start, pattern="^main_menu$")
            ],
            DEV_STATS: [
                CallbackQueryHandler(dev_stats, pattern="^dev_stats$"),
                CallbackQueryHandler(dev_menu, pattern="^dev_menu$")
            ],
            DEV_LIST: [
                CallbackQueryHandler(show_developers, pattern="^dev_list$"),
                CallbackQueryHandler(dev_menu, pattern="^dev_menu$")
            ],
            DEV_ANALYZE: [
                CallbackQueryHandler(dev_menu, pattern="^dev_menu$")
            ]
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    )
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(start, pattern="^main_menu$"))
    app.add_handler(CommandHandler("reload", reload_tickers))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    # Повесим глобальные коллбэки для кнопок отмены из уведомлений (доработать, отслеживание удаляется, но много ошибок в терминале)
    app.add_handler(CallbackQueryHandler(delete_regular_confirm, pattern="^delreg_"))
    app.add_handler(CallbackQueryHandler(delete_threshold_confirm, pattern="^delthr_"))
    #---

    # Явно добавим обработчики для кнопок разработчика
    app.add_handler(CallbackQueryHandler(dev_menu, pattern="^dev_menu$"))
    app.add_handler(CallbackQueryHandler(dev_stats, pattern="^dev_stats$"))
    app.add_handler(CallbackQueryHandler(show_developers, pattern="^dev_list$"))
    app.add_handler(CallbackQueryHandler(dev_analyze, pattern="^dev_analyze$"))
    app.add_handler(CallbackQueryHandler(show_active_trackings, pattern=r"^trackers_page_\d+$"))
    app.add_handler(CallbackQueryHandler(show_jobs, pattern=r"^jobs_page_\d+$"))
    app.add_handler(CallbackQueryHandler(handle_job_action, pattern=r"^job_action_.+"))
    app.add_handler(CallbackQueryHandler(execute_job_action, pattern=r"^(toggle|run)_"))

def main():
    user_history.update(load_user_history()) #загружаем историю пользователей при запуске
    timeframe_settings.update(load_timeframes())  # загружаем таймфреймы пользователей
    load_tickers()
    app = ApplicationBuilder().token(TOKEN).concurrent_updates(5).build()
    load_trackings(app, start_job)
    app.job_queue.run_repeating(cleanup_archive_job, interval=3600, first=10)
    setup_handlers(app)
    app.run_polling()

if __name__ == "__main__":
    main()


'''THRESHOLD_SET_PERCENT: [
                CallbackQueryHandler(threshold_set_interval, pattern="^thr_percent_"),
                CallbackQueryHandler(threshold_set_ticker, pattern='^threshold_notif$')
            ],
            MANUAL_THRESHOLD_INPUT_PERCENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manual_threshold_input),
                CallbackQueryHandler(threshold_set_ticker, pattern='^threshold_notif$')
            ],
            THRESHOLD_SET_INTERVAL: [
                CallbackQueryHandler(threshold_confirm, pattern="^thr_int_"),
                CallbackQueryHandler(threshold_set_percent, pattern='^thr_ticker_')
            ],'''