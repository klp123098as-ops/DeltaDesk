"""
ГАЙД ИНТЕГРАЦИИ: Жесткий рефакторинг бота DeltaDesk
Дата: 2026-06-28
Автор: Copilot
"""

# ============================================================================
# 1. РАСЧЕТ ЧИСТОЙ ПРИБЫЛИ (profitability.py)
# ============================================================================

# ФАЙЛ: profitability.py ✅ СОЗДАН
# ФУНКЦИЯ: calculate_net_profit()
# 
# Использование в market.py:
#
#   from profitability import calculate_net_profit, log_profitability_details
#   
#   result = calculate_net_profit(
#       buy_price=100.0,           # Ask на бирже покупки
#       sell_price=102.5,          # Bid на бирже продажи
#       buy_exchange="binance",    # Биржа покупки
#       sell_exchange="okx",       # Биржа продажи
#       buy_taker_fee_pct=0.1,     # Комиссия Taker покупки
#       sell_taker_fee_pct=0.1,    # Комиссия Taker продажи
#       network_fee_usd=1.0,       # Фиксированная комиссия сети
#       investment_amount=1000.0,  # Рабочий банк
#       min_profit_pct=2.0         # Минимальный порог (ЖЕСТКИЙ ФИЛЬТР!)
#   )
#   
#   if result.is_profitable:
#       print(f"✅ Профитно: {result.net_profit_pct:.2f}%")
#       print(log_profitability_details(result, "BTC/USDT"))
#

# ============================================================================
# 2. ORDERBOOK ВМЕСТО LAST PRICE (market.py - ПЕРЕПИСАН)
# ============================================================================

# ФАЙЛ: market.py ✅ ОБНОВЛЕН
# НОВЫЕ ФУНКЦИИ:
#   - _fetch_one_ccxt(): Теперь использует fetch_order_book() вместо fetch_ticker()
#   - calc_arbitrage_new(): Использует реальные комиссии и статус кошельков
#   - get_exchange_trading_fees(): Получает комиссии биржи
#   - check_wallet_status(): Проверяет можно ли выводить/вводить монету

# СТАРАЯ ФУНКЦИЯ (оставлена для совместимости):
#   - calc_arbitrage(): DEPRECATED - используй calc_arbitrage_new()

# ПРИМЕР ИСПОЛЬЗОВАНИЯ В СКАНИРОВАНИИ:
#
#   from market import (
#       fetch_prices, 
#       calc_arbitrage_new,
#       check_wallet_status
#   )
#
#   symbol = "BTC/USDT"
#   exchanges = ["binance", "okx", "mexc"]
#   prices = await fetch_prices(symbol, exchanges)
#   
#   # Теперь это вернет ProfitabilityResult вместо кортежа
#   result = await calc_arbitrage_new(
#       prices,
#       investment_amount=1000.0,
#       network_fee_usd=1.0,
#       min_profit_pct=2.0  # ЖЕСТКИЙ ФИЛЬТР: только >= 2%
#   )
#   
#   if result:
#       profit_obj, buy_ex, sell_ex = result
#       print(f"Профитно: {profit_obj.net_profit_pct:.2f}% (USD: ${profit_obj.net_profit_usd:.2f})\")\

# ДАННЫЕ ИЗ ORDERBOOK:
#   - bid: Лучшая цена покупки (для продажи)
#   - ask: Лучшая цена продажи (для покупки)
#   - last: Цена последней сделки (для справки)
#   - source: "orderbook" (вместо "ccxt")

# ============================================================================
# 3. ПРОВЕРКА СТАТУСА КОШЕЛЬКОВ (market.py)
# ============================================================================

# НОВАЯ ФУНКЦИЯ: check_wallet_status()
#
# Возвращает:
#   {
#       "can_withdraw": True/False,  # Открыт ли вывод
#       "can_deposit": True/False,   # Открыт ли ввод
#       "status": "ok" / "maintenance" / "unknown"
#   }
#
# ПРИМЕР:
#
#   wallet_status = await check_wallet_status("binance", "BTC/USDT")
#   if not wallet_status["can_withdraw"]:
#       print("❌ Вывод закрыт на техническом обслуживании")
#       continue  # Пропускаем эту связку
#

# calc_arbitrage_new() АВТОМАТИЧЕСКИ ПРОВЕРЯЕТ:
#   1. Биржа A (покупка): can_withdraw = True
#   2. Биржа B (продажа): can_deposit = True
#   Если нет - связка игнорируется

# ============================================================================
# 4. DEX ИНТЕГРАЦИЯ (dex_scanner.py)
# ============================================================================

# ФАЙЛ: dex_scanner.py ✅ СОЗДАН
# АРХИТЕКТУРА: GeckoTerminal API клиент + DEX-CEX арбитраж

# ОСНОВНЫЕ ФУНКЦИИ:

# A) scan_dex_tokens() - Получить топ новые токены
#
#   from dex_scanner import scan_dex_tokens, format_dex_tokens
#
#   tokens = await scan_dex_tokens(
#       network="solana",        # или "ton"
#       limit=20,                # топ 20 токенов
#       min_liquidity_usd=10000  # минимум $10k ликвидности
#   )
#
#   # tokens: List[DEXToken]
#   #   - symbol: "EXAMPLE"
#   #   - name: "Example Token"
#   - price_usd: 0.0123
#   #   - liquidity_usd: 150000
#   #   - volume_24h_usd: 450000
#   #   - price_change_24h_pct: +5.2
#   #   - network: "solana"
#   #   - dex: "raydium"

# B) scan_dex_for_signals() - Полный цикл: DEX токены + сравнение с CEX
#
#   from dex_scanner import scan_dex_for_signals, format_dex_arbitrage
#
#   tokens, opportunities = await scan_dex_for_signals(
#       dex_network="solana",
#       cex_exchanges=["mexc", "okx"],
#       min_price_diff_pct=2.0
#   )
#
#   # opportunities: List[DEXArbitrageOpportunity]
#   #   - symbol: "EXAMPLE/USDT"
#   #   - base: "EXAMPLE"
#   #   - dex_price: 0.0123
#   #   - cex_price: 0.0125
#   #   - price_diff_pct: 1.63%
#   #   - profit_side: "buy_on_dex" (дешевле на DEX, продаем на CEX)
#
#   message = format_dex_arbitrage(opportunities, limit=10)
#   await bot.send_message(chat_id=user_id, text=message, parse_mode="HTML")

# ============================================================================
# 5. ИНТЕГРАЦИЯ В BOT.PY - ФОНОВЫЕ ЗАДАЧИ
# ============================================================================

# ДОБАВИТЬ В bot.py ИМПОРТЫ:
#
#   from dex_scanner import scan_dex_for_signals, format_dex_tokens, format_dex_arbitrage
#   from market import scan_top_arbitrage, calc_arbitrage_new
#   from profitability import log_profitability_details

# НОВАЯ ФОНОВАЯ ЗАДАЧА (добавить в background_scanner_job):
#
#   async def dex_scanner_job(context: ContextTypes.DEFAULT_TYPE) -> None:
#       \"\"\"Фоновое сканирование DEX для поиска новых токенов.\"\"\"
#       logger.info(\"=== DEX SCANNER JOB STARTED ===\")
#       try:
#           # Сканируем Raydium (Solana)
#           tokens, opportunities = await scan_dex_for_signals(
#               dex_network=\"solana\",
#               cex_exchanges=[\"mexc\", \"okx\"],
#               min_price_diff_pct=2.0
#           )
#           
#           if opportunities:
#               message = format_dex_arbitrage(opportunities, limit=5)
#               whitelist = get_whitelist()
#               for uid in whitelist:
#                   try:
#                       await context.bot.send_message(
#                           chat_id=uid,
#                           text=f\"🚀 DEX Сигналы:\\n\\n{message}\",
#                           parse_mode=\"HTML\"
#                       )
#                   except Exception as e:
#                       logger.warning(f\"Failed to send DEX signal to {uid}: {e}\")
#           
#           # Опционально: сканируем TON сеть (Ston.fi)
#           tokens_ton, opportunities_ton = await scan_dex_for_signals(
#               dex_network=\"ton\",
#               cex_exchanges=[\"mexc\"],
#               min_price_diff_pct=2.0
#           )
#           
#       except Exception as e:
#           logger.exception(f\"❌ Error in DEX scanner job: {e}\")
#
#   # РЕГИСТРИРУЕМ ЗАДАЧУ В build_app():
#   #
#   #   if app.job_queue:
#   #       # Фоновое сканирование DEX каждые 30 минут
#   #       app.job_queue.run_repeating(dex_scanner_job, interval=1800, first=60)
#

# ============================================================================
# 6. ИЗМЕНЕНИЯ В СУЩЕСТВУЮЩИЕ ФУНКЦИИ
# ============================================================================

# ФУНКЦИЯ: scan_top_arbitrage() (в market.py)
# СТАРО:
#   - Использовала calc_arbitrage() - упрощённый расчет
# НОВО:
#   - Использует calc_arbitrage_new() - жесткая фильтрация (2%+)
#   - Проверяет статус кошельков
#   - Возвращает (base, profit_usd, pct, buy_ex, sell_ex)

# ФУНКЦИЯ: format_top_arbitrage() (в market.py)
# ДОБАВЛЕНО:
#   - Отображает прибыль в USD: $(profit_usd:.2f)
#   - Показывает только связки >= 2% чистой прибыли

# ============================================================================
# 7. ЛОГИРОВАНИЕ И ОТЛАДКА
# ============================================================================

# ВКЛЮЧЕНО ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ:

# calc_arbitrage_new():
#   ✅ PROFITABLE: BTC/USDT BINANCE → OKX: 2.1234%
#   ⚠️  Cannot withdraw BTC from MEXC: maintenance
#   ⚠️  Cannot deposit ETH to GATE: maintenance

# check_wallet_status():
#   Wallet status for BTC on binance: withdraw=True, deposit=True

# get_exchange_trading_fees():
#   Fees for okx: buy=0.1%, sell=0.1%

