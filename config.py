import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Облако: если задан WEBHOOK_URL — режим webhook (Render и т.п.)
# Локально и на Fly.io — оставьте пустым (режим polling)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip().rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
PORT = int(os.getenv("PORT", "8080"))

# Биржи по умолчанию (если пользователь не настроил свой список)
DEFAULT_EXCHANGES = [
    "binance",
    "bybit",
    "okx",
    "kraken",
    "kucoin",
    "gate",
    "mexc",
]

QUOTE = "USDT"
REQUEST_TIMEOUT_MS = 25_000

# Мин. % арбитража по умолчанию (0 = показывать всё)
DEFAULT_MIN_ARB_PCT = 0.0
