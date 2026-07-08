"""Модуль для интеграции с DEX (децентрализованные биржи).Поддерживает: Raydium (Solana), Ston.fi (TON), и другие через GeckoTerminal API."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, List
import aiohttp

logger = logging.getLogger(__name__)

# GeckoTerminal API Base
GECKO_TERMINAL_API = "https://api.geckoterminal.com/api/v2"

# Поддерживаемые DEX сети
SUPPORTED_DEX_NETWORKS = {
    "solana": "raydium",
    "ton": "ston_fi",
}


@dataclass
class DEXToken:
    """Представление токена на DEX."""
    symbol: str
    name: str
    address: str
    price_usd: float
    market_cap_usd: Optional[float] = None
    volume_24h_usd: Optional[float] = None
    liquidity_usd: Optional[float] = None
    price_change_24h_pct: Optional[float] = None
    network: str = "solana"
    dex: str = "raydium"
    source: str = "geckoterminal"


@dataclass
class DEXArbitrageOpportunity:
    """Возможность арбитража между DEX и CEX."""
    symbol: str
    base: str
    dex_price: float
    cex_price: float
    dex_network: str
    dex_name: str
    cex_name: str
    price_diff_pct: float
    profit_side: str  # "buy_on_dex" или "buy_on_cex"
    dex_token: DEXToken


class GeckoTerminalClient:
    """Клиент для работы с GeckoTerminal API."""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.timeout = aiohttp.ClientTimeout(total=30)
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Получает или создает aiohttp сессию."""
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self.session
    
    async def close(self):
        """Закрывает сессию."""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def get_top_new_tokens(
        self,
        network: str = "solana",
        dex: str = "raydium",
        limit: int = 20,
        sort_by: str = "h24_volume"  # h1_volume, h24_volume, market_cap
    ) -> List[DEXToken]:
        """Получает топ новых токенов с DEX."""
        try:
            session = await self._get_session()
            url = f"{GECKO_TERMINAL_API}/networks/{network}/dexes/{dex}/tokens"
            params = {
                "sort": sort_by,
                "order": "desc",
                "limit": min(limit, 250),
                "page": 1
            }
            
            logger.info(f"Fetching {limit} tokens from {dex} ({network})...")
            
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning(f"GeckoTerminal returned {resp.status}")
                    return []
                
                data = await resp.json()
                tokens = data.get("data", [])
                result = []
                
                for token_data in tokens:
                    try:
                        attrs = token_data.get("attributes", {})
                        token = DEXToken(
                            symbol=attrs.get("symbol", "UNKNOWN"),
                            name=attrs.get("name", ""),
                            address=token_data.get("id", ""),
                            price_usd=float(attrs.get("price_usd", 0) or 0),
                            market_cap_usd=self._safe_float(attrs.get("market_cap_usd")),
                            volume_24h_usd=self._safe_float(attrs.get("volume_usd", {}).get("h24")),
                            liquidity_usd=self._safe_float(attrs.get("total_liquidity_usd")),
                            price_change_24h_pct=self._safe_float(attrs.get("price_change_percentage", {}).get("h24")),
                            network=network,
                            dex=dex,
                        )
                        if token.liquidity_usd and token.liquidity_usd >= 10000:
                            result.append(token)
                    except Exception as e:
                        logger.warning(f"Failed to parse token: {e}")
                        continue
                
                logger.info(f"Got {len(result)} tokens from {dex}")
                return result
        except Exception as e:
            logger.error(f"Error fetching tokens: {e}")
            return []
    
    @staticmethod
    def _safe_float(value) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except (ValueError, TypeError):
            return None


async def scan_dex_tokens(
    network: str = "solana",
    limit: int = 20,
    min_liquidity_usd: float = 10000.0
) -> List[DEXToken]:
    """Сканирует новые токены на DEX."""
    dex = SUPPORTED_DEX_NETWORKS.get(network, "raydium")
    client = GeckoTerminalClient()
    try:
        tokens = await client.get_top_new_tokens(
            network=network,
            dex=dex,
            limit=limit,
            sort_by="h24_volume"
        )
        filtered = [
            t for t in tokens
            if t.liquidity_usd and t.liquidity_usd >= min_liquidity_usd
        ]
        return filtered
    finally:
        await client.close()


