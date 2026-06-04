import logging
import re
import asyncio
from aiohttp import web

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from analysis import analyze_symbol
from config import BOT_TOKEN, PORT, WEBHOOK_SECRET, WEBHOOK_URL, SCAN_COINS, DEFAULT_EXCHANGES
from keyboards import (
    BTN_EX,
    BTN_HELP,
    BTN_MENU,
    BTN_MIN,
    BTN_SETTINGS,
    BTN_TOP,
    BTN_SIGNALS,
    BTN_ALL_EX,
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
    get_new_signals,
    get_price_jumps,
    symbol_base,
    close_all_exchanges,
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
    get_all_users_with_signals,
    get_signals_enabled,
    set_signals_enabled,
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
/all_exchanges — полный список всех бирж (100+)

Мин. % арбитража (топ и подсветка):
/min — текущий порог
/min 0.05 — показывать от 0.05%
/min 0 — показывать всё
Можно просто отправить число в чат (например 0.33)

Авто-сигналы (фон):
/signals — статус
/signals on — включить
/signals off — выключить

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
    await update.message.reply_text(
        f"✅ Ваши биржи ({len(mine)}/20):\n{_fmt_ex(mine)}\n\n"
        "Вы можете добавить любую из 100+ бирж (binance, upbit, bitget...)\n"
        "Добавить: /add id_биржи\nУбрать: /remove id_биржи\n"
        "Полный список ID можно найти в документации CCXT."
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


async def all_exchanges_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает полный список всех бирж, которые знает библиотека ccxt."""
    all_ex = sorted(list(AVAILABLE_EXCHANGES))
    text = "🏛 <b>Все доступные биржи (CCXT):</b>\n\n"
    text += ", ".join(all_ex)
    text += "\n\nДобавить: <code>/add id_биржи</code>"
    
    # Сообщение может быть длинным, разбиваем по 4000 символов
    if len(text) > 4000:
        for i in range(0, len(text), 4000):
            await update.message.reply_text(text[i:i+4000], parse_mode="HTML")
    else:
        await update.message.reply_text(text, parse_mode="HTML")


async def signals_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if not context.args:
        enabled = get_signals_enabled(uid)
        await update.message.reply_text(
            f"Статус сигналов: {'✅ ВКЛ' if enabled else '❌ ВЫКЛ'}\n\n"
            "Бот будет присылать уведомления, если найдет арбитраж выше вашего порога %.\n"
            "Включить: /signals on\n"
            "Выключить: /signals off"
        )
        return
    
    arg = context.args[0].lower()
    if arg == "on":
        set_signals_enabled(uid, True)
        await update.message.reply_text("✅ Сигналы включены! Бот будет искать арбитраж в фоне.")
    elif arg == "off":
        set_signals_enabled(uid, False)
        await update.message.reply_text("❌ Сигналы выключены.")
    else:
        await update.message.reply_text("Используйте: /signals on или /signals off")


async def background_scanner_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Фоновая задача для рассылки сигналов."""
    users = get_all_users_with_signals()
    if not users:
        return

    logger.info("Фоновый скан сигналов...")
    try:
        # 1. Скан арбитража (стандартный набор бирж)
        new_items = await get_new_signals(SCAN_COINS, DEFAULT_EXCHANGES, 0.1)
        
        # 2. Скан скачков цены (Binance)
        jumps = await get_price_jumps(SCAN_COINS, threshold_pct=2.5) # Порог 2.5%
        
        for uid in users:
            user_min = get_min_arb_pct(uid)
            
            # Собираем сообщение для пользователя
            messages = []
            
            # Добавляем арбитраж
            user_items = [item for item in new_items if item[2] >= user_min]
            if user_items:
                messages.append("🔔 <b>Авто-сигнал арбитража!</b>\n" + format_top_arbitrage(user_items, user_min))
            
            # Добавляем скачки
            if jumps:
                jump_text = "🚀 <b>Резкие изменения (Binance):</b>\n"
                for base, change, price in jumps:
                    emoji = "📈" if change > 0 else "📉"
                    jump_text += f"• {emoji} {base}: {change:+.2f}% (${price})\n"
                messages.append(jump_text)
            
            if messages:
                final_text = "\n\n".join(messages) + "\n\n<i>Отключить: /signals off</i>"
                try:
                    await context.bot.send_message(chat_id=uid, text=final_text, parse_mode="HTML")
                except Exception as e:
                    logger.warning(f"Не удалось отправить сигнал пользователю {uid}: {e}")
    except Exception:
        logger.exception("Ошибка в фоновом сканере")


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
            f"Мин. % для топа и подсветки.\nСейчас: {current}%\n\n"
            "Выберите из списка или нажмите кнопку ввода своего значения:",
            reply_markup=min_pct_keyboard(current),
        )
        return
    if data == "min_custom":
        await query.message.reply_text(
            "Введите желаемый процент арбитража числом.\n"
            "Например: 0.33 или 1.5\n\n"
            "После ввода бот запомнит это значение."
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
    BTN_SIGNALS: "_signals",
    BTN_ALL_EX: "_all_ex",
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
    if action == "_signals":
        await signals_cmd(update, context)
        return
    if action == "_all_ex":
        await all_exchanges_cmd(update, context)
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

    # Если введено число (например, 0.33 или 1) - трактуем как настройку %
    if re.fullmatch(r"\d+([.,]\d+)?", text):
        try:
            val = float(text.replace(",", "."))
            uid = update.effective_user.id
            set_min_arb_pct(uid, val)
            await update.message.reply_text(
                f"✅ Мин. арбитраж установлен: {val}%\n"
                f"{'Показываю всё' if val <= 0 else f'В /top только выше {val}%'}",
                reply_markup=min_pct_keyboard(val)
            )
            return
        except ValueError:
            pass

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
        await wait.edit_text(text, reply_markup=kb, parse_mode="HTML")
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
        await wait.edit_text(text, reply_markup=price_actions_keyboard(base), parse_mode="HTML")
    except ValueError as exc:
        await wait.edit_text(str(exc))
    except Exception:
        logger.exception("analyze error")
        await wait.edit_text("Ошибка анализа. Попробуйте позже.")


async def _send_top(update: Update) -> None:
    msg = _chat(update)
    wait = await msg.reply_text(f"⏳ Глубокое сканирование ({len(SCAN_COINS)} монет)...")
    try:
        uid = update.effective_user.id
        min_pct = get_min_arb_pct(uid)
        exchanges = get_user_exchanges(uid)
        
        # Сканируем расширенный список монет из конфига
        items = await scan_top_arbitrage(SCAN_COINS, exchanges, min_arb_pct=min_pct)
        await wait.edit_text(
            format_top_arbitrage(items, min_arb_pct=min_pct),
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML"
        )
    except Exception:
        logger.exception("top error")
        await wait.edit_text("Ошибка сканирования. Попробуйте позже.")


async def on_shutdown(app: Application) -> None:
    logger.info("Закрытие соединений...")
    await close_all_exchanges()

async def post_init(application: Application) -> None:
    """Действия после запуска бота: настройка подсказок команд."""
    commands = [
        BotCommand("start", "Запустить бота"),
        BotCommand("price", "Узнать цену (напр. /price BTC)"),
        BotCommand("top", "Топ арбитражных связок"),
        BotCommand("signals", "Настройка авто-сигналов (on/off)"),
        BotCommand("min", "Установить мин. % (напр. /min 0.3)"),
        BotCommand("exchanges", "Ваши выбранные биржи"),
        BotCommand("all_exchanges", "Список всех доступных бирж"),
        BotCommand("add", "Добавить биржу (напр. /add bybit)"),
        BotCommand("remove", "Удалить биржу"),
        BotCommand("analyze", "Тех. анализ монеты"),
        BotCommand("help", "Справка по командам"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Подсказки команд установлены")

def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    # Добавляем обработчик завершения
    app.post_shutdown = on_shutdown
    
    # Регистрация фоновой задачи (каждые 5 минут)
    if app.job_queue:
        app.job_queue.run_repeating(background_scanner_job, interval=300, first=10)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("price", price_cmd))
    app.add_handler(CommandHandler("analyze", analyze_cmd))
    app.add_handler(CommandHandler("top", top_cmd))
    app.add_handler(CommandHandler("min", min_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("exchanges", exchanges_cmd))
    app.add_handler(CommandHandler("all_exchanges", all_exchanges_cmd))
    app.add_handler(CommandHandler("add", add_exchange_cmd))
    app.add_handler(CommandHandler("remove", remove_exchange_cmd))
    app.add_handler(CommandHandler("reset", reset_exchanges_cmd))
    app.add_handler(CommandHandler("signals", signals_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    return app


async def health_check(request):
    return web.Response(text="OK")

def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Нет BOT_TOKEN")

    # Исправление ошибки "There is no current event loop"
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    app = build_app()

    if WEBHOOK_URL:
        logger.info("Запуск Webhook на порту %s", PORT)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path="telegram",
            webhook_url=f"{WEBHOOK_URL}/telegram",
            secret_token=WEBHOOK_SECRET or None
        )
    else:
        # Режим Polling для Render (экспериментально для скорости)
        logger.info("Запуск в режиме Polling (24/7)")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
