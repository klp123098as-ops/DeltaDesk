from __future__ import annotations

import asyncio

import httpx

from market import ExchangePrice

TIMEOUT = 25.0

COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "DOGE": "dogecoin",
    "XRP": "ripple",
    "BNB": "binancecoin",
    "ADA": "cardano",
    "TRX": "tron",
    "TON": "the-open-network",
    "LTC": "litecoin",
    "DOT": "polkadot",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "MATIC": "matic-network",
    "POL": "polygon-ecosystem-token",
}

# Кэш поиска по тикеру (PEPE, SHIB и т.д. — без ручного добавления)
_COINGECKO_SEARCH_CACHE: dict[str, str | None] = {}


async def resolve_coingecko_id(base: str) -> str | None:
    symbol = base.upper()
    if symbol in COINGECKO_IDS:
        return COINGECKO_IDS[symbol]
    if symbol in _COINGECKO_SEARCH_CACHE:
        return _COINGECKO_SEARCH_CACHE[symbol]

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(
                "https://api.coingecko.com/api/v3/search",
                params={"query": symbol},
            )
            r.raise_for_status()
            for coin in r.json().get("coins", []):
                if (coin.get("symbol") or "").upper() == symbol:
                    coin_id = coin.get("id")
                    if coin_id:
                        _COINGECKO_SEARCH_CACHE[symbol] = coin_id
                        return coin_id
    except Exception:
        pass

    _COINGECKO_SEARCH_CACHE[symbol] = None
    return None


def _f(value, scale: float = 1.0) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value) * scale
    except (TypeError, ValueError):
        return None


def _parse_bybit(data: dict, exchange_id: str) -> ExchangePrice | None:
    items = data.get("result", {}).get("list") or []
    if not items:
        return None
    t = items[0]
    return ExchangePrice(
        exchange=exchange_id,
        bid=_f(t.get("bid1Price")),
        ask=_f(t.get("ask1Price")),
        last=_f(t.get("lastPrice")),
        volume_24h=_f(t.get("turnover24h")),
        change_24h_pct=_f(t.get("price24hPcnt"), scale=100),
    )


def _parse_okx(data: dict, exchange_id: str) -> ExchangePrice | None:
    items = data.get("data") or []
    if not items:
        return None
    t = items[0]
    return ExchangePrice(
        exchange=exchange_id,
        bid=_f(t.get("bidPx")),
        ask=_f(t.get("askPx")),
        last=_f(t.get("last")),
        volume_24h=_f(t.get("volCcy24h")),
        change_24h_pct=None,
    )


def _parse_mexc_book(data: dict | list, exchange_id: str) -> ExchangePrice | None:
    t = data[0] if isinstance(data, list) else data
    if not t:
        return None
    bid, ask = _f(t.get("bidPrice")), _f(t.get("askPrice"))
    last = (bid + ask) / 2 if bid and ask else bid or ask
    return ExchangePrice(
        exchange=exchange_id,
        bid=bid,
        ask=ask,
        last=last,
        volume_24h=None,
        change_24h_pct=None,
    )


def _parse_gate(data: dict | list, exchange_id: str) -> ExchangePrice | None:
    items = data if isinstance(data, list) else [data]
    if not items:
        return None
    t = items[0]
    return ExchangePrice(
        exchange=exchange_id,
        bid=_f(t.get("highest_bid")),
        ask=_f(t.get("lowest_ask")),
        last=_f(t.get("last")),
        volume_24h=_f(t.get("quote_volume")),
        change_24h_pct=_f(t.get("change_percentage")),
    )


DIRECT_HANDLERS = {
    "bybit": (
        "https://api.bybit.com/v5/market/tickers",
        lambda base: {"category": "spot", "symbol": f"{base}USDT"},
        _parse_bybit,
    ),
    "okx": (
        "https://www.okx.com/api/v5/market/ticker",
        lambda base: {"instId": f"{base}-USDT"},
        _parse_okx,
    ),
    "mexc": (
        "https://api.mexc.com/api/v3/ticker/bookTicker",
        lambda base: {"symbol": f"{base}USDT"},
        _parse_mexc_book,
    ),
    "gate": (
        "https://api.gateio.ws/api/v4/spot/tickers",
        lambda base: {"currency_pair": f"{base}_USDT"},
        _parse_gate,
    ),
}


async def _fetch_direct(
    client: httpx.AsyncClient, exchange_id: str, base: str
) -> ExchangePrice | None:
    spec = DIRECT_HANDLERS.get(exchange_id)
    if not spec:
        return None
    url, params_fn, parser = spec
    try:
        r = await client.get(url, params=params_fn(base))
        r.raise_for_status()
        return parser(r.json(), exchange_id)
    except Exception:
        return None


async def fetch_direct_prices(base: str, exchanges: list[str]) -> list[ExchangePrice]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        tasks = [
            _fetch_direct(client, ex, base) for ex in exchanges if ex in DIRECT_HANDLERS
        ]
        results = await asyncio.gather(*tasks)
    return [r for r in results if r and r.last]


async def fetch_coingecko_prices(base: str, exchanges: list[str]) -> list[ExchangePrice]:
    coin_id = await resolve_coingecko_id(base)
    if not coin_id:
        return []

    want = {e.lower() for e in exchanges}
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/tickers"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(url, params={"include_exchange_logo": "false"})
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []

    rows: list[ExchangePrice] = []
    seen: set[str] = set()

    for t in data.get("tickers", []):
        market = t.get("market") or {}
        ex_id = (market.get("identifier") or "").lower()
        if ex_id not in want or ex_id in seen:
            continue
        if (t.get("target") or "").upper() != "USDT":
            continue
        last = _f(t.get("last"))
        if not last:
            continue
        seen.add(ex_id)
        rows.append(
            ExchangePrice(
                exchange=ex_id,
                bid=_f(t.get("bid")),
                ask=_f(t.get("ask")),
                last=last,
                volume_24h=_f(t.get("volume")),
                change_24h_pct=None,
            )
        )

    return rows
