"""
Модуль расчета чистой прибыли для арбитража.
Жесткая логика фильтрации с учетом всех комиссий.
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ProfitabilityResult:
    """Результат расчета профитности связки."""
    is_profitable: bool  # Выше ли чистая прибыль минимального порога?
    net_profit_usd: float  # Чистая прибыль в USD (абсолютная)
    net_profit_pct: float  # Чистая прибыль в % от инвестиции
    gross_spread_pct: float  # Спред ДО комиссий (для информации)
    buy_exchange: str
    sell_exchange: str
    investment_amount: float  # Рабочий банк (например, $1000)
    
    # Детализация комиссий (для логирования)
    buy_fee_usd: float
    sell_fee_usd: float
    network_fee_usd: float
    total_fees_usd: float


def calculate_net_profit(
    buy_price: float,
    sell_price: float,
    buy_exchange: str,
    sell_exchange: str,
    buy_taker_fee_pct: float = 0.1,
    sell_taker_fee_pct: float = 0.1,
    network_fee_usd: float = 1.0,
    investment_amount: float = 1000.0,
    min_profit_pct: float = 2.0,
) -> ProfitabilityResult:
    """
    Рассчитывает чистую прибыль с учетом всех комиссий.
    
    Args:
        buy_price: Цена покупки на бирже A (Ask)
        sell_price: Цена продажи на бирже B (Bid)
        buy_exchange: Имя биржи покупки
        sell_exchange: Имя биржи продажи
        buy_taker_fee_pct: Комиссия Taker покупки (% от суммы)
        sell_taker_fee_pct: Комиссия Taker продажи (% от суммы)
        network_fee_usd: Фиксированная комиссия сети (USD)
        investment_amount: Рабочий банк (USD)
        min_profit_pct: Минимальный порог чистой прибыли (%)
    
    Returns:
        ProfitabilityResult с полной информацией о расчетах
    """
    
    if buy_price <= 0 or sell_price <= 0:
        return ProfitabilityResult(
            is_profitable=False,
            net_profit_usd=0,
            net_profit_pct=0,
            gross_spread_pct=0,
            buy_exchange=buy_exchange,
            sell_exchange=sell_exchange,
            investment_amount=investment_amount,
            buy_fee_usd=0,
            sell_fee_usd=0,
            network_fee_usd=network_fee_usd,
            total_fees_usd=0,
        )
    
    # === ШАГ 1: Покупка на бирже A ===
    # Кол-во монет, которое можем купить на investment_amount
    quantity = investment_amount / buy_price
    
    # Комиссия за покупку (вычитается из нашего банка)
    buy_fee_usd = investment_amount * (buy_taker_fee_pct / 100)
    actual_investment = investment_amount + buy_fee_usd  # Нам нужно больше денег
    quantity = investment_amount / buy_price  # Но монет покупаем с investment_amount
    
    # === ШАГ 2: Вывод монет (сеть) ===
    # Фиксированная комиссия сети в USD (переводим в кол-во монет)
    network_fee_quantity = network_fee_usd / buy_price
    quantity -= network_fee_quantity
    
    # === ШАГ 3: Продажа на бирже B ===
    # Получаем деньги за оставшиеся монеты
    gross_revenue = quantity * sell_price
    
    # Комиссия за продажу (вычитается из выручки)
    sell_fee_usd = gross_revenue * (sell_taker_fee_pct / 100)
    net_revenue = gross_revenue - sell_fee_usd
    
    # === ФИНАЛЬНЫЙ РАСЧЕТ ===
    net_profit_usd = net_revenue - investment_amount
    net_profit_pct = (net_profit_usd / investment_amount) * 100 if investment_amount > 0 else 0
    
    # Валовый спред (до комиссий) для информации
    gross_spread_pct = ((sell_price - buy_price) / buy_price) * 100
    
    # Общие комиссии
    total_fees_usd = buy_fee_usd + sell_fee_usd + network_fee_usd
    
    # Проверка минимального порога
    is_profitable = net_profit_pct >= min_profit_pct
    
    return ProfitabilityResult(
        is_profitable=is_profitable,
        net_profit_usd=net_profit_usd,
        net_profit_pct=net_profit_pct,
        gross_spread_pct=gross_spread_pct,
        buy_exchange=buy_exchange,
        sell_exchange=sell_exchange,
        investment_amount=investment_amount,
        buy_fee_usd=buy_fee_usd,
        sell_fee_usd=sell_fee_usd,
        network_fee_usd=network_fee_usd,
        total_fees_usd=total_fees_usd,
    )


def log_profitability_details(result: ProfitabilityResult, symbol: str) -> str:
    """Форматирует результат для логирования."""
    lines = [
        f"\n{'='*60}",
        f"📊 АНАЛИЗ ПРОФИТНОСТИ: {symbol}",
        f"{'='*60}",
        f"Рабочий банк: ${result.investment_amount:.2f}",
        f"",
        f"Валовый спред: {result.gross_spread_pct:.4f}%",
        f"",
        f"📍 Биржи: {result.buy_exchange.upper()} → {result.sell_exchange.upper()}",
        f"",
        f"💰 Комиссии (USD):",
        f"  • Покупка (Taker):  ${result.buy_fee_usd:.4f}",
        f"  • Сеть (вывод):     ${result.network_fee_usd:.4f}",
        f"  • Продажа (Taker):  ${result.sell_fee_usd:.4f}",
        f"  • ИТОГО комиссий:   ${result.total_fees_usd:.4f}",
        f"",
        f"💵 Чистая прибыль:",
        f"  • USD:              ${result.net_profit_usd:.4f}",
        f"  • %:                {result.net_profit_pct:.4f}%",
        f"",
        f"✅ СТАТУС: {'ПРОФИТНО' if result.is_profitable else '❌ НЕ ПРОФИТНО'}",
        f"{'='*60}",
    ]
    return "\n".join(lines)
