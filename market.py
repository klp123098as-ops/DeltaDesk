from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import ccxt.async_support as ccxt

from config import REQUEST_TIMEOUT_MS, PROXY_URL
from profitability import calculate_net_profit, ProfitabilityResult

logger = logging.getLogger(__name__)

@dataclass
class ExchangePrice:
    exchange: str
    symbol: str
    bid: float | None
    ask: float | None
    last: float | None
    volume_24h: float | None = None
    change_24h_pct: float | None = None
    source: str = "ccxt"

# Кеширование
MARKETS_CACHE = {}
MARKET_CACHE_TTL = 43200
FAILED_EXCHANGES = {}
FAILED_CACHE_TTL = 3600

# Глобальные инстансы бирж
EXCHANGES_INSTANCES = {}

# Максимальный размер истории цен (очистка для предотвращения утечки памяти)
MAX_PRICE_HISTORY_SIZE = 500
PRICE_HISTORY_CLEANUP_INTERVAL = 3600  # очищать каждый час

# Кеш комиссий бирж (чтобы не запрашивать часто)
EXCHANGE_FEES_CACHE = {}
FEES_CACHE_TTL = 86400  # 24 часа

# Кеш статуса кошельков
WALLET_STATUS_CACHE = {}
WALLET_CACHE_TTL = 3600  # 1 час

def _num(val) -> float | None:
    if val is None: return None
    try: return float(val)
    except (ValueError, TypeError): return None

async def get_exchange_instance(exchange_id: str):
    if exchange_id in EXCHANGES_INSTANCES:
        return EXCHANGES_INSTANCES[exchange_id]

    cls = getattr(ccxt, exchange_id, None)
    if not cls: return None

    # Оптимизация для облака: переиспользование соединений и увеличенные таймауты
    config = {
        "enableRateLimit": True,
        "timeout": 30000,
        "options": {"defaultType": "spot"}
    }

    # Добавляем прокси, если установлен в переменных окружения
    if PROXY_URL:
        logger.info(f"Using proxy for {exchange_id}: {PROXY_URL[:30]}...")
        config["aiohttp_proxy"] = PROXY_URL
    else:
        config["aiohttp_proxy"] = None

    instance = cls(config)
    EXCHANGES_INSTANCES[exchange_id] = instance
    return instance

async def close_all_exchanges():
    for ex in EXCHANGES_INSTANCES.values():
        await ex.close()
    EXCHANGES_INSTANCES.clear()

async def fetch_prices(symbol: str, exchanges: list[str]) -> list[ExchangePrice]:
    """Получает цены с разных бирж (bid/ask из orderbook)."""
    tasks = [_fetch_one_ccxt(eid, symbol) for eid in exchanges]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r]

async def _fetch_one_ccxt(exchange_id: str, symbol: str) -> ExchangePrice | None:
    """
    Получает bid/ask из orderbook (вместо Last Price).
    Это гарантирует реальные цены, по которым можно торговать.
    """
    now = time.time()
    # Убираем блокировку FAILED_EXCHANGES для популярных бирж, чтобы всегда пробовать их
    popular_to_retry = ["binance", "bybit", "okx", "mexc", "bitget", "gate"]
    
    if exchange_id in FAILED_EXCHANGES and exchange_id not in popular_to_retry:
        if now - FAILED_EXCHANGES[exchange_id] < FAILED_CACHE_TTL:
            return None

    ex = await get_exchange_instance(exchange_id)
    if not ex: return None

    # Пробуем до 3 раз для популярных бирж с увеличением таймаута
    attempts = 3 if exchange_id in popular_to_retry else 1
    
    for attempt in range(attempts):
        try:
            # Загрузка рынков с кешем
            cached_markets, ts = MARKETS_CACHE.get(exchange_id, (None, 0))
            if not cached_markets or (now - ts > MARKET_CACHE_TTL):
                await asyncio.wait_for(ex.load_markets(), timeout=(30.0 + attempt * 10))
                MARKETS_CACHE[exchange_id] = (ex.markets, now)
                cached_markets = ex.markets

            # Проверяем символ
            current_symbol = symbol
            if current_symbol not in cached_markets:
                alt = current_symbol.replace("/", "")
                if alt in cached_markets:
                    current_symbol = alt
                else:
                    return None

            # === ГЛАВНОЕ ИЗМЕНЕНИЕ: Берём ORDERBOOK вместо Last Price ===
            # Получаем стакан (ордербук) с ограничением
            orderbook = await asyncio.wait_for(
                ex.fetch_order_book(current_symbol, limit=5),
                timeout=(15.0 + attempt * 5)
            )
            
            # Извлекаем лучшую цену покупки (Bid) и продажи (Ask)
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])
            
            bid = _num(bids[0][0]) if bids else None
            ask = _num(asks[0][0]) if asks else None
            
            # Получаем Last Price из тикера для справки
            ticker = await asyncio.wait_for(
                ex.fetch_ticker(current_symbol),
                timeout=(15.0 + attempt * 5)
            )
            last = _num(ticker.get("last"))
            
            return ExchangePrice(
                exchange=exchange_id,
                symbol=current_symbol,
                bid=bid,
                ask=ask,
                last=last,
                volume_24h=_num(ticker.get("quoteVolume")),
                change_24h_pct=_num(ticker.get("percentage")),
                source="orderbook"  # Отметили, что данные из orderbook
            )
        except Exception as e:
            if attempt == attempts - 1:
                logger.warning(f"Final failure for {exchange_id} after {attempts} attempts: {e}")
                FAILED_EXCHANGES[exchange_id] = now
            else:
                # Экспоненциальная пауза перед ретраем
                await asyncio.sleep(1 + attempt * 2)
    return None


