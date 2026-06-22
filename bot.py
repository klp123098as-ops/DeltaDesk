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
from config import BOT_TOKEN, PORT, WEBHOOK_SECRET, WEBHOOK_URL, SCAN_COINS, DEFAULT_EXCHANGES, ADMIN_ID
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
    exchange_list_keyboard,
)
from market import (
    fetch_prices,
    format_price_table,
    format_top_arbitrage,
    normalize_symbol,
    scan_top_arbitrage,
    get_new_signals,
    get_price_jumps,
    get_fear_greed_index,
    symbol_base,
    close_all_exchanges,
    get_top_movers,
    format_movers,
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
    add_user_alert,
    get_all_users_with_alerts,
    get_user_alerts,
    remove_user_alert,
    is_user_allowed,
    add_to_whitelist,
    remove_from_whitelist,
    get_whitelist,
    save_user_info,
    get_user_info,
    _load_raw,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

HELP_TEXT = """
🤖 <b>DeltaDesk — твой крипто-сканер</b>

<b>Команды:</b>
/price BTC — цена на всех биржах
/top — лучший арбитраж прямо сейчас
/alert BTC 65000 — уведомление по цене
/analyze BTC — тех. анализ + Индекс Страха

<b>Настройки:</b>
/signals on/off — авто-уведомления (фон)
/min 0.3 — порог арбитража в %
/exchanges — управление биржами
/all_exchanges — список всех 100+ бирж

<b>Админ (если доступно):</b>
/allow ID — дать доступ
/deny ID — закрыть доступ
/whitelist — список пользователей

Просто нажми / и выбери команду!
""".strip()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    user = update.effective_user

    # Сохраняем информацию о пользователе
    save_user_info(uid, first_name=user.first_name or "", username=user.username or "")

    if not is_user_allowed(uid):
        await update.message.reply_text(
            f"⛔️ Доступ ограничен.\n\nВаш ID: <code>{uid}</code>\n"
            "Передайте этот ID владельцу бота для получения доступа.",
            parse_mode="HTML"
        )
        return

    await update.message.reply_text(
        "Привет! Сравниваю цены на биржах и ищу арбитраж.\n\n" + HELP_TEXT,
        reply_markup=reply_panel_keyboard(),
        parse_mode="HTML",
    )
    await update.message.reply_text(
        "Быстрый доступ — кнопки ниже 👇",
        reply_markup=main_menu_keyboard(),
    )


async def allow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для админа: добавить пользователя в белый список."""
    uid = update.effective_user.id
    logger.info(f"Admin attempt /allow by {uid}. Current ADMIN_ID is {ADMIN_ID}")

    try:
        if not ADMIN_ID:
            logger.warning(f"ADMIN_ID not set, blocking /allow by {uid}")
            await update.message.reply_text("❌ Админ не настроен на этом боте.")
            return

        if uid != ADMIN_ID:
            logger.warning(f"Unauthorized /allow attempt by {uid}")
            await update.message.reply_text("❌ Недостаточно прав для этой команды.")
            return

        if not context.args:
            await update.message.reply_text("Пример: /allow 12345678")
            return

        target_id = int(context.args[0])
        add_to_whitelist(target_id)
        await update.message.reply_text(f"✅ Пользователь {target_id} добавлен в белый список.")
        try:
            await context.bot.send_message(chat_id=target_id, text="🎉 Вам предоставлен доступ к боту! Напишите /start")
        except Exception as e:
            logger.error(f"Could not notify user {target_id}: {e}")
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
    except Exception as e:
        logger.exception(f"Error in allow_cmd: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


async def deny_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для админа: удалить пользователя из белого списка."""
    uid = update.effective_user.id

    try:
        if not ADMIN_ID:
            await update.message.reply_text("❌ Админ не настроен на этом боте.")
            return

        if uid != ADMIN_ID:
            await update.message.reply_text("❌ Недостаточно прав для этой команды.")
            return

        if not context.args:
            await update.message.reply_text("Пример: /deny 12345678")
            return

        target_id = int(context.args[0])
        if target_id == ADMIN_ID:
            await update.message.reply_text("Нельзя удалить самого себя.")
            return
        remove_from_whitelist(target_id)
        await update.message.reply_text(f"❌ Пользователь {target_id} удален из белого списка.")
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
    except Exception as e:
        logger.exception(f"Error in deny_cmd: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


async def whitelist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для админа: список всех допущенных."""
    uid = update.effective_user.id

    try:
        if not ADMIN_ID:
            await update.message.reply_text("❌ Админ не настроен на этом боте.")
            return

        if uid != ADMIN_ID:
            await update.message.reply_text("❌ Недостаточно прав для этой команды.")
            return

        wl = get_whitelist()
        text = "👥 <b>Белый список:</b>\n\n"
        if not wl:
            text += "Список пуст."
        else:
            for user_id in wl:
                is_admin = "👑" if user_id == ADMIN_ID else ""
                info = get_user_info(user_id)
                first_name = info.get("first_name", "")
                username = info.get("username", "")

                # Формируем строку с информацией
                user_display = f"<code>{user_id}</code>"
                if first_name:
                    user_display += f" • {first_name}"
                if username:
                    user_display += f" (@{username})"

                text += f"• {user_display} {is_admin}\n"
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        logger.exception(f"Error in whitelist_cmd: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        HELP_TEXT,
        reply_markup=reply_panel_keyboard(),
        parse_mode="HTML",
    )
    await update.message.reply_text("Меню:", reply_markup=main_menu_keyboard())


async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        if not context.args:
            await update.message.reply_text(
                "Выберите монету кнопкой или: /price BTC",
                reply_markup=main_menu_keyboard(),
            )
            return
        await _send_prices(update, " ".join(context.args))
    except Exception as e:
        logger.exception(f"Error in price_cmd: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


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
        f"⚙️ <b>Управление вашими биржами:</b>\n\n"
        f"Ваш список ({len(mine)}/20): <code>{_fmt_ex(mine)}</code>\n\n"
        "Выберите биржи из списка популярных или нажмите 'Вперед' для поиска других:",
        reply_markup=exchange_list_keyboard(page=0, user_id=uid),
        parse_mode="HTML"
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
    """Показывает интерактивное меню выбора бирж."""
    await exchanges_cmd(update, context)


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


async def me_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для проверки своего ID и статуса."""
    try:
        uid = update.effective_user.id
        is_admin = (uid == ADMIN_ID)
        mode = "Webhook" if WEBHOOK_URL else "Polling"

        text = (
            f"👤 <b>Ваш профиль:</b>\n\n"
            f"• ID: <code>{uid}</code>\n"
            f"• Статус: {'<b>АДМИНИСТРАТОР</b>' if is_admin else 'Пользователь'}\n"
            f"• Режим бота: {mode}\n"
            f"• Доступ: {'✅ Разрешен' if is_user_allowed(uid) else '❌ Ограничен'}"
        )
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        logger.exception(f"Error in me_cmd: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


async def alert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id

    try:
        # Без параметров — показываем список
        if not context.args or len(context.args) < 2:
            alerts = get_user_alerts(uid)
            text = "🔔 <b>Ваши уведомления по цене:</b>\n\n"
            if not alerts:
                text += "Список пуст."
            else:
                for i, a in enumerate(alerts):
                    direction = "повышение выше" if a['type'] == "above" else "понижение ниже"
                    text += f"{i}. <b>{a['base']}</b>: {direction} ${a['price']}\n"
                text += "\n<code>/alert_del 0</code> — удалить первый алерт"

            text += "\n\n<b>Добавить новый:</b>\n<code>/alert BTC 65000</code>"
            await update.message.reply_text(text, parse_mode="HTML")
            return

        # Создание нового алерта
        base = context.args[0].upper()
        try:
            target_price = float(context.args[1].replace(",", "."))
        except (ValueError, IndexError):
            await update.message.reply_text("❌ Ошибка: укажите цену числом.\nПример: <code>/alert BTC 65000</code>", parse_mode="HTML")
            return

        # Проверяем, существует ли такая монета
        symbol = normalize_symbol(base)
        logger.info(f"Creating alert for {uid}: {base} at ${target_price}")

        # Берем биржи пользователя
        exchanges = get_user_exchanges(uid)
        if not exchanges:
            await update.message.reply_text("❌ У вас нет добавленных бирж. Используйте /exchanges для добавления.", parse_mode="HTML")
            return

        wait_msg = await update.message.reply_text(f"⏳ Проверяю цену {base} на {len(exchanges)} биржах...")

        try:
            prices = await fetch_prices(symbol, exchanges)
            logger.info(f"Got prices for {symbol}: {len(prices)} exchanges responded")

            # Фильтруем только те, которые дали ответ с ценой
            valid_prices = [p for p in prices if p.last]

            if not valid_prices:
                await wait_msg.edit_text(f"❌ Монета <b>{base}</b> не найдена на ваших биржах.\nПроверьте написание (например, BTC, ETH, SOL).", parse_mode="HTML")
                return

            # Берем среднюю цену (или первую если одна биржа)
            current = sum(p.last for p in valid_prices) / len(valid_prices)

            # Формируем информацию о биржах
            exchanges_info = ", ".join([f"<b>{p.exchange.upper()}</b>" for p in valid_prices])
            logger.info(f"Valid prices from: {exchanges_info}")

            # Определяем тип алерта
            alert_type = "above" if target_price > current else "below"

            # Сохраняем алерт
            add_user_alert(uid, base, target_price, alert_type)
            logger.info(f"Alert saved for {uid}: {base} {alert_type} {target_price} (current: {current})")

            direction_text = f"выше ${target_price}" if alert_type == "above" else f"ниже ${target_price}"

            await wait_msg.edit_text(
                f"✅ <b>Уведомление создано!</b>\n\n"
                f"Монета: <b>{base}</b>\n"
                f"Текущая цена: <b>${current:.2f}</b>\n"
                f"Алерт при: {direction_text}\n"
                f"Биржи: {exchanges_info}\n\n"
                f"<i>Я пришлю сообщение, когда цена будет достигнута на любой из этих бирж.</i>",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.exception(f"Error fetching price for {symbol}: {e}")
            await wait_msg.edit_text(f"❌ Ошибка при запросе цены: {str(e)}", parse_mode="HTML")

    except Exception as e:
        logger.exception(f"Alert command error: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}", parse_mode="HTML")


async def alert_del_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Укажите номер алерты из списка /alert")
        return
    try:
        idx = int(context.args[0])
        if remove_user_alert(update.effective_user.id, idx):
            await update.message.reply_text("✅ Удалено.")
        else:
            await update.message.reply_text("❌ Неверный номер.")
    except Exception:
        await update.message.reply_text("Пример: /alert_del 0")


async def daily_movers_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ежедневная рассылка топ монет по волатильности."""
    logger.info("=== DAILY MOVERS JOB STARTED ===")
    try:
        # Получаем топ монеты
        movers_data = await get_top_movers(["binance", "bybit", "okx"], limit=3)
        message = await format_movers(movers_data)

        # Получаем всех пользователей
        data = _load_raw()
        all_users = [int(uid) for uid in data.keys() if uid.isdigit()]

        logger.info(f"Отправляю моверс {len(all_users)} пользователям")

        for uid in all_users:
            try:
                await context.bot.send_message(chat_id=uid, text=message, parse_mode="HTML")
                logger.info(f"✅ Movers sent to {uid}")
            except Exception as e:
                logger.warning(f"Failed to send movers to {uid}: {e}")

        logger.info("=== DAILY MOVERS JOB FINISHED ===")
    except Exception as e:
        logger.exception(f"Error in daily_movers_job: {e}")


async def background_scanner_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Фоновая задача для рассылки сигналов и алертов."""
    users_signals = get_all_users_with_signals()
    users_alerts = get_all_users_with_alerts()

    logger.info(f"=== BACKGROUND JOB STARTED ===")
    logger.info(f"Пользователей с сигналами: {len(users_signals)}")
    logger.info(f"Пользователей с алертами: {len(users_alerts)}")

    if users_alerts:
        for uid, alerts in users_alerts.items():
            logger.info(f"  User {uid}: {len(alerts)} алертов")
            for a in alerts:
                logger.info(f"    - {a['base']} {a['type']} ${a['price']}")

    if not users_signals and not users_alerts:
        logger.info("Нет пользователей с активными сигналами/алертами, выход")
        return

    logger.info(f"Начинаю сканирование...")
    try:
        # 1. Скан арбитража (если есть пользователи)
        new_items = []
        if users_signals:
            new_items = await get_new_signals(SCAN_COINS, DEFAULT_EXCHANGES, 0.1)

        # 2. Скан скачков цены
        jumps = await get_price_jumps(SCAN_COINS, threshold_pct=2.5)

        # 3. Скан алертов (по всем монетам из алертов)
        all_alert_bases = set()
        for alerts in users_alerts.values():
            for a in alerts:
                all_alert_bases.add(a["base"])

        logger.info(f"Проверяю цены для {len(all_alert_bases)} монет...")

        # Для каждого юзера получаем цены на его биржах
        # Format: {uid: {base: {'price': avg, 'exchanges_str': str, 'all_prices': [ExchangePrice]}}}
        user_current_prices = {}
        for uid, alerts in users_alerts.items():
            user_exchanges = get_user_exchanges(uid)
            user_alert_bases = set(a["base"] for a in alerts)

            logger.info(f"User {uid}: биржи = {user_exchanges}, монеты = {user_alert_bases}")

            user_current_prices[uid] = {}
            for base in user_alert_bases:
                try:
                    logger.info(f"  Получаю цену {base} на {user_exchanges}...")
                    prices = await fetch_prices(f"{base}/USDT", user_exchanges)
                    valid_prices = [p for p in prices if p.last]

                    logger.info(f"    Ответило {len(valid_prices)} бирж из {len(prices)}")

                    if valid_prices:
                        # Берем среднюю цену
                        avg_price = sum(p.last for p in valid_prices) / len(valid_prices)
                        exchanges_str = ", ".join(p.exchange.upper() for p in valid_prices)
                        user_current_prices[uid][base] = {
                            'price': avg_price,
                            'exchanges_str': exchanges_str,
                            'all_prices': valid_prices
                        }
                        logger.info(f"    ✅ {base} = ${avg_price:.2f} (from {exchanges_str})")
                    else:
                        logger.warning(f"    ❌ Нет ответов от бирж для {base}")
                except Exception as e:
                    logger.exception(f"Failed to fetch price for {uid}/{base}: {e}")

        # Рассылка сигналов арбитража
        for uid in users_signals:
            try:
                user_min = get_min_arb_pct(uid)
                messages = []
                user_items = [item for item in new_items if item[2] >= user_min]
                if user_items:
                    messages.append("🔔 <b>Авто-сигнал арбитража!</b>\n" + format_top_arbitrage(user_items, user_min))
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
                        logger.warning(f"Failed to send signal to {uid}: {e}")
            except Exception as e:
                logger.exception(f"Error processing signals for user {uid}: {e}")

        # Рассылка алертов по цене
        logger.info(f"Проверка алертов для {len(users_alerts)} пользователей...")
        for uid, alerts in users_alerts.items():
            try:
                user_prices = user_current_prices.get(uid, {})
                logger.info(f"User {uid}: есть цены для {len(user_prices)} монет")

                # Делаем копию, чтобы не лезть в оригинальный список
                alerts_to_check = list(alerts)
                triggered_indices = []

                for i, a in enumerate(alerts_to_check):
                    base = a["base"]
                    logger.info(f"  Проверяю алерт {i}: {base} {a['type']} ${a['price']}")

                    if base in user_prices:
                        price_data = user_prices[base]
                        curr = price_data['price']
                        all_prices = price_data['all_prices']
                        triggered = False
                        triggered_exchanges = []

                        logger.info(f"    Средняя цена: ${curr:.2f}")

                        # Проверяем условие алерта и ищем биржи, где цена соответствует
                        for p in all_prices:
                            if a["type"] == "above" and p.last >= a["price"]:
                                triggered = True
                                triggered_exchanges.append(p.exchange.upper())
                            elif a["type"] == "below" and p.last <= a["price"]:
                                triggered = True
                                triggered_exchanges.append(p.exchange.upper())

                        if triggered:
                            logger.info(f"    ✅ TRIGGERED на биржах: {triggered_exchanges}")
                            direction_text = f"выше ${a['price']}" if a['type'] == "above" else f"ниже ${a['price']}"
                            exchanges_triggered = ", ".join(triggered_exchanges)
                            text = f"🚨 <b>ALERT: {base} достиг цели!</b>\n\nТекущая цена: <b>${curr:.2f}</b>\nВаша цель: {direction_text}\n\n<b>Достигнута на:</b> {exchanges_triggered}"
                            try:
                                await context.bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
                                logger.info(f"✅✅✅ Alert SENT to {uid}: {base} {a['type']} {a['price']}, current: {curr} ({exchanges_triggered})")
                                triggered_indices.append(i)
                            except Exception as e:
                                logger.exception(f"Failed to send alert to {uid}: {e}")
                        else:
                            logger.info(f"    ❌ Не срабатывает")
                    else:
                        logger.warning(f"    ❌ Нет цены для {base}")

                # Удаляем сработавшие алерты (в обратном порядке, чтобы индексы не сбивались)
                for i in sorted(triggered_indices, reverse=True):
                    logger.info(f"  Удаляю алерт {i}")
                    remove_user_alert(uid, i)

            except Exception as e:
                logger.exception(f"Error processing alerts for user {uid}: {e}")

        logger.info(f"=== BACKGROUND JOB FINISHED ===")

    except Exception:
        logger.exception("Ошибка в фоновом сканере")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    uid = update.effective_user.id
    
    if not is_user_allowed(uid):
        await query.answer("Доступ ограничен", show_alert=True)
        return

    await query.answer()
    data = query.data or ""

    if data == "menu":
        await query.message.reply_text("Меню:", reply_markup=main_menu_keyboard())
        return
    if data == "help":
        await query.message.reply_text(HELP_TEXT, reply_markup=main_menu_keyboard())
        return
    if data == "ex":
        await exchanges_cmd(update, context)
        return
    if data.startswith("ex_pg:"):
        page = int(data.split(":")[1])
        await query.edit_message_reply_markup(reply_markup=exchange_list_keyboard(page, uid))
        return
    if data.startswith("ex_tgl:"):
        _, ex_id, pg = data.split(":")
        page = int(pg)
        current = get_user_exchanges(uid)
        if ex_id in current:
            remove_user_exchange(uid, ex_id)
        else:
            add_user_exchange(uid, ex_id)
        
        # Обновляем сообщение и клавиатуру
        mine = get_user_exchanges(uid)
        await query.edit_message_text(
            f"⚙️ <b>Управление вашими биржами:</b>\n\n"
            f"Ваш список ({len(mine)}/20): <code>{_fmt_ex(mine)}</code>\n\n"
            "Выберите биржи из списка популярных или нажмите 'Вперед' для поиска других:",
            reply_markup=exchange_list_keyboard(page, uid),
            parse_mode="HTML"
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
    uid = update.effective_user.id
    user = update.effective_user

    # Обновляем информацию о пользователе при каждом контакте
    save_user_info(uid, first_name=user.first_name or "", username=user.username or "")

    if not is_user_allowed(uid):
        return

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
        
        # Получаем тех.анализ
        analysis_text = await analyze_symbol(symbol, exchanges)
        
        # Добавляем индекс страха и жадности
        fng_text = await get_fear_greed_index()
        
        final_text = f"{analysis_text}\n\n{fng_text}"
        base = symbol_base(symbol)
        await wait.edit_text(final_text, reply_markup=price_actions_keyboard(base), parse_mode="HTML")
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
        
        # Получаем биржи пользователя
        exchanges = get_user_exchanges(uid)
        
        # Сканируем расширенный список монет из конфига
        items = await scan_top_arbitrage(SCAN_COINS, exchanges, min_arb_pct=min_pct)
        text = format_top_arbitrage(items, min_arb_pct=min_pct)
        
        await wait.edit_text(
            text,
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
    try:
        # Базовые команды для всех
        commands = [
            BotCommand("start", "Запустить бота"),
            BotCommand("price", "Цена (напр. /price BTC)"),
            BotCommand("top", "Топ арбитража"),
            BotCommand("alert", "Уведомление по цене (напр. /alert BTC 65000)"),
            BotCommand("signals", "Авто-сигналы (on/off)"),
            BotCommand("min", "Мин. % (напр. /min 0.3)"),
            BotCommand("exchanges", "Мои биржи"),
            BotCommand("all_exchanges", "Все биржи"),
            BotCommand("add", "Добавить биржу"),
            BotCommand("remove", "Удалить биржу"),
            BotCommand("analyze", "Анализ + Индекс Страха"),
            BotCommand("help", "Справка"),
        ]
        
        # Если задан ADMIN_ID, добавляем админ-команды в подсказки
        if ADMIN_ID:
            admin_commands = commands + [
                BotCommand("allow", "Добавить в белый список"),
                BotCommand("deny", "Удалить из белого списка"),
                BotCommand("whitelist", "Список допущенных"),
            ]
            # Устанавливаем админ-команды специально для админа
            from telegram import BotCommandScopeChat
            await application.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_ID))
            
        # Устанавливаем базовые команды для всех остальных
        await application.bot.set_my_commands(commands)
        logger.info("Подсказки команд успешно установлены")
    except Exception as e:
        logger.error(f"Ошибка при установке команд: {e}")

def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    # Добавляем обработчик завершения
    app.post_shutdown = on_shutdown
    
    # Регистрация фоновой задачи (каждые 3 минуты для алертов)
    if app.job_queue:
        # Фоновое сканирование алертов каждые 3 минуты
        app.job_queue.run_repeating(background_scanner_job, interval=180, first=10)

        # Ежедневная рассылка топ монет в 21:40 МСК (18:40 UTC)
        from datetime import time
        app.job_queue.run_daily(daily_movers_job, time=time(hour=18, minute=40))
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("price", price_cmd))
    app.add_handler(CommandHandler("analyze", analyze_cmd))
    app.add_handler(CommandHandler("top", top_cmd))
    app.add_handler(CommandHandler("min", min_cmd))
    app.add_handler(CommandHandler("alert", alert_cmd))
    app.add_handler(CommandHandler("alert_del", alert_del_cmd))
    app.add_handler(CommandHandler("me", me_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("exchanges", exchanges_cmd))
    app.add_handler(CommandHandler("all_exchanges", all_exchanges_cmd))
    app.add_handler(CommandHandler("add", add_exchange_cmd))
    app.add_handler(CommandHandler("remove", remove_exchange_cmd))
    app.add_handler(CommandHandler("reset", reset_exchanges_cmd))
    app.add_handler(CommandHandler("signals", signals_cmd))
    app.add_handler(CommandHandler("allow", allow_cmd))
    app.add_handler(CommandHandler("deny", deny_cmd))
    app.add_handler(CommandHandler("whitelist", whitelist_cmd))
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
