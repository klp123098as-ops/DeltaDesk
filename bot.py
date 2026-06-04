import logging
import re

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from analysis import analyze_symbol
from config import BOT_TOKEN, PORT, WEBHOOK_SECRET, WEBHOOK_URL
from keyboards import (
    BTN_EX,
    BTN_HELP,
    BTN_MENU,
    BTN_MIN,
    BTN_SETTINGS,
    BTN_TOP,
    POPULAR_COINS,
    main_menu_keyboard,
    min_pct_keyboard,
    price_actions_keyboard,
    reply_panel_keyboard,
)
from market import (
    fetch_prices,
    format_price_table,
    format_top_arbitrage,
    normalize_symbol,
    scan_top_arbitrage,
    symbol_base,
)
from user_settings import (
    AVAILABLE_EXCHANGES,
    add_user_exchange,
    format_user_settings,
    get_min_arb_pct,
    get_user_exchanges,
    remove_user_exchange,
    reset_user_exchanges,
    set_min_arb_pct,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

HELP_TEXT = """
🤖 DeltaDesk — цены с разных бирж

Цены:
/price BTC — любая монета с USDT (PEPE, SHIB, WIF…)
/analyze BTC — краткий анализ
/top — топ арбитража (популярные монеты)
Кнопки — только топ; остальное вводом: /price ТИКЕР

Ваши биржи:
/exchanges — список
/add bybit — добавить
/remove mexc — убрать
/reset — стандартный список

Мин. % арбитража (топ и подсветка):
/min — текущий порог
/min 0.05 — показывать от 0.05%
/min 0 — показывать всё

Панель внизу чата + кнопки под сообщениями.
""".strip()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Сравниваю цены на биржах и ищу арбитраж.\n\n" + HELP_TEXT,
        reply_markup=reply_panel_keyboard(),
    )
    await update.message.reply_text(
        "Быстрый доступ — кнопки ниже 👇",
        reply_markup=main_menu_keyboard(),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        HELP_TEXT,
        reply_markup=reply_panel_keyboard(),
    )
    await update.message.reply_text("Меню:", reply_markup=main_menu_keyboard())


async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Выберите монету кнопкой или: /price BTC",
            reply_markup=main_menu_keyboard(),
        )
        return
    await _send_prices(update, " ".join(context.args))


async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Пример: /analyze BTC")
        return
    await _send_analysis(update, " ".join(context.args))


async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_top(update)