async def get_exchange_trading_fees(exchange_id: str) -> dict:
    """
    Получает комиссии биржи (Taker Fee).
    Результаты кешируются на 24 часа.
    """
    now = time.time()
    cached_fees, ts = EXCHANGE_FEES_CACHE.get(exchange_id, (None, 0))
    
    if cached_fees and (now - ts < FEES_CACHE_TTL):
        return cached_fees

    try:
        ex = await get_exchange_instance(exchange_id)
        if not ex:
            return {"buy_taker": 0.1, "sell_taker": 0.1}  # Default fallback
        
        # Получаем информацию о комиссиях
        if hasattr(ex, "describe"):
            desc = ex.describe()
            fees = desc.get("fees", {})
            
            buy_fee = fees.get("trading", {}).get("maker", 0.1)
            sell_fee = fees.get("trading", {}).get("taker", 0.1)
            
            result = {
                "buy_taker": float(buy_fee),
                "sell_taker": float(sell_fee)
            }
        else:
            result = {"buy_taker": 0.1, "sell_taker": 0.1}
        
        EXCHANGE_FEES_CACHE[exchange_id] = (result, now)
        logger.info(f"Fees for {exchange_id}: buy={result['buy_taker']}%, sell={result['sell_taker']}%")
        return result
        
    except Exception as e:
        logger.warning(f"Failed to get fees for {exchange_id}: {e}")
        return {"buy_taker": 0.1, "sell_taker": 0.1}  # Default fallback


async def check_wallet_status(exchange_id: str, symbol: str) -> dict:
    """
    Проверяет статус вывода/ввода кошельков для монеты на бирже.
    
    Returns:
        {
            "can_withdraw": bool,
            "can_deposit": bool,
            "status": str  # "ok", "maintenance", "unknown"
        }
    """
    cache_key = f"{exchange_id}:{symbol}"
    now = time.time()
    cached_status, ts = WALLET_STATUS_CACHE.get(cache_key, (None, 0))
    
    if cached_status and (now - ts < WALLET_CACHE_TTL):
        return cached_status

    try:
        ex = await get_exchange_instance(exchange_id)
        if not ex:
            return {"can_withdraw": True, "can_deposit": True, "status": "unknown"}
        
        # Получаем информацию о валютах
        currencies = await ex.fetch_currencies()
        
        # Ищем монету (symbol может быть "BTC" или "BTC/USDT")
        base = symbol.split("/")[0].upper()
        
        if base in currencies:
            currency = currencies[base]
            active = currency.get("active", True)
            
            # Проверяем статус вывода/ввода
            limits = currency.get("limits", {})
            withdraw_enabled = limits.get("withdraw", {}).get("enabled", True)
            deposit_enabled = limits.get("deposit", {}).get("enabled", True)
            
            status_result = {
                "can_withdraw": active and withdraw_enabled,
                "can_deposit": active and deposit_enabled,
                "status": "ok" if active else "maintenance"
            }
        else:
            # Монета не найдена на бирже
            status_result = {
                "can_withdraw": False,
                "can_deposit": False,
                "status": "unknown"
            }
        
        WALLET_STATUS_CACHE[cache_key] = (status_result, now)
        logger.info(f"Wallet status for {base} on {exchange_id}: withdraw={status_result['can_withdraw']}, deposit={status_result['can_deposit']}")
        return status_result
        
    except Exception as e:
        logger.warning(f"Failed to check wallet status for {exchange_id}/{symbol}: {e}")
        return {"can_withdraw": True, "can_deposit": True, "status": "unknown"}


