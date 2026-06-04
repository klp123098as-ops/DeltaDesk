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
        cached, ts = MARKETS_CACHE.get(exchange_id, (None, 0))
        if not cached or (now - ts > MARKET_CACHE_TTL):
            await asyncio.wait_for(ex.load_markets(), timeout=10.0)
            MARKETS_CACHE[exchange_id] = (ex.markets, now)

        if symbol not in ex.markets:
            return None

        ticker = await asyncio.wait_for(ex.fetch_ticker(symbol), timeout=5.0)
        return ExchangePrice(
            exchange=exchange_id,
            bid=_num(ticker.get("bid")),
            ask=_num(ticker.get("ask")),
            last=_num(ticker.get("last")),
            volume_24h=_num(ticker.get("quoteVolume")),
            change_24h_pct=_num(ticker.get("percentage")),
        )
    except Exception:
        FAILED_EXCHANGES[exchange_id] = now
        return None

def calc_arbitrage(prices: list[ExchangePrice]) -> tuple[float, float, str, str] | None:
    valid = [p for p in prices if p.bid and p.ask]
    if len(valid) < 2: return None
    
    best_bid = max(valid, key=lambda x: x.bid)
    best_ask = min(valid, key=lambda x: x.ask)
    
    if best_ask.ask <= 0: return None
    profit = best_bid.bid - best_ask.ask
    pct = (profit / best_ask.ask) * 100
    
    return (profit, pct, best_ask.exchange, best_bid.exchange)

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

def format_price_table(symbol: str, prices: list[ExchangePrice], min_arb_pct: float = 0.0) -> str:
    if not prices: return f"❌ {symbol} не найден"
    
    arb = calc_arbitrage(prices)
    lines = [f"<b>{symbol}</b>"]
    
    if arb:
        profit, pct, buy_ex, sell_ex = arb
        # Подсвечиваем, если выше порога или если выбран режим "Все%" (0)
        if pct >= min_arb_pct or min_arb_pct <= 0:
            lines.append(f"🟢 Арбитраж: <b>{pct:.2f}%</b>")
            lines.append(f"   {buy_ex.upper()} → {sell_ex.upper()}")
    
    lines.append("")
    for p in sorted(prices, key=lambda x: x.last or 0, reverse=True):
        lines.append(f"• {p.exchange.upper()}: {p.last or '?'}")
    return "\n".join(lines)

def format_top_arbitrage(items: list, min_arb_pct: float) -> str:
    if not items: return "Ничего не найдено"
    lines = ["📊 <b>Топ арбитраж</b>", ""]
    for base, profit, pct, buy_ex, sell_ex in items:
        lines.append(f"• <b>{base}</b>: {pct:.2f}% ({buy_ex.upper()} → {sell_ex.upper()})")
    return "\n".join(lines)

def normalize_symbol(text: str) -> str:
    t = text.upper().replace(" ", "").replace("-", "").replace("_", "")
    if "/" not in t: t = f"{t}/USDT"
    return t

def symbol_base(symbol: str) -> str:
    return symbol.split("/")[0]
