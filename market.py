from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import ccxt.async_support as ccxt

from config import REQUEST_TIMEOUT_MS

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
    instance = cls({
        "enableRateLimit": True, 
        "timeout": 30000,
        "aiohttp_proxy": None,
        "options": {"defaultType": "spot"}
    })
    EXCHANGES_INSTANCES[exchange_id] = instance
    return instance

async def close_all_exchanges():
    for ex in EXCHANGES_INSTANCES.values():
        await ex.close()
    EXCHANGES_INSTANCES.clear()

async def fetch_prices(symbol: str, exchanges: list[str]) -> list[ExchangePrice]:
    tasks = [_fetch_one_ccxt(eid, symbol) for eid in exchanges]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r]

async def _fetch_one_ccxt(exchange_id: str, symbol: str) -> ExchangePrice | None:
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
            # Загрузка рынков с кешем (таймаут 30 секунд!)
            cached_markets, ts = MARKETS_CACHE.get(exchange_id, (None, 0))
            if not cached_markets or (now - ts > MARKET_CACHE_TTL):
                # Для ретрая увеличиваем таймаут
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

            # Запрос тикера (таймаут 15-20 секунд)
            ticker = await asyncio.wait_for(ex.fetch_ticker(current_symbol), timeout=(15.0 + attempt * 5))
            return ExchangePrice(
                exchange=exchange_id,
                symbol=current_symbol,
                bid=_num(ticker.get("bid")),
                ask=_num(ticker.get("ask")),
                last=_num(ticker.get("last")),
                volume_24h=_num(ticker.get("quoteVolume")),
                change_24h_pct=_num(ticker.get("percentage")),
            )
        except Exception as e:
            if attempt == attempts - 1:
                logger.warning(f"Final failure for {exchange_id} after {attempts} attempts: {e}")
                FAILED_EXCHANGES[exchange_id] = now
            else:
                # Экспоненциальная пауза перед ретраем
                await asyncio.sleep(1 + attempt * 2)
    return None

def calc_arbitrage(prices: list[ExchangePrice]) -> tuple[float, float, str, str] | None:
    # Оставляем только те, где есть цены и нормальный объем (минимум $50,000 суточного объема)
    valid = [p for p in prices if p.bid and p.ask and (p.volume_24h or 0) > 50000]
    if len(valid) < 2: return None
    
    best_pair = None
    max_pct = -999.0
    
    # Средняя комиссия биржи (Taker) — примерно 0.1% на покупку и 0.1% на продажу
    # Итого на круг уходит ~0.2%
    FEE_ESTIMATE = 0.2
    
    # Ищем лучшую пару среди РАЗНЫХ бирж
    for i in range(len(valid)):
        for j in range(len(valid)):
            if i == j: continue 
            
            ex_buy = valid[i]  # Покупаем по Ask
            ex_sell = valid[j] # Продаем по Bid
            
            if ex_buy.ask <= 0: continue
            
            profit = ex_sell.bid - ex_buy.ask
            # Вычитаем комиссии из процента прибыли
            pct = ((profit / ex_buy.ask) * 100) - FEE_ESTIMATE
            
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
    if not exchanges:
        # Порядок предпочтения: если одна не работает, пробуем другую
        exchanges = ["okx", "kucoin", "gate", "mexc", "htx", "upbit", "bybit", "binance"]

    result = {}
    used_exchanges = set()
    max_exchanges = 3  # Максимум 3 биржи в результате

    for exchange in exchanges:
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
    async def _scan(base):
        symbol = f"{base}/USDT"
        prices = await fetch_prices(symbol, exchanges)
        arb = calc_arbitrage(prices)
        # Если порог 0 (Все%), показываем всё, где есть цена на 2+ биржах
        if arb and (min_arb_pct <= 0 or arb[1] >= min_arb_pct):
            return (base, *arb)
        return None

    results = await asyncio.gather(*[_scan(b) for b in bases])
    valid = [r for r in results if r]
    valid.sort(key=lambda x: x[2], reverse=True)
    return valid

async def get_new_signals(bases: list[str], exchanges: list[str], min_pct: float):
    """Ищет новые возможности для арбитража, которых не было в прошлый раз."""
    items = await scan_top_arbitrage(bases, exchanges, min_pct)
    new_signals = []
    now = time.time()
    
    for base, profit, pct, buy_ex, sell_ex in items:
        last_pct, last_ts = LAST_SIGNALS.get(base, (0.0, 0))
        # Условия для отправки сигнала:
        # 1. Арбитраж выше порога пользователя
        # 2. Монета новая ИЛИ прошло более 15 минут ИЛИ процент вырос на 0.3%+
        if pct >= min_pct:
            if (now - last_ts > 900) or (pct > last_pct + 0.3):
                new_signals.append((base, profit, pct, buy_ex, sell_ex))
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
    for base, profit, pct, buy_ex, sell_ex in display_items:
        lines.append(f"• <b>{base}</b>: <code>{pct:.2f}%</code> ({buy_ex.upper()} → {sell_ex.upper()})")
    return "\n".join(lines)

def normalize_symbol(text: str) -> str:
    t = text.upper().replace(" ", "").replace("-", "").replace("_", "")
    if "/" not in t: t = f"{t}/USDT"
    return t

def symbol_base(symbol: str) -> str:
    return symbol.split("/")[0]
