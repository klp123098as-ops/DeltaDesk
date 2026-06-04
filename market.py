from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import ccxt.async_support as ccxt

from config import QUOTE, REQUEST_TIMEOUT_MS

logger = logging.getLogger(__name__)

EXCHANGE_OPTIONS: dict[str, dict] = {
    "binance": {"options": {"defaultType": "spot"}},
    "bybit": {"options": {"defaultType": "spot"}},
    "okx": {"options": {"defaultType": "spot"}},
    "kucoin": {"options": {"defaultType": "spot"}},
    "gate": {"options": {"defaultType": "spot"}},
    "mexc": {"options": {"defaultType": "spot"}},
    "bitget": {"options": {"defaultType": "spot"}},
    "kraken": {},
    "cryptocom": {},
    "bingx": {"options": {"defaultType": "spot"}},
    "htx": {"options": {"defaultType": "spot"}},
    "coinex": {},
    "bitfinex": {},
}


@dataclass
class ExchangePrice:
    exchange: str
    bid: float | None
    ask: float | None
    last: float | None
    volume_24h: float | None
    change_24h_pct: float | None
    source: str = "ccxt"


def normalize_symbol(user_input: str) -> str:
    raw = user_input.strip().upper().replace("/", "").replace("-", "")
    if not raw:
        raise ValueError("Укажите монету, например: BTC")
    base = raw.split(QUOTE)[0] if raw.endswith(QUOTE) else raw
    return f"{base}/{QUOTE}"


def symbol_base(symbol: str) -> str:
    return symbol.split("/")[0]


# Кеш для рынков (чтобы не грузить список монет каждый раз)
MARKETS_CACHE: dict[str, tuple[dict, float]] = {}
MARKET_CACHE_TTL = 600  # 10 минут

# Глобальный кеш инстансов бирж для переиспользования соединений
EXCHANGES_INSTANCES: dict[str, ccxt.Exchange] = {}

async def close_all_exchanges():
    """Корректно закрывает все открытые соединения с биржами."""
    for exchange in EXCHANGES_INSTANCES.values():
        try:
            await exchange.close()
        except Exception:
            pass
    EXCHANGES_INSTANCES.clear()

async def get_exchange_instance(exchange_id: str) -> ccxt.Exchange | None:
    if exchange_id in EXCHANGES_INSTANCES:
        return EXCHANGES_INSTANCES[exchange_id]
    
    exchange_class = getattr(ccxt, exchange_id, None)
    if exchange_class is None:
        return None
    
    cfg = {"enableRateLimit": True, "timeout": REQUEST_TIMEOUT_MS}
    cfg.update(EXCHANGE_OPTIONS.get(exchange_id, {}))
    instance = exchange_class(cfg)
    EXCHANGES_INSTANCES[exchange_id] = instance
    return instance

# Глобальный кеш инстансов бирж для "Турбо-режима"
EXCHANGES_INSTANCES: dict[str, ccxt.Exchange] = {}

# Блокировка для предотвращения одновременной загрузки рынков одной биржи
MARKETS_LOCKS: dict[str, asyncio.Lock] = {}

async def get_exchange_instance(exchange_id: str) -> ccxt.Exchange | None:
    if exchange_id in EXCHANGES_INSTANCES:
        return EXCHANGES_INSTANCES[exchange_id]
    
    exchange_class = getattr(ccxt, exchange_id, None)
    if exchange_class is None:
        return None
    
    # Настройки для максимальной скорости
    cfg = {
        "enableRateLimit": True, 
        "timeout": 10000, # 10 секунд на соединение
        "options": {"preloadMarkets": False} # НЕ грузить все рынки сразу
    }
    cfg.update(EXCHANGE_OPTIONS.get(exchange_id, {}))
    instance = exchange_class(cfg)
    EXCHANGES_INSTANCES[exchange_id] = instance
    MARKETS_LOCKS[exchange_id] = asyncio.Lock()
    return instance