async def calc_arbitrage_new(
    prices: list[ExchangePrice],
    investment_amount: float = 1000.0,
    network_fee_usd: float = 1.0,
    min_profit_pct: float = 2.0
) -> tuple[ProfitabilityResult, str, str] | None:
    """
    Рассчитывает профитность арбитража на основе реальных цен из orderbook.
    
    Возвращает: (ProfitabilityResult, buy_exchange, sell_exchange) или None
    
    Проверяет:
    1. Bid/Ask из orderbook (не Last Price)
    2. Реальные комиссии бирж (fetch_currencies/fees)
    3. Статус кошельков (allowWithdraw, allowDeposit)
    4. Чистая прибыль >= 2% (жесткий фильтр)
    """
    # Оставляем только те, где есть цены и нормальный объем
    valid = [p for p in prices if p.bid and p.ask and (p.volume_24h or 0) > 50000]
    if len(valid) < 2:
        return None
    
    best_result = None
    best_exchange_pair = None
    
    # Ищем лучшую пару среди РАЗНЫХ бирж
    for i in range(len(valid)):
        for j in range(len(valid)):
            if i == j: continue 
            
            ex_buy = valid[i]    # Покупаем по Ask
            ex_sell = valid[j]   # Продаем по Bid
            
            if ex_buy.ask <= 0 or ex_sell.bid <= 0:
                continue
            
            # === ПРОВЕРЯЕМ СТАТУС КОШЕЛЬКОВ ===
            # Биржа A (покупка): нужен открытый вывод
            wallet_buy = await check_wallet_status(ex_buy.exchange, ex_buy.symbol)
            if not wallet_buy["can_withdraw"]:
                logger.warning(f"⚠️ Cannot withdraw {ex_buy.symbol} from {ex_buy.exchange.upper()}: {wallet_buy['status']}")
                continue
            
            # Биржа B (продажа): нужен открытый ввод
            wallet_sell = await check_wallet_status(ex_sell.exchange, ex_sell.symbol)
            if not wallet_sell["can_deposit"]:
                logger.warning(f"⚠️ Cannot deposit {ex_sell.symbol} to {ex_sell.exchange.upper()}: {wallet_sell['status']}")
                continue
            
            # === ПОЛУЧАЕМ РЕАЛЬНЫЕ КОМИССИИ ===
            fees_buy = await get_exchange_trading_fees(ex_buy.exchange)
            fees_sell = await get_exchange_trading_fees(ex_sell.exchange)
            
            # === РАССЧИТЫВАЕМ ПРОФИТНОСТЬ ===
            result = calculate_net_profit(
                buy_price=ex_buy.ask,
                sell_price=ex_sell.bid,
                buy_exchange=ex_buy.exchange,
                sell_exchange=ex_sell.exchange,
                buy_taker_fee_pct=fees_buy["buy_taker"],
                sell_taker_fee_pct=fees_sell["sell_taker"],
                network_fee_usd=network_fee_usd,
                investment_amount=investment_amount,
                min_profit_pct=min_profit_pct
            )
            
            # Логируем только профитные связки
            if result.is_profitable:
                logger.info(f"✅ PROFITABLE: {ex_buy.symbol} {ex_buy.exchange.upper()} → {ex_sell.exchange.upper()}: {result.net_profit_pct:.4f}%")
            
            # Выбираем лучшую профитную связку
            if result.is_profitable:
                if best_result is None or result.net_profit_pct > best_result.net_profit_pct:
                    best_result = result
                    best_exchange_pair = (ex_buy.exchange, ex_sell.exchange)
    
    if best_result and best_exchange_pair:
        return (best_result, best_exchange_pair[0], best_exchange_pair[1])
    
    return None