async def min_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if not context.args:
        current = get_min_arb_pct(uid)
        await update.message.reply_text(
            f"Текущий минимум: {current}%.\n"
            "Примеры: /min 0.05  |  /min 0 (всё)\n"
            "Или кнопки ниже:",
            reply_markup=min_pct_keyboard(current),
        )
        return
    try:
        value = float(context.args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Пример: /min 0.05")
        return
    set_min_arb_pct(uid, value)
    await update.message.reply_text(
        f"✅ Мин. арбитраж: {get_min_arb_pct(uid)}%\n"
        f"{'Показываю всё' if value <= 0 else 'В /top только выше порога'}",
        reply_markup=min_pct_keyboard(get_min_arb_pct(uid)),
    )


async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    await update.message.reply_text(
        format_user_settings(uid),
        reply_markup=min_pct_keyboard(get_min_arb_pct(uid)),
    )


async def exchanges_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    mine = get_user_exchanges(uid)
    available = ", ".join(e.upper() for e in AVAILABLE_EXCHANGES)
    await update.message.reply_text(
        f"✅ Ваши биржи ({len(mine)}):\n{_fmt_ex(mine)}\n\n"
        f"📋 Можно добавить:\n{available}\n\n"
        "Добавить: /add bitget\nУбрать: /remove mexc"
    )


async def add_exchange_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Пример: /add binance")
        return
    _, msg = add_user_exchange(update.effective_user.id, context.args[0])
    await update.message.reply_text(msg)


async def remove_exchange_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Пример: /remove kraken")
        return
    _, msg = remove_user_exchange(update.effective_user.id, context.args[0])
    await update.message.reply_text(msg)


async def reset_exchanges_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = reset_user_exchanges(update.effective_user.id)
    await update.message.reply_text(msg)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    uid = update.effective_user.id

    if data == "menu":
        await query.message.reply_text("Меню:", reply_markup=main_menu_keyboard())
        return
    if data == "help":
        await query.message.reply_text(HELP_TEXT, reply_markup=main_menu_keyboard())
        return
    if data == "ex":
        await query.message.reply_text(
            f"Ваши биржи:\n{_fmt_ex(get_user_exchanges(uid))}\n\n/add /remove"
        )
        return
    if data == "settings":
        await query.message.reply_text(
            format_user_settings(uid),
            reply_markup=min_pct_keyboard(get_min_arb_pct(uid)),
        )
        return
    if data == "minmenu":
        current = get_min_arb_pct(uid)
        await query.message.reply_text(
            f"Мин. % для топа и подсветки.\nСейчас: {current}%",
            reply_markup=min_pct_keyboard(current),
        )
        return
    if data.startswith("min:"):
        try:
            value = float(data.split(":", 1)[1])
        except ValueError:
            return
        set_min_arb_pct(uid, value)
        await query.message.reply_text(
            f"✅ Мин. арбитраж: {get_min_arb_pct(uid)}%",
            reply_markup=min_pct_keyboard(get_min_arb_pct(uid)),
        )
        return
    if data == "top":
        await _send_top(update)
        return
    if data.startswith("p:"):
        await _send_prices(update, data[2:], edit=True)
        return
    if data.startswith("a:"):
        await _send_analysis(update, data[2:], edit=True)


def _fmt_ex(exchanges: list[str]) -> str:
    return ", ".join(e.upper() for e in exchanges)


PANEL_ACTIONS = {
    BTN_TOP: "_top",
    BTN_EX: "_ex",
    BTN_MIN: "_min",
    BTN_SETTINGS: "_settings",
    BTN_HELP: "_help",
    BTN_MENU: "_menu",
}


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    action = PANEL_ACTIONS.get(text)
    if action == "_top":
        await _send_top(update)
        return
    if action == "_ex":
        await exchanges_cmd(update, context)
        return
    if action == "_min":
        await min_cmd(update, context)
        return
    if action == "_settings":
        await settings_cmd(update, context)
        return
    if action == "_help":
        await help_cmd(update, context)
        return
    if action == "_menu":
        await update.message.reply_text("Меню:", reply_markup=main_menu_keyboard())
        return
    if re.fullmatch(r"[A-Za-z0-9]{2,12}", text):
        await _send_prices(update, text)


def _chat(update: Update):
    if update.callback_query:
        return update.callback_query.message
    return update.message


async def _send_prices(update: Update, coin: str, edit: bool = False) -> None:
    msg = _chat(update)
    wait = msg
    if edit:
        try:
            await msg.edit_text("⏳ Обновляю…")
        except Exception:
            wait = await msg.reply_text("⏳ Запрашиваю биржи…")
    else:
        wait = await msg.reply_text("⏳ Запрашиваю биржи…")

    try:
        symbol = normalize_symbol(coin)
        base = symbol_base(symbol)
        uid = update.effective_user.id
        min_pct = get_min_arb_pct(uid)
        exchanges = get_user_exchanges(uid)
        rows = await fetch_prices(symbol, exchanges)
        text = format_price_table(symbol, rows, min_arb_pct=min_pct)
        kb = price_actions_keyboard(base)
        await wait.edit_text(text, reply_markup=kb)
    except ValueError as exc:
        await wait.edit_text(str(exc))
    except Exception:
        logger.exception("price error")
        await wait.edit_text("Ошибка при запросе цен. Попробуйте позже.")


async def _send_analysis(update: Update, coin: str, edit: bool = False) -> None:
    msg = _chat(update)
    wait = msg
    if edit:
        try:
            await msg.edit_text("⏳ Считаю анализ…")
        except Exception:
            wait = await msg.reply_text("⏳ Считаю анализ…")
    else:
        wait = await msg.reply_text("⏳ Считаю анализ…")

    try:
        symbol = normalize_symbol(coin)
        exchanges = get_user_exchanges(update.effective_user.id)
        text = await analyze_symbol(symbol, exchanges)
        base = symbol_base(symbol)
        await wait.edit_text(text, reply_markup=price_actions_keyboard(base))
    except ValueError as exc:
        await wait.edit_text(str(exc))
    except Exception:
        logger.exception("analyze error")
        await wait.edit_text("Ошибка анализа. Попробуйте позже.")


async def _send_top(update: Update) -> None:
    msg = _chat(update)
    wait = await msg.reply_text("⏳ Сканирую монеты…")
    try:
        uid = update.effective_user.id
        min_pct = get_min_arb_pct(uid)
        exchanges = get_user_exchanges(uid)
        items = await scan_top_arbitrage(POPULAR_COINS[:6], exchanges, min_arb_pct=min_pct)
        await wait.edit_text(
            format_top_arbitrage(items, min_arb_pct=min_pct),
            reply_markup=main_menu_keyboard(),
        )
    except Exception:
        logger.exception("top error")
        await wait.edit_text("Ошибка сканирования. Попробуйте позже.")


def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("price", price_cmd))
    app.add_handler(CommandHandler("analyze", analyze_cmd))
    app.add_handler(CommandHandler("top", top_cmd))
    app.add_handler(CommandHandler("min", min_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("exchanges", exchanges_cmd))
    app.add_handler(CommandHandler("add", add_exchange_cmd))
    app.add_handler(CommandHandler("remove", remove_exchange_cmd))
    app.add_handler(CommandHandler("reset", reset_exchanges_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    return app


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit(
            "Нет BOT_TOKEN.\n"
            "1) Откройте @BotFather → /newbot → скопируйте токен\n"
            "2) Локально: файл .env → BOT_TOKEN=...\n"
            "3) Облако: см. DEPLOY_FREE.md"
        )

    app = build_app()

    if WEBHOOK_URL:
        logger.info("Режим webhook: %s/telegram", WEBHOOK_URL)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path="telegram",
            webhook_url=f"{WEBHOOK_URL}/telegram",
            secret_token=WEBHOOK_SECRET or None,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.info("Режим polling (24/7 в облаке — см. DEPLOY_FREE.md)")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