async def _fetch_one_ccxt(exchange_id: str, symbol: str) -> ExchangePrice | None:
    exchange = await get_exchange_instance(exchange_id)
    if not exchange:
        return None

    lock = MARKETS_LOCKS.get(exchange_id)
    
    try:
        async with lock:
            now = time.time()
            cached_markets, ts = MARKETS_CACHE.get(exchange_id, (None, 0))
            
            # Грузим рынки только если их нет или они старые
            if not cached_markets or (now - ts > MARKET_CACHE_TTL):
                logger.info("Гружу рынки для %s...", exchange_id)
                await asyncio.wait_for(exchange.load_markets(), timeout=15.0)
                MARKETS_CACHE[exchange_id] = (exchange.markets, now)

        if symbol not in exchange.markets:
            return None
            
        # Сам запрос цены (очень быстрый)
        ticker = await asyncio.wait_for(exchange.fetch_ticker(symbol), timeout=5.0)
        return ExchangePrice(
            exchange=exchange_id,
            bid=_num(ticker.get("bid")),
            ask=_num(ticker.get("ask")),
            last=_num(ticker.get("last")),
            volume_24h=_num(ticker.get("quoteVolume") or ticker.get("baseVolume")),
            change_24h_pct=_num(ticker.get("percentage")),
            source="ccxt",
        )
    except Exception as exc:
        logger.debug("Биржа %s пропущена: %s", exchange_id, str(exc))
        return None
    # НИКАКОГО exchange.close() здесь! Соединение должно жить.