# === LEGACY COMPATIBILITY (для старого кода) ===
def calc_arbitrage(prices: list[ExchangePrice]) -> tuple[float, float, str, str] | None:
    """
    DEPRECATED: Используй calc_arbitrage_new() вместо этого!
    
    Это оставлено для обратной совместимости с форматированием.
    """
    valid = [p for p in prices if p.bid and p.ask and (p.volume_24h or 0) > 50000]
    if len(valid) < 2:
        return None
    
    best_pair = None
    max_pct = -999.0
    
    for i in range(len(valid)):
        for j in range(len(valid)):
            if i == j: continue 
            
            ex_buy = valid[i]
            ex_sell = valid[j]
            
            if ex_buy.ask <= 0: continue
            
            # Упрощенный расчет (без реальных комиссий)
            profit = ex_sell.bid - ex_buy.ask
            pct = ((profit / ex_buy.ask) * 100) - 0.2  # Примерно 0.2% комиссий
            
            if pct > max_pct:
                max_pct = pct
                best_pair = (profit, pct, ex_buy.exchange, ex_sell.exchange)
    
    return best_pair


import aiohttp

# Хранение последних сигналов для предотвращения спама
LAST_SIGNALS = {}
# История цен для отслеживания скачков
PRICE_HISTORY = {}
# Время последней очистки PRICE_HISTORY
LAST_PRICE_HISTORY_CLEANUP = time.time()

async def get_top_movers(exchanges: list[str] = None, limit: int = 3) -> dict:
    """Получает топ монеты по волатильности за 24ч по биржам.

    Returns:
        {exchange: [(symbol, change_pct, bid, ask), ...]}

    Пробует получить данные с максимум 3 доступных бирж.
    """
    # Биржи, которые заблокированы на облачных серверах (Render)
    BLOCKED_ON_RENDER = {"binance", "bybit"}

    if not exchanges:
        # Порядок предпочтения: пропускаем заблокированные
        all_exchanges = ["okx", "kucoin", "gate", "mexc", "htx", "upbit", "huobi", "coinex"]
        exchanges = [e for e in all_exchanges if e not in BLOCKED_ON_RENDER]
        # Добавляем в конец (для fallback, хотя скорее всего не сработают)
        exchanges += list(BLOCKED_ON_RENDER)

    result = {}
    used_exchanges = set()
    max_exchanges = 3  # Максимум 3 биржи в результате

    for exchange in exchanges:
        # Пропускаем заблокированные биржи
        if exchange in BLOCKED_ON_RENDER:
            logger.info(f"⏭️ Skipping {exchange} (blocked on Render)")
            continue

        # Пробуем до 3 разных бирж (на случай, если несколько заблокированы)
        if len(used_exchanges) >= max_exchanges:
            logger.info(f"Got data from {len(used_exchanges)} exchanges, stopping")
            break

        try:
            logger.info(f"Trying to get movers from {exchange}...")
            ex = await get_exchange_instance(exchange)
            if not ex:
                logger.warning(f"{exchange} not available")
                continue

            # Загружаем маркеты
            await asyncio.wait_for(ex.load_markets(), timeout=30.0)
            symbols = list(ex.symbols)[:80]  # Топ 80 монет

            # Получаем тикеры
            movers = []
            tasks = [asyncio.wait_for(ex.fetch_ticker(s), timeout=15.0) for s in symbols[:50]]  # Берем первые 50
            tickers = await asyncio.gather(*tasks, return_exceptions=True)

            successful = 0
            for ticker in tickers:
                if isinstance(ticker, dict) and ticker.get("percentage"):
                    change = _num(ticker.get("percentage"))
                    if change is not None:
                        symbol = ticker.get("symbol", "")
                        bid = _num(ticker.get("bid"))
                        ask = _num(ticker.get("ask"))
                        movers.append((symbol, change, bid, ask))
                        successful += 1

            if successful > 0:
                # Сортируем по абсолютному значению изменения
                movers.sort(key=lambda x: abs(x[1]), reverse=True)
                result[exchange] = movers[:limit]
                used_exchanges.add(exchange)
                logger.info(f"✅ Got {successful} movers from {exchange}")
            else:
                logger.warning(f"No valid tickers from {exchange}")

        except asyncio.TimeoutError:
            logger.warning(f"Timeout for {exchange}")
        except Exception as e:
            logger.warning(f"Failed to get movers from {exchange}: {e}")

    return result


