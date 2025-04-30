# Скриншот графика
import asyncio
import logging

from PIL import Image

from config import timeframe_settings
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
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from io import BytesIO


async def capture_chart_screenshot(ticker: str, chat_id: int) -> BytesIO | None:
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
        driver.quit()