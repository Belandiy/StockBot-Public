import logging
import os
import watchdog
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from config import valid_tickers  # Импорт из config.py
from storage import cleanup_archive_files

TICKERS_RU_FILE = "tickers-RU.txt"
TICKERS_USA_FILE = "tickers-USA.txt"
TICKERS_CRYPTO_FILE = "tickers-crypto.txt"
TICKERS_ETF = "tickers_ETF.txt"
TICKERS_INDEXES = "tickers_indexes.txt"
TICKERS_FUTURES = "tickers-futures.txt"

def load_tickers():
    valid_tickers.clear()
    for f in (TICKERS_RU_FILE, TICKERS_USA_FILE, TICKERS_CRYPTO_FILE, TICKERS_ETF, TICKERS_INDEXES, TICKERS_FUTURES):
        if os.path.exists(f):
            with open(f, "r", encoding="utf-8") as fp:
                valid_tickers.update(line.strip().upper() for line in fp if line.strip())
    logging.info(f"Loaded {len(valid_tickers)} tickers")

def is_ticker_valid(ticker: str) -> bool:
    base = ticker.split("|")[0].upper()
    return any(t.split("|")[0].upper() == base for t in valid_tickers)

class TickerFileHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if any(f in event.src_path for f in (TICKERS_RU_FILE, TICKERS_USA_FILE, TICKERS_CRYPTO_FILE, TICKERS_ETF, TICKERS_INDEXES, TICKERS_FUTURES)):
            load_tickers()
            logging.info("Списки тикеров автоматически обновлены")

observer = Observer()
observer.schedule(TickerFileHandler(), path=".", recursive=False)
observer.start()

async def cleanup_archive_job(context):
    cleanup_archive_files()