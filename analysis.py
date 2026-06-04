from __future__ import annotations

from statistics import mean

import ccxt.async_support as ccxt

from config import REQUEST_TIMEOUT_MS


async def _ohlcv_from_exchange(exchange_id: str, symbol: str, limit: int = 30):
    exchange_class = getattr(ccxt, exchange_id, None)
    if exchange_class is None:
        return None

    exchange = exchange_class(
        {"enableRateLimit": True, "timeout": REQUEST_TIMEOUT_MS}
    )
    try:
        await exchange.load_markets()
        if symbol not in exchange.markets:
            return None
        return await exchange.fetch_ohlcv(symbol, timeframe="1d", limit=limit)
    except Exception:
        return None
    finally:
        await exchange.close()


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return mean(values[-period:])


def _analyze_candles(candles: list) -> dict:
    closes = [c[4] for c in candles]
    if len(closes) < 2:
        return {}

    change_24h = (closes[-1] - closes[-2]) / closes[-2] * 100
    change_7d = None
    if len(closes) >= 8:
        change_7d = (closes[-1] - closes[-8]) / closes[-8] * 100

    sma7 = _sma(closes, 7)
    sma14 = _sma(closes, 14)
    trend = "нейтральный"
    if sma7 and sma14:
        if sma7 > sma14 * 1.01:
            trend = "восходящий 📈"
        elif sma7 < sma14 * 0.99:
            trend = "нисходящий 📉"

    recent = closes[-14:] if len(closes) >= 14 else closes
    avg = mean(recent)
    volatility = (sum((x - avg) ** 2 for x in recent) / len(recent)) ** 0.5
    vol_pct = volatility / avg * 100 if avg else 0

    return {
        "change_24h": change_24h,
        "change_7d": change_7d,
        "trend": trend,
        "volatility_pct": vol_pct,
        "last": closes[-1],
    }


async def analyze_symbol(symbol: str, exchanges: list[str]) -> str:
    # Сначала биржи, которые чаще доступны из РФ/СНГ
    priority = ["bybit", "okx", "mexc", "gate", "bitget", "kucoin", "binance", "kraken"]
    ordered = [e for e in priority if e in exchanges]
    ordered += [e for e in exchanges if e not in ordered]

    for exchange_id in ordered:
        candles = await _ohlcv_from_exchange(exchange_id, symbol)
        if candles:
            stats = _analyze_candles(candles)
            if not stats:
                break
            lines = [
                f"🔍 Анализ {symbol} (данные: {exchange_id.upper()}, дневные свечи)\n",
                f"• Цена: {stats['last']:,.4f} {symbol.split('/')[1]}",
                f"• Изменение ~24ч: {_sign(stats['change_24h'])}%",
            ]
            if stats.get("change_7d") is not None:
                lines.append(f"• Изменение ~7д: {_sign(stats['change_7d'])}%")
            lines.extend(
                [
                    f"• Краткий тренд (SMA7 vs SMA14): {stats['trend']}",
                    f"• Волатильность (14д): {stats['volatility_pct']:.2f}%",
                    "",
                    "Это упрощённый технический обзор, не финансовый совет.",
                    "Для точных решений смотрите новости, листинги и объёмы на биржах.",
                ]
            )
            return "\n".join(lines)

    return (
        f"Не удалось построить анализ для {symbol}.\n"
        "Сначала проверьте цену командой /price BTC"
    )


def _sign(value: float) -> str:
    return f"+{value:.2f}" if value >= 0 else f"{value:.2f}"
