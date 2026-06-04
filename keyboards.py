from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

POPULAR_COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "TON", "ADA"]

# Тексты кнопок нижней панели (Reply keyboard)
BTN_TOP = "📊 Топ арбитраж"
BTN_EX = "⚙️ Мои Биржи"
BTN_MIN = "📉 Мин %"
BTN_SIGNALS = "🔔 Сигналы"
BTN_ALL_EX = "🏛 Все Биржи"
BTN_SETTINGS = "🔧 Настройки"
BTN_HELP = "❓ Помощь"
BTN_MENU = "🏠 Меню"


def reply_panel_keyboard() -> ReplyKeyboardMarkup:
    """Постоянная панель внизу чата."""
    return ReplyKeyboardMarkup(
        [
            [BTN_TOP, BTN_SIGNALS, BTN_MIN],
            [BTN_EX, BTN_ALL_EX, BTN_SETTINGS],
            [BTN_HELP, BTN_MENU],
            [
                KeyboardButton("BTC"),
                KeyboardButton("ETH"),
                KeyboardButton("SOL"),
                KeyboardButton("BNB"),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def main_menu_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for coin in POPULAR_COINS:
        row.append(InlineKeyboardButton(coin, callback_data=f"p:{coin}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton("📊 Топ", callback_data="top"),
            InlineKeyboardButton("⚙️ Биржи", callback_data="ex"),
            InlineKeyboardButton("📉 Мин %", callback_data="minmenu"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton("🔧 Настройки", callback_data="settings"),
            InlineKeyboardButton("❓ Справка", callback_data="help"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def min_pct_keyboard(current: float) -> InlineKeyboardMarkup:
    presets = [0, 0.01, 0.03, 0.05, 0.1, 0.25]
    row = []
    rows = []
    for p in presets:
        label = "Всё" if p == 0 else f"{p}%"
        mark = " ✓" if abs(current - p) < 0.0001 else ""
        row.append(InlineKeyboardButton(f"{label}{mark}", callback_data=f"min:{p}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    
    # Добавляем кнопку для ввода своего значения
    rows.append([InlineKeyboardButton("⌨️ Ввести свой %", callback_data="min_custom")])
    rows.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


from user_settings import AVAILABLE_EXCHANGES, get_user_exchanges

def exchange_list_keyboard(page: int = 0, user_id: int | None = None) -> InlineKeyboardMarkup:
    """Интерактивное меню выбора бирж с пагинацией."""
    # Популярные биржи (выводим первыми)
    popular = ["binance", "bybit", "okx", "mexc", "bitget", "bingx", "gate", "kucoin", "kraken", "htx"]
    
    # Все остальные из CCXT по алфавиту
    others = sorted([ex for ex in AVAILABLE_EXCHANGES if ex not in popular])
    full_list = popular + others
    
    per_page = 10
    start = page * per_page
    end = start + per_page
    current_page_ex = full_list[start:end]
    
    user_exchanges = get_user_exchanges(user_id) if user_id else []
    
    rows = []
    for ex in current_page_ex:
        is_added = ex in user_exchanges
        label = f"✅ {ex.upper()}" if is_added else f"➕ {ex.upper()}"
        # Префикс 'ex_tgl:' для переключения статуса биржи
        rows.append([InlineKeyboardButton(label, callback_data=f"ex_tgl:{ex}:{page}")])
    
    # Навигация
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"ex_pg:{page-1}"))
    
    max_pages = (len(full_list) - 1) // per_page
    if end < len(full_list):
        nav_row.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"ex_pg:{page+1}"))
    
    if nav_row:
        rows.append(nav_row)
        
    rows.append([InlineKeyboardButton("◀️ Меню", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def price_actions_keyboard(coin: str) -> InlineKeyboardMarkup:
    base = coin.upper().split("/")[0]
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔄 Обновить", callback_data=f"p:{base}"),
                InlineKeyboardButton("🔍 Анализ", callback_data=f"a:{base}"),
            ],
            [
                InlineKeyboardButton("📊 Топ", callback_data="top"),
                InlineKeyboardButton("◀️ Меню", callback_data="menu"),
            ],
        ]
    )
