"""
DEX Scanner: поиск новых токенов в DEX (Raydium, Ston.fi) и сравнение с CEX.
Асинхронно работает с GeckoTerminal API.
"""

import asyncio
import logging
from typing import Optional
import aiohttp

logger = logging.getLogger(__name__)


class DEXScanner:
    """
    Сканер DEX для топ-20 новых токенов в Solana (Raydium) и TON (Ston.fi).
    Сравнивает цены с CEX (например, MEXC).
    """
    
    GECKO_TERMINAL_BASE = "https://api.geckoterminal.com/api/v2"
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def start(self):
        """Инициализирует aiohttp сессию."""
        if not self.session:
            self.session = aiohttp.ClientSession()
            logger.info("DEXScanner session started")
    
    async def stop(self):
        """Закрывает сессию."""
        if self.session:
            await self.session.close()
            self.session = None
            logger.info("DEXScanner session closed")
    
    async def get_top_new_tokens_raydium(self, limit: int = 20) -> list[dict]:
        """
        Получает топ новых токенов в Raydium (Solana).
        
        Returns:
            [
                {
                    'symbol': 'NEW',
                    'address': '...',
                    'price_usd': 0.001,
                    'volume_24h': 10000,
                    'market_cap': 100000,
                    'liquidity': 50000,
                    'network': 'Raydium',
                }
            ]
        """
        try:
            if not self.session:
                await self.start()
            
            # GeckoTerminal URL для Raydium (Solana)
            url = f"{self.GECKO_TERMINAL_BASE}/networks/solana/pools?order=h24_volume_usd&limit={limit}"
            
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning(f"GeckoTerminal Raydium failed: {resp.status}")
                    return []
                
                data = await resp.json()
                pools = data.get('data', [])
                
                tokens = []
                for pool in pools[:limit]:
                    attrs = pool.get('attributes', {})
                    try:
                        token = {
                            'symbol': attrs.get('name', 'UNKNOWN'),
                            'address': pool.get('id', ''),
                            'price_usd': float(attrs.get('token_price_usd', 0) or 0),
                            'volume_24h': float(attrs.get('volume_usd', {}).get('h24', 0) or 0),
                            'market_cap': float(attrs.get('market_cap_usd', 0) or 0),
                            'liquidity': float(attrs.get('liquidity_usd', 0) or 0),
                            'network': 'Raydium',
                        }
                        tokens.append(token)
                    except (ValueError, TypeError, KeyError) as e:
                        logger.debug(f"Error parsing Raydium token: {e}")
                        continue
                
                logger.info(f"✅ Got {len(tokens)} tokens from Raydium")
                return tokens
        
        except asyncio.TimeoutError:
            logger.warning("Timeout getting Raydium tokens")
            return []
        except Exception as e:
            logger.error(f"Failed to get Raydium tokens: {e}")
            return []
    
    async def get_top_new_tokens_stonfi(self, limit: int = 20) -> list[dict]:
        """
        Получает топ новых токенов в Ston.fi (TON).
        
        Returns: аналогично get_top_new_tokens_raydium()
        """
        try:
            if not self.session:
                await self.start()
            
            # GeckoTerminal URL для Ston.fi (TON)
            url = f"{self.GECKO_TERMINAL_BASE}/networks/ton/pools?order=h24_volume_usd&limit={limit}"
            
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning(f"GeckoTerminal Ston.fi failed: {resp.status}")
                    return []
                
                data = await resp.json()
                pools = data.get('data', [])
                
                tokens = []
                for pool in pools[:limit]:
                    attrs = pool.get('attributes', {})
                    try:
                        token = {
                            'symbol': attrs.get('name', 'UNKNOWN'),
                            'address': pool.get('id', ''),
                            'price_usd': float(attrs.get('token_price_usd', 0) or 0),
                            'volume_24h': float(attrs.get('volume_usd', {}).get('h24', 0) or 0),
                            'market_cap': float(attrs.get('market_cap_usd', 0) or 0),
                            'liquidity': float(attrs.get('liquidity_usd', 0) or 0),
                            'network': 'Ston.fi',
                        }
                        tokens.append(token)
                    except (ValueError, TypeError, KeyError) as e:
                        logger.debug(f"Error parsing Ston.fi token: {e}")
                        continue
                
                logger.info(f"✅ Got {len(tokens)} tokens from Ston.fi")
                return tokens
        
        except asyncio.TimeoutError:
            logger.warning("Timeout getting Ston.fi tokens")
            return []
        except Exception as e:
            logger.error(f"Failed to get Ston.fi tokens: {e}")
            return []
    
    async def get_combined_top_tokens(self, limit: int = 20) -> list[dict]:
        """
        Получает топ новых токенов из ОБОИХ DEX.
        Сортирует по volume_24h.
        """
        raydium_task = self.get_top_new_tokens_raydium(limit)
        stonfi_task = self.get_top_new_tokens_stonfi(limit)
        
        raydium, stonfi = await asyncio.gather(raydium_task, stonfi_task)
        
        # Комбинируем и сортируем по объему
        combined = raydium + stonfi
        combined.sort(key=lambda x: x['volume_24h'], reverse=True)
        
        return combined[:limit]


# Глобальный инстанс DEX сканера
DEX_SCANNER: Optional[DEXScanner] = None


async def get_dex_scanner() -> DEXScanner:
    """Получить глобальный инстанс DEX сканера."""
    global DEX_SCANNER
    if not DEX_SCANNER:
        DEX_SCANNER = DEXScanner()
        await DEX_SCANNER.start()
    return DEX_SCANNER


async def close_dex_scanner():
    """Закрыть DEX сканер."""
    global DEX_SCANNER
    if DEX_SCANNER:
        await DEX_SCANNER.stop()
        DEX_SCANNER = None
