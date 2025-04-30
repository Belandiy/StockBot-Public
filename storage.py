import logging
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
    '''line = f"{chat_id}-{tracking_type}-{ticker}-{'-'.join(map(str, params))}\n"
    with open(TRACKING_FILE, "a", encoding="utf-8") as f:
        f.write(line)'''
    exist = False
    if os.path.exists(TRACKING_FILE):
        with open(TRACKING_FILE, "r", encoding="utf-8") as f:
            existing = f.read()
            if f"{chat_id}-{tracking_type}-{ticker}" in existing:
                exist = True

        if not exist:
            with open(TRACKING_FILE, "w", encoding="utf-8") as f:
                f.write(f"{chat_id}-{tracking_type}-{ticker}-{'-'.join(map(str, params))}\n")
            '''else:
                f.write(f"{chat_id}-{tracking_type}-{ticker}-{'-'.join(map(str, params))}\n")'''
def remove_tracking(chat_id: int, tracking_type: str, ticker: str):
    if not os.path.exists(TRACKING_FILE):
        return
    tmp = TRACKING_FILE + ".tmp"
    with open(TRACKING_FILE, "r", encoding="utf-8") as fin, open(tmp, "w", encoding="utf-8") as fout:
        for line in fin:
            parts = line.strip().split("-")
            if len(parts) >= 4 and int(parts[0]) == chat_id and parts[1] == tracking_type and parts[2] == ticker:
                continue
            fout.write(line)
    os.replace(tmp, TRACKING_FILE)

def load_trackings(application, add_job_callback):
    if not os.path.exists(TRACKING_FILE):
        return
    with open(TRACKING_FILE, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("-")
            if len(parts) < 4:
                continue
            chat_id = int(parts[0]); typ = parts[1]; ticker = parts[2]; params = parts[3:]
            try:
                if typ == "set_stock" and len(params) == 1:
                    interval = int(params[0])
                    add_job_callback(application, chat_id, ticker, "regular", interval)
                elif typ == "follow_stock" and len(params) == 2:
                    threshold, interval = float(params[0]), int(params[1])
                    add_job_callback(application, chat_id, ticker, "threshold", interval, threshold)
                else:
                    logging.error(f"Invalid tracking format: {line}")
            except Exception as e:
                logging.error(f"Error loading tracking {line}: {str(e)}")
                continue

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