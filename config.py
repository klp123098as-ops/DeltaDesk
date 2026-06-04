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
# Здесь популярные + волатильные альткоины, где чаще бывает разница цен
SCAN_COINS = [
    "BTC", "ETH", "SOL", "XRP", "DOGE", "TON", "ADA", "AVAX", "SHIB", "DOT", 
    "LINK", "NEAR", "MATIC", "PEPE", "LTC", "ICP", "BCH", "UNI", "SUI", "APT", 
    "OP", "ARB", "TIA", "SEI", "INJ", "RNDR", "GRT", "STX", "FIL", "ATOM", 
    "IMX", "KAS", "WIF", "BONK", "FLOKI", "NOT", "TRX", "ETC", "XLM", "VET",
    "THETA", "MKR", "LDO", "FET", "AGIX", "TAO", "ORDI", "1000SATS", "AAVE", "AR"
]
REQUEST_TIMEOUT_MS = 15_000 # 15 сек — золотая середина

# Мин. % арбитража по умолчанию (0 = показывать всё)
DEFAULT_MIN_ARB_PCT = 0.0
