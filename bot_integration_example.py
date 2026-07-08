"""ПРИМЕР ИНТЕГРАЦИИ DEX В BOT.PY

Это файл с примерами кода для добавления в bot.py
Добавьте эти импорты и функции в существующий bot.py
"""

# ============================================================================
# ДОБАВИТЬ В ИМПОРТЫ bot.py
# ============================================================================

# from dex_scanner import (
#     scan_dex_for_signals,
#     format_dex_tokens,
#     format_dex_arbitrage,
#     scan_dex_tokens
# )

# ============================================================================
# НОВАЯ ФОНОВАЯ ЗАДАЧА: DEX СКАНЕР
# ============================================================================

"""
async def dex_scanner_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Фоновое сканирование DEX для поиска арбитража и новых токенов."""
    logger.info("=== DEX SCANNER JOB STARTED ===")
    try:
        whitelist = get_whitelist()
        if not whitelist:
            logger.info("No users in whitelist, skipping DEX scan")
            return
        
        # Сканируем Raydium (Solana)
        logger.info("Scanning Raydium (Solana) for arbitrage...")
        tokens_sol, opportunities_sol = await scan_dex_for_signals(
            dex_network="solana",
            cex_exchanges=["mexc", "okx"],
            min_price_diff_pct=2.0
        )
        
        # Сканируем Ston.fi (TON) - опционально
        logger.info("Scanning Ston.fi (TON) for arbitrage...")
        tokens_ton, opportunities_ton = await scan_dex_for_signals(
            dex_network="ton",
            cex_exchanges=["mexc"],
            min_price_diff_pct=2.0
        )
        
        # Отправляем результаты пользователям
        if opportunities_sol or opportunities_ton:
            for uid in whitelist:
                try:
                    messages = []
                    
                    if opportunities_sol:
                        msg = format_dex_arbitrage(opportunities_sol, limit=5)
                        messages.append("🔄 <b>Raydium ↔ CEX Арбитраж:</b>\n" + msg)
                    
                    if opportunities_ton:
                        msg = format_dex_arbitrage(opportunities_ton, limit=5)
                        messages.append("🔄 <b>Ston.fi ↔ CEX Арбитраж:</b>\n" + msg)
                    
                    if messages:
                        final_text = "\n\n".join(messages)
                        await context.bot.send_message(
                            chat_id=uid,
                            text=final_text,
                            parse_mode="HTML"
                        )
                        logger.info(f"✅ DEX signals sent to {uid}")
                
                except Exception as e:
                    logger.warning(f"Failed to send DEX signal to {uid}: {e}")
        
        logger.info("=== DEX SCANNER JOB FINISHED ===")
    
    except Exception as e:
        logger.exception(f"❌ Error in DEX scanner job: {e}")

"""

# ============================================================================
# РЕГИСТРАЦИЯ ЗАДАЧИ В build_app()
# ============================================================================

"""
def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.post_shutdown = on_shutdown
    
    if app.job_queue:
        # Существующие задачи
        app.job_queue.run_repeating(background_scanner_job, interval=180, first=10)
        
        # ДОБАВИТЬ: DEX сканирование каждые 30 минут
        app.job_queue.run_repeating(dex_scanner_job, interval=1800, first=60)
        
        # Ежедневная рассылка топ монет
        from datetime import time
        app.job_queue.run_daily(daily_movers_job, time=time(hour=18, minute=50))
    
    # ... остальной код ...
"""

# ============================================================================
# КОМАНДА ДЛЯ ПОЛЬЗОВАТЕЛЯ: /dex
# ============================================================================

"""
async def dex_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /dex - вручную сканировать DEX."""
    uid = update.effective_user.id
    
    if not is_user_allowed(uid):
        await update.message.reply_text("⛔️ Доступ ограничен.")
        return
    
    wait_msg = await update.message.reply_text("⏳ Сканирую DEX (Solana + TON)...")
    
    try:
        # Raydium
        tokens_sol, opp_sol = await scan_dex_for_signals(
            dex_network="solana",
            cex_exchanges=["mexc", "okx"]
        )
        
        # Ston.fi
        tokens_ton, opp_ton = await scan_dex_for_signals(
            dex_network="ton",
            cex_exchanges=["mexc"]
        )
        
        messages = []
        
        if tokens_sol:
            msg = format_dex_tokens(tokens_sol, limit=5)
            messages.append("🚀 <b>Новые токены Raydium (Solana):</b>\n" + msg)
        
        if opp_sol:
            msg = format_dex_arbitrage(opp_sol, limit=5)
            messages.append("🔄 <b>Raydium ↔ CEX Арбитраж:</b>\n" + msg)
        
        if tokens_ton:
            msg = format_dex_tokens(tokens_ton, limit=5)
            messages.append("🚀 <b>Новые токены Ston.fi (TON):</b>\n" + msg)
        
        if opp_ton:
            msg = format_dex_arbitrage(opp_ton, limit=5)
            messages.append("🔄 <b>Ston.fi ↔ CEX Арбитраж:</b>\n" + msg)
        
        if not messages:
            await wait_msg.edit_text("📊 Данных не найдено")
            return
        
        final_text = "\n\n".join(messages)
        await wait_msg.edit_text(final_text, parse_mode="HTML")
    
    except Exception as e:
        logger.exception(f"Error in dex_cmd: {e}")
        await wait_msg.edit_text(f"❌ Ошибка: {str(e)}")
"""

# ============================================================================
# РЕГИСТРАЦИЯ КОМАНДЫ В build_app()
# ============================================================================

"""
    app.add_handler(CommandHandler("dex", dex_cmd))
"""

# ============================================================================
# РЕЗУЛЬТАТЫ
# ============================================================================

print("""
🎉 ИНТЕГРАЦИЯ DEX ЗАВЕРШЕНА!

ЧтО ПОЛУЧИЛОСЬ:

1. ✅ calc_arbitrage_new() - жесткий фильтр 2% чистой прибыли
   - Учитывает комиссии покупки, продажи, сети
   - Использует Bid/Ask из orderbook
   - Проверяет статус кошельков

2. ✅ Orderbook вместо Last Price
   - fetch_order_book() вместо fetch_ticker()
   - Реальные цены торговли

3. ✅ Проверка статуса кошельков
   - can_withdraw на бирже покупки
   - can_deposit на бирже продажи
   - Пропускает техническое обслуживание

4. ✅ Интеграция DEX
   - GeckoTerminal API для Solana (Raydium)
   - GeckoTerminal API для TON (Ston.fi)
   - Поиск новых токенов ($10k+ ликвидность)
   - DEX ↔ CEX арбитраж

СЛЕДУЮЩИЕ ШАГИ:

1. Скопируйте импорты из bot_integration_example.py в bot.py
2. Добавьте функцию dex_scanner_job()
3. Зарегистрируйте её в build_app()
4. Добавьте команду /dex
5. Протестируйте локально
6. Выполните: git add . && git commit -m "🚀 Полный рефакторинг с DEX" && git push

ФАЙЛЫ В РЕПОЗИТОРИИ:
  ✅ profitability.py (6.3 KB) - расчет чистой прибыли
  ✅ market.py (27.3 KB) - orderbook + проверка кошельков
  ✅ dex_scanner.py (12.1 KB) - GeckoTerminal интеграция
  ✅ REFACTORING_GUIDE.py (15.4 KB) - полный гайд
  📝 bot_integration_example.py (эта версия) - примеры кода

""")