async def format_movers(movers_data: dict) -> str:
    """Форматирует топ монеты в красивое сообщение без preview ссылок."""
    if not movers_data:
        return "Не удалось получить данные о движениях цен."

    lines = ["🔥 <b>ТОП ДВИЖЕНИЯ за 24 часа</b>\n"]

    exchange_names = {
        "binance": "Binance USDT-M",
        "bybit": "Bybit USDT Perpetual",
        "okx": "OKX USDT-M",
        "kucoin": "KuCoin",
        "gate": "Gate.io",
        "mexc": "MEXC",
        "htx": "HTX",
        "upbit": "Upbit"
    }

    total_count = 0
    for exchange, movers in movers_data.items():
        if not movers:
            continue

        exchange_display = exchange_names.get(exchange, exchange.upper())
        lines.append(f"\n{exchange_display} 🔥")
        lines.append("─" * 30)

        for i, (symbol, change, bid, ask) in enumerate(movers, 1):
            emoji = "📈" if change > 0 else "📉"
            # Без ссылок — просто текст
            lines.append(f"{i}️⃣ {emoji} <b>{change:+.1f}%</b> — {symbol}")
            total_count += 1

    lines.append(f"\n<i>Всего {total_count} монет с макс движением</i>")
    return "\n".join(lines)


