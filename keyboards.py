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