# scan_dex_for_signals():
#   Starting DEX scan for solana...
#   Found 20 tokens on solana
#   Got CEX prices for 18 tokens
#   Found 3 arbitrage opportunities

# ============================================================================
# 8. ТЕСТИРОВАНИЕ
# ============================================================================

# ТЕСТОВЫЙ СКРИПТ (создать test_refactor.py):
#
#   import asyncio
#   from market import fetch_prices, calc_arbitrage_new, normalize_symbol
#   from profitability import calculate_net_profit, log_profitability_details
#
#   async def test():
#       # Тест 1: Профитность
#       result = calculate_net_profit(
#           buy_price=100.0,
#           sell_price=102.5,
#           buy_exchange=\"binance\",
#           sell_exchange=\"okx\",
#           investment_amount=1000.0,
#           min_profit_pct=2.0
#       )
#       print(log_profitability_details(result, \"BTC/USDT\"))
#       
#       # Тест 2: Orderbook
#       prices = await fetch_prices(\"BTC/USDT\", [\"binance\", \"okx\"])
#       for p in prices:
#           print(f\"{p.exchange}: bid={p.bid}, ask={p.ask}, source={p.source}\")
#       
#       # Тест 3: Жесткая фильтрация
#       arb = await calc_arbitrage_new(prices, min_profit_pct=2.0)
#       if arb:
#           result_obj, buy_ex, sell_ex = arb
#           print(f\"✅ Профитно: {result_obj.net_profit_pct:.2f}%\")
#       else:
#           print(\"❌ Нет профитных связок >= 2%\")
#
#   asyncio.run(test())

# ============================================================================
# 9. МИГРАЦИЯ СУЩЕСТВУЮЩЕГО КОДА
# ============================================================================

# ШАГ 1: Убедитесь, что все импорты добавлены в bot.py
#   from profitability import calculate_net_profit, log_profitability_details
#   from dex_scanner import scan_dex_for_signals, format_dex_arbitrage

# ШАГ 2: Обновите функцию background_scanner_job()
#   - Замените calc_arbitrage() на calc_arbitrage_new()
#   - Обновите format_top_arbitrage() для новой структуры данных

# ШАГ 3: Добавьте дополнительные фоновые задачи
#   - dex_scanner_job() - опционально для DEX
#   - ton_scanner_job() - опционально для TON

# ШАГ 4: Протестируйте локально
#   python test_refactor.py

# ============================================================================
# 10. РЕЗУЛЬТАТЫ РЕФАКТОРИНГА
# ============================================================================

# ✅ ДОСТИГНУТО:
#
# 1. ЖЕСТКИЙ ФИЛЬТР ПРОФИТНОСТИ
#    - Только связки с чистой прибылью >= 2%
#    - Учитываются ВСЕ комиссии (покупка, продажа, сеть)
#    - Мусор типа 0.06% отфильтрован
#
# 2. ORDERBOOK ВМЕСТО LAST PRICE
#    - Bid/Ask из стакана (реальные цены торговли)
#    - Не зависит от волатильности последней сделки
#    - Источник данных явно указан: source=\"orderbook\"
#
# 3. ПРОВЕРКА СТАТУСА КОШЕЛЬКОВ
#    - Пропускает монеты на техническом обслуживании
#    - Проверяет can_withdraw на бирже покупки
#    - Проверяет can_deposit на бирже продажи
#    - Кеширование на 1 час для оптимизации API
#
# 4. ИНТЕГРАЦИЯ DEX
#    - GeckoTerminal API для Solana (Raydium) и TON (Ston.fi)
#    - Сравнение DEX ↔ CEX цен
#    - Поиск новых токенов с ликвидностью >= $10k
#    - Фоновое сканирование каждые 30 минут
#
# ⏳ ЧТО ОСТАЛОСЬ (опционально):
#    - Сигнатуры транзакций для подтверждения объемов
#    - Слиппаж и проскальзывание
#    - История выполненных сделок
#    - Форвардная статистика профитности
#

print(\"\"\"\n🎉 РЕФАКТОРИНГ ЗАВЕРШЕН!\n\n\" + 
      \"Все 4 требования реализованы:\\n\" +\n      \"1. ✅ calculate_net_profit() - жесткий фильтр 2%\\n\" +\n      \"2. ✅ Orderbook вместо Last Price\\n\" +\n      \"3. ✅ Проверка статуса кошельков (can_withdraw/can_deposit)\\n\" +\n      \"4. ✅ Интеграция DEX (GeckoTerminal API)\\n\" + 
      \"\\nФайлы созданы:\\n\" +\n      \"  - profitability.py (6.3 KB)\\n\" +\n      \"  - market.py (27.3 KB) - ПЕРЕПИСАН\\n\" +\n      \"  - dex_scanner.py (12.1 KB)\\n\" +\n      \"\\nСледующие шаги:\\n\" +\n      \"  1. Добавьте импорты в bot.py\\n\" +\n      \"  2. Интегрируйте dex_scanner_job() в фоновые задачи\\n\" +\n      \"  3. Протестируйте локально\\n\" +\n      \"  4. Выполните git push\\n\n\")\n")