async def get_fear_greed_index() -> str:
    """Получает индекс страха и жадности с Alternative.me"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.alternative.me/fng/") as resp:
                data = await resp.json()
                val = int(data["data"][0]["value"])
                label = data["data"][0]["value_classification"]
                
                emoji = "😨" if val < 25 else "😰" if val < 45 else "😐" if val < 60 else "😊" if val < 75 else "🤑"
                return f"{emoji} <b>Индекс страха и жадности: {val}/100</b> ({label})"
    except Exception:
        return ""

def _cleanup_price_history():
    """Очищает старые данные из PRICE_HISTORY для предотвращения утечки памяти."""
    global LAST_PRICE_HISTORY_CLEANUP
    now = time.time()
    
    if now - LAST_PRICE_HISTORY_CLEANUP > PRICE_HISTORY_CLEANUP_INTERVAL:
        if len(PRICE_HISTORY) > MAX_PRICE_HISTORY_SIZE:
            # Удаляем половину самых старых записей
            keys_to_delete = list(PRICE_HISTORY.keys())[:len(PRICE_HISTORY) // 2]
            for key in keys_to_delete:
                del PRICE_HISTORY[key]
            logger.info(f"Очищена история цен: удалено {len(keys_to_delete)} записей")
        LAST_PRICE_HISTORY_CLEANUP = now

async def scan_top_arbitrage(bases: list[str], exchanges: list[str], min_arb_pct: float = 0.0):
    """Сканирует арбитраж используя НОВЫЙ calc_arbitrage_new с жесткой фильтрацией."""
    async def _scan(base):
        symbol = f"{base}/USDT"
        prices = await fetch_prices(symbol, exchanges)
        arb = await calc_arbitrage_new(prices, min_profit_pct=min_arb_pct)
        
        if arb:
            result_obj, buy_ex, sell_ex = arb
            # Возвращаем совместимый с форматом формат
            return (base, result_obj.net_profit_usd, result_obj.net_profit_pct, buy_ex, sell_ex)
        return None

    results = await asyncio.gather(*[_scan(b) for b in bases])
    valid = [r for r in results if r]
    valid.sort(key=lambda x: x[2], reverse=True)  # Сортируем по % прибыли
    return valid

async def get_new_signals(bases: list[str], exchanges: list[str], min_pct: float):
    """Ищет новые возможности для арбитража, которых не было в прошлый раз."""
    items = await scan_top_arbitrage(bases, exchanges, min_pct)
    new_signals = []
    now = time.time()
    
    for base, profit_usd, pct, buy_ex, sell_ex in items:
        last_pct, last_ts = LAST_SIGNALS.get(base, (0.0, 0))
        # Условия для отправки сигнала:
        # 1. Арбитраж выше порога пользователя
        # 2. Монета новая ИЛИ прошло более 15 минут ИЛИ процент вырос на 0.3%+
        if pct >= min_pct:
            if (now - last_ts > 900) or (pct > last_pct + 0.3):
                new_signals.append((base, profit_usd, pct, buy_ex, sell_ex))
                LAST_SIGNALS[base] = (pct, now)
                
    return new_signals


async def get_price_jumps(bases: list[str], threshold_pct: float = 3.0):
    """Отслеживает резкие изменения цены (с fallback на разные биржи)."""
    # Периодическая очистка истории цен
    _cleanup_price_history()

    jumps = []
    # Биржи для проверки (в порядке предпочтения)
    price_sources = ["kucoin", "bybit", "okx", "binance"]
    symbol_list = [f"{b}/USDT" for b in bases[:15]]

    # Пробуем биржи по очереди, пока не получим цены
    results = None
    for exchange in price_sources:
        tasks = [_fetch_one_ccxt(exchange, s) for s in symbol_list]
        results = await asyncio.gather(*tasks)
        if any(r for r in results):  # Если хотя бы одна биржа ответила
            break
    
    for p in results:
        if not p or not p.last: continue
        base = p.symbol.split("/")[0]
        
        old_price = PRICE_HISTORY.get(base)
        if old_price:
            change = ((p.last - old_price) / old_price) * 100
            if abs(change) >= threshold_pct:
                jumps.append((base, change, p.last))
        
        PRICE_HISTORY[base] = p.last
             
    return jumps

def format_price_table(symbol: str, prices: list[ExchangePrice], min_arb_pct: float = 0.0) -> str:
    if not prices: return f"❌ {symbol} не найден"

    arb = calc_arbitrage(prices)
    lines = [f"<b>{symbol}</b>"]

    if arb:
        profit, pct, buy_ex, sell_ex = arb
        # Показываем арбитраж ТОЛЬКО если он положительный (> 0.01%)
        if pct > 0.01:
            lines.append(f"🟢 Арбитраж: <b>{pct:.2f}%</b>")
            lines.append(f"   {buy_ex.upper()} → {sell_ex.upper()}")
            lines.append("") # Пустая строка только если есть арбитраж

    # Сортируем: сначала самые дорогие (лучшие для продажи), потом дешевые
    sorted_prices = sorted(prices, key=lambda x: x.last or 0, reverse=True)
    for p in sorted_prices:
        buy_str = f"{p.ask:g}" if p.ask else "?"
        sell_str = f"{p.bid:g}" if p.bid else "?"
        lines.append(f"• {p.exchange.upper()}")
        lines.append(f"  Покупка <code>{buy_str}</code>")
        lines.append(f"  Продажа <code>{sell_str}</code>")
    return "\n".join(lines)

def format_top_arbitrage(items: list, min_arb_pct: float) -> str:
    if not items: return "Ничего не найдено"
    
    # Оставляем только РЕАЛЬНО выгодные связки (> 0.01%)
    # Если пользователь сам поставил порог выше (например 0.33), используем его
    threshold = max(0.01, min_arb_pct)
    display_items = [it for it in items if it[2] >= threshold]

    if not display_items: 
        return "📊 <b>Топ арбитраж</b>\n\nВыгодных связок прямо сейчас нет. Попробуйте позже или добавьте больше бирж."

    lines = ["📊 <b>Топ арбитраж</b>", ""]
    for base, profit_usd, pct, buy_ex, sell_ex in display_items:
        lines.append(f"• <b>{base}</b>: <code>{pct:.2f}%</code> (${profit_usd:.2f}) {buy_ex.upper()} → {sell_ex.upper()}")
    return "\n".join(lines)

def normalize_symbol(text: str) -> str:
    t = text.upper().replace(" ", "").replace("-", "").replace("_", "")
    if "/" not in t: t = f"{t}/USDT"
    return t

def symbol_base(symbol: str) -> str:
    return symbol.split("/")[0]