async def find_dex_cex_arbitrage(
    dex_tokens: List[DEXToken],
    cex_prices: dict
) -> List[DEXArbitrageOpportunity]:
    """Ищет арбитраж между DEX и CEX ценами."""
    opportunities = []
    
    for dex_token in dex_tokens:
        cex_price = cex_prices.get(dex_token.symbol)
        if not cex_price or cex_price <= 0:
            continue
        
        dex_price = dex_token.price_usd
        if dex_price <= 0:
            continue
        
        price_diff_pct = ((cex_price - dex_price) / dex_price) * 100
        if abs(price_diff_pct) < 2.0:
            continue
        
        profit_side = "buy_on_dex" if price_diff_pct > 0 else "buy_on_cex"
        opp = DEXArbitrageOpportunity(
            symbol=f"{dex_token.symbol}/USDT",
            base=dex_token.symbol,
            dex_price=dex_price,
            cex_price=cex_price,
            dex_network=dex_token.network,
            dex_name=dex_token.dex,
            cex_name="MEXC",
            price_diff_pct=abs(price_diff_pct),
            profit_side=profit_side,
            dex_token=dex_token,
        )
        opportunities.append(opp)
    
    opportunities.sort(key=lambda x: x.price_diff_pct, reverse=True)
    return opportunities


def format_dex_tokens(tokens: List[DEXToken], limit: int = 10) -> str:
    """Форматирует список DEX токенов для Telegram."""
    if not tokens:
        return "Не найдено новых токенов на DEX"
    
    lines = ["🚀 <b>Топ новые токены на DEX</b>\n"]
    for i, token in enumerate(tokens[:limit], 1):
        price_change = ""
        if token.price_change_24h_pct:
            emoji = "📈" if token.price_change_24h_pct > 0 else "📉"
            price_change = f" {emoji} {token.price_change_24h_pct:+.2f}%"
        liquidity = f"${token.liquidity_usd:,.0f}" if token.liquidity_usd else "?"
        volume = f"${token.volume_24h_usd:,.0f}" if token.volume_24h_usd else "?"
        lines.append(f"{i}. <b>{token.symbol}</b> ({token.name})\n   💰 Цена: <code>${token.price_usd:.8f}</code>{price_change}\n   💧 Ликвидность: {liquidity} | 📊 Объем 24ч: {volume}\n")
    
    return "\n".join(lines)


async def scan_dex_for_signals(
    dex_network: str = "solana",
    cex_exchanges: list = None
) -> tuple[List[DEXToken], List[DEXArbitrageOpportunity]]:
    """Полный цикл сканирования DEX для поиска сигналов."""
    from market import fetch_prices, normalize_symbol
    if not cex_exchanges:
        cex_exchanges = ["mexc", "okx"]
    
    logger.info(f"Starting DEX scan for {dex_network}...")
    tokens = await scan_dex_tokens(network=dex_network, limit=20, min_liquidity_usd=10000.0)
    if not tokens:
        logger.warning(f"No tokens found on {dex_network}")
        return [], []
    
    logger.info(f"Found {len(tokens)} tokens on {dex_network}")
    cex_prices = {}
    tasks = [fetch_prices(normalize_symbol(f"{token.symbol}/USDT"), cex_exchanges) for token in tokens]
    all_prices = await asyncio.gather(*tasks, return_exceptions=True)
    
    for i, token in enumerate(tokens):
        try:
            prices = all_prices[i]
            if isinstance(prices, list) and prices:
                valid_prices = [p.last for p in prices if p.last]
                if valid_prices:
                    avg_price = sum(valid_prices) / len(valid_prices)
                    cex_prices[token.symbol] = avg_price
        except Exception as e:
            logger.warning(f"Failed to get CEX price for {token.symbol}: {e}")
    
    logger.info(f"Got CEX prices for {len(cex_prices)} tokens")
    opportunities = await find_dex_cex_arbitrage(tokens, cex_prices)
    logger.info(f"Found {len(opportunities)} arbitrage opportunities")
    return tokens, opportunities
