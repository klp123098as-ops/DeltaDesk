"""
Жесткий расчет чистой прибыли арбитража с учетом:
1. Комиссий бирж на покупку и продажу (Taker Fee)
2. Фиксированной комиссии сети (gas fee за вывод коина)
3. Абсолютного значения в USD
4. Минимального порога 2% от инвестиции
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ArbitrageCalculator:
    """
    Калькулятор чистой прибыли арбитража.
    
    Формула:
    1. Получаем $1000 рабочего капитала
    2. Покупаем на бирже A: цена_ask * (1 + taker_fee_buy)
    3. Выводим на бирже A: вычитаем network_fee_usd
    4. Получаем на бирже B: вычитаем входящую комиссию (если есть)
    5. Продаем на бирже B: цена_bid * (1 - taker_fee_sell)
    
    Чистая прибыль = финальное_значение - инвестиция
    """
    
    def __init__(
        self,
        working_balance_usd: float = 1000.0,
        min_profit_threshold_pct: float = 2.0,
    ):
        """
        Args:
            working_balance_usd: Размер рабочего капитала для расчета (по умолчанию $1000)
            min_profit_threshold_pct: Минимальный порог чистой прибыли в % (по умолчанию 2%)
        """
        self.working_balance_usd = working_balance_usd
        self.min_profit_threshold_pct = min_profit_threshold_pct
    
    def calculate_net_profit(
        self,
        buy_price: float,
        sell_price: float,
        buy_exchange_taker_fee: float = 0.001,  # 0.1% — типичная Taker Fee
        sell_exchange_taker_fee: float = 0.001,  # 0.1%
        network_fee_usd: float = 0.5,  # Фиксированная комиссия сети (USD)
        deposit_fee_pct: float = 0.0,  # Входящая комиссия на бирже-получателе (обычно 0)
    ) -> dict:
        """
        Расчет чистой прибыли арбитража.
        
        Args:
            buy_price: Цена Ask на бирже-доноре (где покупаем)
            sell_price: Цена Bid на бирже-получателе (где продаем)
            buy_exchange_taker_fee: Комиссия Taker на покупку (доля от 0 до 1, е.г. 0.001 = 0.1%)
            sell_exchange_taker_fee: Комиссия Taker на продажу (доля)
            network_fee_usd: Фиксированная комиссия сети за вывод (в USD)
            deposit_fee_pct: Комиссия входящего платежа на второй бирже (доля)
        
        Returns:
            {
                'is_profitable': bool,  # Выгодна ли связка (net_profit_pct >= 2%)
                'working_balance': float,  # Рабочий капитал
                'stage_1_cost': float,  # Стоимость покупки с комиссией
                'stage_2_after_buy_fee': float,  # После вычета комиссии на покупку
                'stage_3_after_network_fee': float,  # После вычета сетевой комиссии
                'stage_4_received': float,  # После вычета входящей комиссии
                'sell_revenue': float,  # Выручка от продажи
                'stage_5_after_sell_fee': float,  # После вычета комиссии на продажу
                'net_profit_usd': float,  # Абсолютная чистая прибыль в USD
                'net_profit_pct': float,  # Процент прибыли от инвестиции
                'profit_threshold_pct': float,  # Требуемый минимум
                'passes_filter': bool,  # Проходит ли жесткий фильтр (>= min_profit_pct)
                'details': str,  # Человеко-читаемое объяснение расчета
            }
        """
        
        # ЭТАП 1: Инвестируем рабочий капитал
        investment = self.working_balance_usd
        
        # ЭТАП 2: Покупаем на бирже A (платим Ask цену + Taker Fee)
        amount_coins = investment / buy_price
        buy_fee_usd = investment * buy_exchange_taker_fee
        amount_after_buy_fee = investment - buy_fee_usd
        
        # ЭТАП 3: Выводим с биржи A (вычитаем сетевую комиссию)
        amount_after_network = amount_after_buy_fee - network_fee_usd
        
        if amount_after_network <= 0:
            # Сетевая комиссия полностью съела прибыль
            return {
                'is_profitable': False,
                'working_balance': investment,
                'stage_1_cost': investment,
                'stage_2_after_buy_fee': amount_after_buy_fee,
                'stage_3_after_network_fee': amount_after_network,
                'stage_4_received': 0,
                'sell_revenue': 0,
                'stage_5_after_sell_fee': 0,
                'net_profit_usd': amount_after_network,
                'net_profit_pct': (amount_after_network / investment * 100) if investment > 0 else -100,
                'profit_threshold_pct': self.min_profit_threshold_pct,
                'passes_filter': False,
                'details': f"❌ Сетевая комиссия (${network_fee_usd:.4f}) превышает возможную прибыль",
            }
        
        # ЭТАП 4: Получаем на бирже B (вычитаем входящую комиссию, если есть)
        amount_received = amount_after_network * (1 - deposit_fee_pct)
        
        # Переводим обратно в доллары по цене Bid бирже B
        amount_in_dollars = amount_received * sell_price
        
        # ЭТАП 5: Продаем на бирже B (платим Taker Fee на продажу)
        sell_fee_usd = amount_in_dollars * sell_exchange_taker_fee
        net_revenue = amount_in_dollars - sell_fee_usd
        
        # ИТОГОВЫЙ РАСЧЕТ
        net_profit_usd = net_revenue - investment
        net_profit_pct = (net_profit_usd / investment * 100) if investment > 0 else 0
        
        # Проверяем жесткий фильтр (должно быть >= 2%)
        passes_filter = net_profit_pct >= self.min_profit_threshold_pct
        
        # Детальное объяснение
        details = self._format_details(
            investment, buy_price, sell_price,
            buy_fee_usd, network_fee_usd, deposit_fee_pct,
            sell_fee_usd, net_profit_usd, net_profit_pct, passes_filter
        )
        
        return {
            'is_profitable': net_profit_pct > 0,
            'working_balance': investment,
            'stage_1_cost': investment,
            'stage_2_after_buy_fee': amount_after_buy_fee,
            'stage_3_after_network_fee': amount_after_network,
            'stage_4_received': amount_received,
            'sell_revenue': amount_in_dollars,
            'stage_5_after_sell_fee': net_revenue,
            'net_profit_usd': net_profit_usd,
            'net_profit_pct': net_profit_pct,
            'profit_threshold_pct': self.min_profit_threshold_pct,
            'passes_filter': passes_filter,
            'details': details,
        }
    
    def _format_details(
        self,
        investment: float,
        buy_price: float,
        sell_price: float,
        buy_fee_usd: float,
        network_fee_usd: float,
        deposit_fee_pct: float,
        sell_fee_usd: float,
        net_profit_usd: float,
        net_profit_pct: float,
        passes_filter: bool,
    ) -> str:
        """Форматирует детальное объяснение расчета."""
        lines = [
            f"💰 <b>Расчет чистой прибыли</b>",
            f"",
            f"<b>Входные данные:</b>",
            f"• Рабочий капитал: ${investment:.2f}",
            f"• Цена покупки (Ask): ${buy_price:.6f}",
            f"• Цена продажи (Bid): ${sell_price:.6f}",
            f"",
            f"<b>Вычеты:</b>",
            f"• Комиссия покупки (Taker): -${buy_fee_usd:.4f}",
            f"• Комиссия сети: -${network_fee_usd:.4f}",
            if deposit_fee_pct > 0 else None,
            f"• Входящая комиссия (Deposit): -{deposit_fee_pct*100:.2f}%" if deposit_fee_pct > 0 else None,
            f"• Комиссия продажи (Taker): -${sell_fee_usd:.4f}",
            f"",
            f"<b>Результат:</b>",
            f"• Чистая прибыль: ${net_profit_usd:.4f}",
            f"• Процент от капитала: {net_profit_pct:.2f}%",
            f"• Требуемый минимум: {self.min_profit_threshold_pct:.2f}%",
            f"",
            f"{'✅ ПРОХОДИТ ФИЛЬТР' if passes_filter else '❌ НЕ ПРОХОДИТ ФИЛЬТР'}",
        ]
        
        # Удаляем None значения
        lines = [l for l in lines if l is not None]
        
        return "\n".join(lines)


# Утилита для работы с разными парами и биржами
def validate_arbitrage_pair(
    buy_ask: float,
    sell_bid: float,
    buy_exchange_taker_fee: float = 0.001,
    sell_exchange_taker_fee: float = 0.001,
    network_fee_usd: float = 0.5,
    working_balance: float = 1000.0,
    min_profit_threshold_pct: float = 2.0,
) -> bool:
    """
    Быстрая проверка: проходит ли пара арбитража жесткий фильтр?
    
    Returns:
        True если чистая прибыль >= min_profit_threshold_pct, иначе False
    """
    calc = ArbitrageCalculator(
        working_balance_usd=working_balance,
        min_profit_threshold_pct=min_profit_threshold_pct,
    )
    
    result = calc.calculate_net_profit(
        buy_price=buy_ask,
        sell_price=sell_bid,
        buy_exchange_taker_fee=buy_exchange_taker_fee,
        sell_exchange_taker_fee=sell_exchange_taker_fee,
        network_fee_usd=network_fee_usd,
    )
    
    return result['passes_filter']


if __name__ == "__main__":
    # Пример использования
    calc = ArbitrageCalculator(working_balance_usd=1000.0, min_profit_threshold_pct=2.0)
    
    # Сценарий: Покупаем BTC на Binance (Ask=$67000), продаем на OKX (Bid=$67100)
    result = calc.calculate_net_profit(
        buy_price=67000.0,
        sell_price=67100.0,
        buy_exchange_taker_fee=0.001,  # 0.1%
        sell_exchange_taker_fee=0.001,  # 0.1%
        network_fee_usd=1.0,  # $1 за вывод BTC
    )
    
    print(result['details'])
    print(f"\nПроходит фильтр: {result['passes_filter']}")
