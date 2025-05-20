import logging
import traceback
import os
import json
from datetime import datetime, timedelta

# Пути к файлам
TRACKING_FILE = "trackings.txt"
ARCHIVE_FILE = "archive.txt"
TIMEFRAME_FILE = "timeframes.json"
NOTIFICATION_LOG_FILE = "notifications.log"
USER_HISTORY_FILE = "user_history.json"

from config import (
    price_history, active_trackings, timeframe_settings,
    user_history, unique_users
)

CACHE_TTL_HOURS = 24

def log_notification(chat_id: int, ticker: str, notification_type: str, message: str):
    timestamp = datetime.now().isoformat()
    with open(NOTIFICATION_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} | {chat_id} | {ticker} | {notification_type} | {message}\n")

# ————————————————— Tracking —————————————————
def save_tracking(chat_id: int, tracking_type: str, ticker: str, *params):
    exist = False
    new_line = f"{chat_id}-{tracking_type}-{ticker}-{'-'.join(map(str, params))}\n"
    if os.path.exists(TRACKING_FILE):
        with open(TRACKING_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines:
                if line.strip().startswith(f"{chat_id}-{tracking_type}-{ticker}-{'-'.join(map(str, params))}"):
                    exist = True
                    break

    if not exist:
        with open(TRACKING_FILE, "a", encoding="utf-8") as f:
            f.write(new_line)

def remove_tracking(chat_id: int, tracking_type: str, ticker: str, *params):
    if not os.path.exists(TRACKING_FILE):
        return

    logging.info(f"Удаление отслеживания: {chat_id}-{tracking_type}-{ticker}-{'-'.join(map(str, params))}")

    #удаление из файла
    tmp = TRACKING_FILE + ".tmp"
    found = False
    with open(TRACKING_FILE, "r", encoding="utf-8") as fin, open(tmp, "w", encoding="utf-8") as fout:
        for line in fin:
            parts = line.strip().split("-")
            if len(parts) >= 4 and int(parts[0]) == chat_id and parts[1] == tracking_type and parts[2] == ticker:
                if tracking_type == "regular" and len(params) > 0 and len(parts) >= 4:
                    if parts[3] == str(params[0]):
                        logging.info(f"Удаляем запись из файла: {line.strip()}")
                        found = True
                        continue

                elif tracking_type == "follow" and len(params) > 1 and len(parts) > 5:
                    if parts[3] == str(params[0]) and parts[4] == str(params[1]):
                        logging.info(f"Удаляем запись из файла: {line.strip()}")
                        found = True
                        continue
            fout.write(line)
    os.replace(tmp, TRACKING_FILE)

    if not found:
        logging.warning(f"Запись {chat_id}-{tracking_type}-{ticker}-{'-'.join(map(str, params))} не найдена в файле")

    #удаление из active_trackings
    try:
        if chat_id not in active_trackings:
            logging.info(f"Пользователь {chat_id} не найден в active_trackings")
            return
        if ticker not in active_trackings:
            logging.info(f"Тикер {ticker} не найден у пользователя {chat_id} в active_trackings")
            return

        ticker_data = active_trackings[chat_id][ticker]

        if tracking_type == "regular" and "regular" in ticker_data and len(params) > 0:
            interval = int(params[0])
            interval_key = str(interval)

            if interval_key in ticker_data["regular"]:
                del ticker_data["regular"][interval_key]
                logging.info(f"Удалено регулярное отслеживание {ticker} (интервал {params[0]}) у пользователя {chat_id}")

                if not ticker_data["regular"]:
                    del ticker_data["regular"]
            else:
                logging.warning(f"Интервал {interval} не найден в регулярных отслеживаниях тикера {ticker}")
        elif tracking_type == "follow" and "follow" in ticker_data and len(params) > 1:
            threshold = float(params[0])
            interval = int(params[1])
            follow_key = f"{threshold}_{interval}"

            if follow_key in ticker_data["follow"]:
                del ticker_data["follow"][follow_key]
                logging.info(f"Удалено пороговое отслеживание {ticker} (порог {params[0]}%, интервал {params[1]}) у пользователя {chat_id}")

                if not ticker_data["follow"]:
                    del ticker_data["follow"]
            else:
                logging.warning(f"Комбинация порог/интервал {threshold}/{interval} не найдена в пороговых отслеживаниях тикера {ticker}")

        if not ticker_data:
            del active_trackings[chat_id][ticker]
            logging.info(f"Полностью удален тикер {ticker} у пользователя {chat_id}")

            if not active_trackings[chat_id]:
                del active_trackings[chat_id]
                logging.info(f"Пользователь {chat_id} удален из active_trackings")

    except Exception as e:
        logging.error(f"Ошибка при удалении из active_trackings: {e}")
        logging.error(traceback.format_exc())


def load_trackings(application, add_job_callback):
    if not os.path.exists(TRACKING_FILE):
        return

    logging.info("Загрузка отслеживаний из файла...")
    with open(TRACKING_FILE, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("-")
            if len(parts) < 4:
                logging.warning(f"Некорректная строка в файле отслеживаний: {line}")
                continue

            chat_id = int(parts[0])
            typ = parts[1]
            ticker = parts[2]
            params = parts[3:]

            try:
                if typ == "regular" and len(params) == 1:
                    interval = int(params[0])
                    logging.info(f"Загружаем регулярное отслеживание: {chat_id}-{ticker}-{interval}")

                    # Инициализируем структуру если нужно
                    if chat_id not in active_trackings:
                        active_trackings[chat_id] = {}
                    if ticker not in active_trackings[chat_id]:
                        active_trackings[chat_id][ticker] = {}
                    if "regular" not in active_trackings[chat_id][ticker]:
                        active_trackings[chat_id][ticker]["regular"] = {}

                    # Добавляем отслеживание с интервалом в качестве ключа
                    interval_key = str(interval)
                    active_trackings[chat_id][ticker]["regular"][interval_key] = {"interval": interval}

                    add_job_callback(application, chat_id, ticker, "regular", interval)
                elif typ == "follow" and len(params) == 2:
                    threshold = float(params[0])
                    interval = int(params[1])
                    logging.info(f"Загружаем пороговое отслеживание: {chat_id}-{ticker}-{threshold}-{interval}")

                    # Инициализируем структуру если нужно
                    if chat_id not in active_trackings:
                        active_trackings[chat_id] = {}
                    if ticker not in active_trackings[chat_id]:
                        active_trackings[chat_id][ticker] = {}
                    if "follow" not in active_trackings[chat_id][ticker]:
                        active_trackings[chat_id][ticker]["follow"] = {}

                    # Добавляем отслеживание с комбинацией порог_интервал в качестве ключа
                    follow_key = f"{threshold}_{interval}"
                    active_trackings[chat_id][ticker]["follow"][follow_key] = {
                        "threshold": threshold,
                        "interval": interval
                    }

                    add_job_callback(application, chat_id, ticker, "follow", interval, threshold)
                else:
                    logging.error(f"Некорректный формат строки: {line}")
            except Exception as e:
                logging.error(f"Ошибка загрузки отслеживания: {line} - {str(e)}")

    logging.info(f"Загружено отслеживаний: {sum(len(user_data) for user_data in active_trackings.values())}")
    logging.info(f"Структура active_trackings после загрузки: {active_trackings}")


# ————————————————— Timeframes —————————————————
def save_timeframe(chat_id: int, timeframe: str):
    data = {}
    if os.path.exists(TIMEFRAME_FILE):
        with open(TIMEFRAME_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    data[str(chat_id)] = timeframe
    with open(TIMEFRAME_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_timeframes():
    if not os.path.exists(TIMEFRAME_FILE):
        return {}
    try:
        with open(TIMEFRAME_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return {int(k): v for k, v in raw.items()}
    except:
        return {}

# ————————————————— Archive —————————————————
def save_price_to_archive(ticker: str, price: float):
    timestamp = datetime.now().isoformat()
    with open(ARCHIVE_FILE, "a", encoding="utf-8") as f:
        f.write(f"{timestamp}-{ticker}-{price}\n")

def get_price_from_archive(ticker: str, target_time: datetime):
    if not os.path.exists(ARCHIVE_FILE):
        return None
    for line in reversed(open(ARCHIVE_FILE, "r", encoding="utf-8").readlines()):
        parts = line.strip().split("-")
        if len(parts) != 3:
            continue
        rec_time = datetime.fromisoformat(parts[0])
        if parts[1] == ticker and abs((rec_time - target_time).total_seconds()) <= 60:
            return float(parts[2])
    return None

def cleanup_archive_files():
    cutoff = datetime.now() - timedelta(hours=24)
    if not os.path.exists(ARCHIVE_FILE):
        return
    valid = []
    for line in open(ARCHIVE_FILE, "r", encoding="utf-8"):
        parts = line.strip().split("-")
        if len(parts) != 3:
            continue
        rec_time = datetime.fromisoformat(parts[0])
        if rec_time > cutoff:
            valid.append(line)
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        f.writelines(valid)

def check_price_cache(ticker: str):
    now = datetime.now()
    if not os.path.exists(ARCHIVE_FILE):
        return None
    kept = []; found = None
    for line in open(ARCHIVE_FILE, "r", encoding="utf-8"):
        parts = line.strip().split("-")
        if len(parts) != 3:
            continue
        rec_time = datetime.fromisoformat(parts[0])
        if now - rec_time <= timedelta(hours=CACHE_TTL_HOURS):
            kept.append(line)
            if parts[1] == ticker:
                found = float(parts[2])
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        f.writelines(kept)
    return found

# ————————————————— User history —————————————————
def save_user_history(data: dict):
    with open(USER_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_user_history():
    if not os.path.exists(USER_HISTORY_FILE):
        return {}
    try:
        return json.load(open(USER_HISTORY_FILE, "r", encoding="utf-8"))
    except:
        return {}