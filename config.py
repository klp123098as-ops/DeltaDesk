import os
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID_STR = os.getenv("ADMIN_ID", "").strip()
ADMIN_ID = int(ADMIN_ID_STR) if ADMIN_ID_STR else 0

logger = logging.getLogger(__name__)
if BOT_TOKEN:
    logger.info(f"CONFIG: BOT_TOKEN=******, ADMIN_ID={ADMIN_ID}")

# Облако: если задан WEBHOOK_URL — режим webhook (Render и т.п.)
# Локально и на Fly.io — оставьте пустым (режим polling)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip().rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
PORT = int(os.getenv("PORT", "8080"))

# Папка для данных (важно для облака)
DATA_DIR = Path(os.getenv("DATA_DIR", ".")).resolve()
SETTINGS_FILE = DATA_DIR / "user_data.json"

# Биржи, стабильно работающие на Render (без Binance/Bybit, т.к. они блокируют облака)
DEFAULT_EXCHANGES = [
    "okx",
    "mexc",
    "bitget",
    "bingx",
    "gate",
    "kucoin"
]

# Список монет для расширенного сканирования (Топ арбитраж)
# Оставили 20 самых "арбитражных" монет для стабильности на Render
SCAN_COINS = [
    "BTC", "ETH", "SOL", "XRP", "DOGE", "TON", "AVAX", "SHIB", "DOT",
    "LINK", "NEAR", "MATIC", "PEPE", "LTC", "ICP", "SUI", "APT",
    "ARB", "RNDR", "WIF"
]

# Таймаут для запросов к биржам (в миллисекундах)
# 15 сек — оптимальный баланс между скоростью и надежностью
REQUEST_TIMEOUT_MS = 15000

# Мин. % арбитража по умолчанию (чтобы не показывать убыточные связки)
DEFAULT_MIN_ARB_PCT = 0.5

# Прокси для обхода географических блокировок (опционально)
# Формат: http://ip:port или https://ip:port или socks5://ip:port
PROXY_URL = os.getenv("PROXY_URL", "").strip()
