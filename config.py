import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Облако: если задан WEBHOOK_URL — режим webhook (Render и т.п.)
# Локально и на Fly.io — оставьте пустым (режим polling)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip().rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
PORT = int(os.getenv("PORT", "8080"))

# Папка для данных (важно для облака)
DATA_DIR = Path(os.getenv("DATA_DIR", ".")).resolve()
SETTINGS_FILE = DATA_DIR / "user_data.json"

# Биржи, доступные в Беларуси (Binance, Bybit, OKX, MEXC, Bitget, BingX, Gate)
DEFAULT_EXCHANGES = [
    "binance",
    "bybit",
    "okx",
    "mexc",
    "bitget",
    "bingx",
    "gate",
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

# Мин. % арбитража по умолчанию (0 = показывать всё)
DEFAULT_MIN_ARB_PCT = 0.0