def _num(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _merge_rows(rows: list[ExchangePrice]) -> list[ExchangePrice]:
    by_ex: dict[str, ExchangePrice] = {}
    for row in rows:
        if row.last is None:
            continue
        prev = by_ex.get(row.exchange)
        if prev is None:
            by_ex[row.exchange] = row
    return sorted(by_ex.values(), key=lambda r: r.last or 0)


async def fetch_prices(symbol: str, exchanges: list[str]) -> list[ExchangePrice]:
    from fallback_api import fetch_coingecko_prices, fetch_direct_prices

    base = symbol_base(symbol)

    ccxt_tasks = [_fetch_one_ccxt(ex_id, symbol) for ex_id in exchanges]
    ccxt_results = await asyncio.gather(*ccxt_tasks)
    rows = _merge_rows([r for r in ccxt_results if r is not None])

    if len(rows) >= 2:
        return rows

    direct = await fetch_direct_prices(base, exchanges)
    rows = _merge_rows(rows + direct)

    if len(rows) >= 1:
        return rows

    cg = await fetch_coingecko_prices(base, exchanges)
    for row in cg:
        row.source = "coingecko"
    return _merge_rows(cg)


def format_price_table(
    symbol: str, rows: list[ExchangePrice], min_arb_pct: float = 0.0
) -> str:
    if not rows:
        return (
            f"Не удалось получить цены для {symbol}.\n\n"
            "Возможные причины:\n"
            "• нет интернета или биржи заблокированы в вашей сети\n"
            "• монета не найдена (попробуйте ETH, SOL, DOGE)\n"
            "• слишком много бирж — попробуйте /reset и снова /price\n\n"
            "Проверка: /exchanges"
        )

    sources = {r.source for r in rows}
    via_cg = "coingecko" in sources and len(sources) == 1

    min_note = (
        f"Фильтр: арбитраж от {min_arb_pct}%+\n"
        if min_arb_pct > 0
        else ""
    )
    lines = [f"📊 {symbol} — сравнение бирж\n", min_note]
    if via_cg:
        lines.append("(данные через CoinGecko — ccxt/биржи недоступны из сети)\n")

    cheapest_buy = min(rows, key=lambda r: r.ask or r.last or float("inf"))
    best_sell = max(rows, key=lambda r: r.bid or r.last or 0)

    for row in sorted(rows, key=lambda r: r.ask or r.last or 0):
        ch = _fmt_change(row.change_24h_pct)
        vol = _fmt_volume(row.volume_24h)
        tag = ""
        if row.exchange == cheapest_buy.exchange:
            tag = " 🟢дешевле"
        if row.exchange == best_sell.exchange:
            tag += " 🔴дороже"
        lines.append(
            f"• {row.exchange.upper()}{tag}:\n"
            f"  ask {_fmt(row.ask)} | bid {_fmt(row.bid)} | "
            f"last {_fmt(row.last)}{ch}{vol}"
        )

    lines.append("")
    lines.append("💡 Где выгоднее:")
    lines.append(
        f"• Дешевле КУПИТЬ: {cheapest_buy.exchange.upper()} "
        f"(ask ≈ {_fmt(cheapest_buy.ask or cheapest_buy.last)})"
    )
    lines.append(
        f"• Выгоднее ПРОДАТЬ: {best_sell.exchange.upper()} "
        f"(bid ≈ {_fmt(best_sell.bid or best_sell.last)})"
    )

    buy_ask = cheapest_buy.ask or cheapest_buy.last
    sell_bid = best_sell.bid or best_sell.last

    if buy_ask and sell_bid and len(rows) >= 2:
        arb_usdt = sell_bid - buy_ask
        arb_pct = arb_usdt / buy_ask * 100
        if min_arb_pct > 0 and arb_pct < min_arb_pct:
            lines.append(
                f"• Арбитраж {_fmt_pct(arb_pct)} — ниже порога {min_arb_pct}%"
            )
            lines.append("  (цены выше; /min 0 — показывать всегда)")
        else:
            lines.append(
                f"• Арбитраж buy→sell: {arb_usdt:+.2f} USDT ({_fmt_pct(arb_pct)})"
            )
            if arb_usdt <= 0:
                lines.append("  (минус — комиссии съедят)")

    if len(rows) >= 2:
        lasts = [r.last for r in rows if r.last]
        low, high = min(lasts), max(lasts)
        spread = (high - low) / low * 100 if low else 0
        lines.append(f"• Разброс last: {_fmt_pct(spread)} (${high - low:,.2f})")

    lines.append(
        "\n⚠️ Комиссии, вывод и ликвидность не учтены — ориентир, не сделка."
    )
    return "\n".join(lines)


def calc_arbitrage(rows: list[ExchangePrice]) -> tuple[float, float, str, str] | None:
    """Возвращает (arb_usdt, arb_pct, buy_exchange, sell_exchange)."""
    if len(rows) < 2:
        return None
    cheapest_buy = min(rows, key=lambda r: r.ask or r.last or float("inf"))
    best_sell = max(rows, key=lambda r: r.bid or r.last or 0)
    buy_ask = cheapest_buy.ask or cheapest_buy.last
    sell_bid = best_sell.bid or best_sell.last
    if not buy_ask or not sell_bid:
        return None
    arb_usdt = sell_bid - buy_ask
    arb_pct = arb_usdt / buy_ask * 100
    return arb_usdt, arb_pct, cheapest_buy.exchange, best_sell.exchange


async def scan_top_arbitrage(
    bases: list[str],
    exchanges: list[str],
    min_arb_pct: float = 0.0,
) -> list[tuple[str, float, float, str, str]]:
    async def _scan_one(base: str):
        symbol = f"{base}/USDT"
        rows = await fetch_prices(symbol, exchanges)
        arb = calc_arbitrage(rows)
        if arb:
            _, pct, _, _ = arb
            if min_arb_pct <= 0 or pct >= min_arb_pct:
                return (base, *arb)
        return None

    tasks = [_scan_one(base) for base in bases]
    results = await asyncio.gather(*tasks)
    
    valid_results = [r for r in results if r is not None]
    valid_results.sort(key=lambda x: x[2], reverse=True)
    return valid_results


def format_top_arbitrage(
    items: list[tuple[str, float, float, str, str]], min_arb_pct: float = 0.0
) -> str:
    if not items:
        if min_arb_pct > 0:
            return (
                f"🏆 Топ арбитраж\n\n"
                f"Нет монет с арбитражем ≥ {min_arb_pct}%.\n"
                f"Понизьте порог: /min 0.03 или /min 0"
            )
        return "Нет данных для топа. Попробуйте /price BTC"
    header = "🏆 Топ арбитраж (buy ask → sell bid)"
    if min_arb_pct > 0:
        header += f" — от {min_arb_pct}%"
    lines = [header + "\n"]
    for base, usdt, pct, buy_ex, sell_ex in items[:6]:
        lines.append(
            f"• {base}: {usdt:+.2f} USDT ({_fmt_pct(pct)})\n"
            f"  купить {buy_ex.upper()} → продать {sell_ex.upper()}"
        )
    lines.append("\n⚠️ Без учёта комиссий и перевода между биржами.")
    return "\n".join(lines)


def _fmt_pct(pct: float) -> str:
    ap = abs(pct)
    if ap > 0 and ap < 0.01:
        return f"{pct:+.4f}%"
    return f"{pct:+.2f}%"


def _fmt(value: float | None) -> str:
    if value is None:
        return "—"
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.4f}"
    return f"{value:.8f}"


def _fmt_change(pct: float | None) -> str:
    if pct is None:
        return ""
    sign = "+" if pct >= 0 else ""
    return f" | 24ч: {sign}{pct:.2f}%"


def _fmt_volume(vol: float | None) -> str:
    if vol is None:
        return ""
    if vol >= 1_000_000:
        return f" | объём: {vol / 1_000_000:.2f}M"
    if vol >= 1_000:
        return f" | объём: {vol / 1_000:.1f}K"
    return f" | объём: {vol:.0f}"
