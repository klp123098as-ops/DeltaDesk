"""
Модуль для расчета чистой прибыли арбитража.
Учитывает все комиссии и гарантирует только реально выгодные связки.
"""

from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class ProfitabilityResult:
    """Результат расчета профитности арбитража."""
    is_profitable: bool  # Проходит ли фильтр (>= min_profit_pct)
    net_profit_usd: float  # Чистая прибыль в USD
    net_profit_pct: float  # Прибыль в % от инвестиции
    gross_profit_usd: float  # Валовая прибыль до комиссий
    investment_amount: float  # Размер инвестиции
    buy_price: float  # Цена покупки (Ask)
    sell_price: float  # Цена продажи (Bid)
    buy_exchange: str
    sell_exchange: str
    buy_fee_usd: float  # Комиссия на покупку
    sell_fee_usd: float  # Комиссия на продажу
    network_fee_usd: float  # Сетевая комиссия
    total_fees_usd: float  # Все комиссии вместе
    
    def format_details(self) -> str:
        """Форматирует детальное объяснение расчета."""
        lines = [
            f"💰 <b>Расчет арбитража</b>",
            f"",
            f"<b>Входные данные:</b>",
            f"• Инвестиция: ${self.investment_amount:.2f}",
            f"• Покупка на {self.buy_exchange.upper()} (Ask): ${self.buy_price:.8f}",
            f"• Продажа на {self.sell_exchange.upper()} (Bid): ${self.sell_price:.8f}",
            f"",
            f"<b>Вычеты:</b>",
            f"• Комиссия покупки: -${self.buy_fee_usd:.4f}",
            f"• Сетевая комиссия: -${self.network_fee_usd:.4f}",
            f"• Комиссия продажи: -${self.sell_fee_usd:.4f}",
            f"• Всего комиссий: -${self.total_fees_usd:.4f}",
            f"",
            f"<b>Результат:</b>",
            f"• Валовая прибыль: ${self.gross_profit_usd:.4f}",
            f"• Чистая прибыль: ${self.net_profit_usd:.4f}",
            f"• Процент: {self.net_profit_pct:.4f}%",
            f"",
            f"{'✅ ПРОХОДИТ' if self.is_profitable else '❌ НЕ ПРОХОДИТ'}",
        ]
        return "\n".join(lines)


def calculate_net_profit(
    buy_price: float,
    sell_price: float,
    buy_exchange: str,
    sell_exchange: str,
    buy_taker_fee_pct: float = 0.1,  # 0.1%
    sell_taker_fee_pct: float = 0.1,  # 0.1%
    network_fee_usd: float = 1.0,  # $1
    investment_amount: float = 1000.0,
    min_profit_pct: float = 2.0,
) -> ProfitabilityResult:
    """
    Расчет чистой прибыли арбитража.
    
    Args:
        buy_price: Цена покупки (Ask на бирже-доноре)
        sell_price: Цена продажи (Bid на бирже-приемнике)
        buy_exchange: Название биржи покупки
        sell_exchange: Название биржи продажи
        buy_taker_fee_pct: Комиссия Taker на покупку (в %, например 0.1)
        sell_taker_fee_pct: Комиссия Taker на продажу (в %, например 0.1)
        network_fee_usd: Сетевая комиссия (в USD)
        investment_amount: Размер инвестиции (в USD)
        min_profit_pct: Минимальный порог прибыли для фильтрации
    
    Returns:
        ProfitabilityResult с полной информацией о расчетах
    """
    
    # ЭТАП 1: Рассчитываем, сколько коинов мы можем купить
    coins_bought = investment_amount / buy_price
    
    # ЭТАП 2: Вычитаем комиссию покупки (Taker Fee)
    buy_fee_pct_decimal = buy_taker_fee_pct / 100  # Переводим проценты в decimal
    buy_fee_usd = investment_amount * buy_fee_pct_decimal
    amount_after_buy_fee = investment_amount - buy_fee_usd
    
    # ЭТАП 3: Вычитаем сетевую комиссию (газ за вывод)
    amount_after_network = amount_after_buy_fee - network_fee_usd
    
    # Если сетевая комиссия съела прибыль — не выгодно
    if amount_after_network <= 0:
        return ProfitabilityResult(
            is_profitable=False,
            net_profit_usd=amount_after_network,
            net_profit_pct=(amount_after_network / investment_amount * 100) if investment_amount > 0 else -100,
            gross_profit_usd=0,
            investment_amount=investment_amount,
            buy_price=buy_price,
            sell_price=sell_price,
            buy_exchange=buy_exchange,
            sell_exchange=sell_exchange,
            buy_fee_usd=buy_fee_usd,
            sell_fee_usd=0,
            network_fee_usd=network_fee_usd,
            total_fees_usd=buy_fee_usd + network_fee_usd,
        )
    
    # ЭТАП 4: Конвертируем обратно в USD по цене продажи
    amount_in_usd = amount_after_network * sell_price
    
    # ЭТАП 5: Вычитаем комиссию продажи (Taker Fee)
    sell_fee_pct_decimal = sell_taker_fee_pct / 100
    sell_fee_usd = amount_in_usd * sell_fee_pct_decimal
    net_revenue = amount_in_usd - sell_fee_usd
    
    # ИТОГОВЫЙ РАСЧЕТ
    gross_profit_usd = sell_price - buy_price  # Разница цен
    net_profit_usd = net_revenue - investment_amount
    net_profit_pct = (net_profit_usd / investment_amount * 100) if investment_amount > 0 else 0
    total_fees_usd = buy_fee_usd + network_fee_usd + sell_fee_usd
    
    # Проверяем фильтр
    is_profitable = net_profit_pct >= min_profit_pct
    
    return ProfitabilityResult(
        is_profitable=is_profitable,
        net_profit_usd=net_profit_usd,
        net_profit_pct=net_profit_pct,
        gross_profit_usd=gross_profit_usd,
        investment_amount=investment_amount,
        buy_price=buy_price,
        sell_price=sell_price,
        buy_exchange=buy_exchange,
        sell_exchange=sell_exchange,
        buy_fee_usd=buy_fee_usd,
        sell_fee_usd=sell_fee_usd,
        network_fee_usd=network_fee_usd,
        total_fees_usd=total_fees_usd,
    )
