from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import ccxt.async_support as ccxt

logger = logging.getLogger(__name__)

# Настройки таймаутов
REQUEST_TIMEOUT_MS = 10000

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

def _num(val) -> float | None:
    if val is None: return None
    try: return float(val)
    except (ValueError, TypeError): return None

async def get_exchange_instance(exchange_id: str):
    if exchange_id in EXCHANGES_INSTANCES:
        return EXCHANGES_INSTANCES[exchange_id]
    
    cls = getattr(ccxt, exchange_id, None)
    if not cls: return None
    
    instance = cls({"enableRateLimit": True, "timeout": REQUEST_TIMEOUT_MS})
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
    if exchange_id in FAILED_EXCHANGES:
        if now - FAILED_EXCHANGES[exchange_id] < FAILED_CACHE_TTL:
            return None

    ex = await get_exchange_instance(exchange_id)
    if not ex: return None

    try:
        # Загрузка рынков с кешем
        cached_markets, ts = MARKETS_CACHE.get(exchange_id, (None, 0))
        if not cached_markets or (now - ts > MARKET_CACHE_TTL):
            await asyncio.wait_for(ex.load_markets(), timeout=15.0)
            MARKETS_CACHE[exchange_id] = (ex.markets, now)
            cached_markets = ex.markets

        # Проверяем символ в загруженных рынках
        if symbol not in cached_markets:
            # Попробуем найти символ без слеша, если не нашли со слешем
            alt_symbol = symbol.replace("/", "")
            if alt_symbol in cached_markets:
                symbol = alt_symbol
            else:
                return None

        ticker = await asyncio.wait_for(ex.fetch_ticker(symbol), timeout=10.0)
        return ExchangePrice(
            exchange=exchange_id,
            symbol=symbol,
            bid=_num(ticker.get("bid")),
            ask=_num(ticker.get("ask")),
            last=_num(ticker.get("last")),
            volume_24h=_num(ticker.get("quoteVolume")),
            change_24h_pct=_num(ticker.get("percentage")),
        )
    except Exception as e:
        logger.warning(f"Ошибка {exchange_id} для {symbol}: {e}")
        # Не добавляем в FAILED сразу, если это просто таймаут одной монеты
        return None

def calc_arbitrage(prices: list[ExchangePrice]) -> tuple[float, float, str, str] | None:
    valid = [p for p in prices if p.bid and p.ask]
    if len(valid) < 2: return None
    
    best_pair = None
    max_pct = -999.0
    
    # Ищем лучшую пару среди РАЗНЫХ бирж
    for i in range(len(valid)):
        for j in range(len(valid)):
            if i == j: continue # Пропускаем одну и ту же биржу
            
            ex_buy = valid[i]  # Покупаем по Ask
            ex_sell = valid[j] # Продаем по Bid
            
            if ex_buy.ask <= 0: continue
            
            profit = ex_sell.bid - ex_buy.ask
            pct = (profit / ex_buy.ask) * 100
            
            if pct > max_pct:
                max_pct = pct
                best_pair = (profit, pct, ex_buy.exchange, ex_sell.exchange)
    
    return best_pair

# Хранение последних сигналов для предотвращения спама
LAST_SIGNALS = {}
# История цен для отслеживания скачков
PRICE_HISTORY = {}

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
    """Отслеживает резкие изменения цены на Binance."""
    jumps = []
    # Используем Binance как эталон для скачков цены
    symbol_list = [f"{b}/USDT" for b in bases[:15]]
    tasks = [_fetch_one_ccxt("binance", s) for s in symbol_list]
    results = await asyncio.gather(*tasks)
    
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
    
    for p in sorted(prices, key=lambda x: x.last or 0, reverse=True):
        lines.append(f"• {p.exchange.upper()}: <code>{p.last or '?'}</code>")
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
