# Запуск @DeltaDesk1_bot бесплатно 24/7

Бот: https://t.me/DeltaDesk1_bot

Чтобы бот работал **всегда**, его нужно запустить в облаке. На своём ПК он работает только пока включён `start.bat`.

Рекомендуемый вариант: **Fly.io** (бесплатный лимит, бот крутится постоянно в режиме polling).

---

## ⚠️ Сначала — безопасность токена

Вы отправили токен в чат. Любой, кто его увидит, может управлять ботом.

1. Откройте [@BotFather](https://t.me/BotFather)
2. Выберите **DeltaDesk1** → **/revoke** (или «Revoke current token»)
3. Скопируйте **новый** токен
4. Вставьте в файл `.env` (локально) или в секреты Fly (облако)

**Никому не показывайте токен и не публикуйте в чатах.**

---

## Вариант A — Fly.io (24/7, бесплатный тариф)

Нужны: аккаунт на https://fly.io и 15–20 минут один раз.

### 1. Установите Fly CLI

Windows (PowerShell от администратора):

```powershell
powershell -Command "iwr https://fly.io/install.ps1 -useb | iex"
```

Перезапустите терминал.

### 2. Войдите и создайте приложение

```powershell
cd "c:\Users\Acer\.cursor\projects\Mordor Project\crypto-telegram-bot"
fly auth login
fly launch --no-deploy
```

На вопрос имени приложения можно ввести: `deltadesk-bot` (латиница, без пробелов).

### 3. Задайте токен (подставьте НОВЫЙ после /revoke)

```powershell
fly secrets set BOT_TOKEN="ВАШ_НОВЫЙ_ТОКЕН"
```

### 4. Запуск

```powershell
fly deploy
fly logs
```

Если в логах есть `Режим polling` и `Бот запущен` — напишите боту в Telegram `/start`.

Проверка статуса:

```powershell
fly status
```

---

## Вариант B — только на своём ПК (проще, но не 24/7)

1. Дважды щёлкните `setup.bat` (один раз)
2. В `.env` вставьте актуальный `BOT_TOKEN`
3. Дважды щёлкните `start.bat` и **не закрывайте окно**

Пока окно открыто и есть интернет — бот отвечает.

---

## Вариант C — Oracle Cloud (всегда бесплатный VPS)

Сложнее в настройке, зато сервер «навсегда» бесплатный. Подходит, если Fly.io недоступен в вашей стране.

Кратко:

1. Регистрация: https://www.oracle.com/cloud/free/
2. Создать VM (Ubuntu), открыть порт 22
3. Установить Python, скопировать папку `crypto-telegram-bot`
4. `pip install -r requirements.txt`, `.env` с токеном
5. Запуск через `systemd` (служба), чтобы бот перезапускался сам

Подробную инструкцию по Oracle можно запросить отдельно.

---

## Описание бота в BotFather (по желанию)

**Description:**

```
Compare crypto prices across Binance, Bybit, OKX, Kraken, KuCoin, Gate, MEXC. See where to buy cheaper and sell higher. Commands: /price BTC, /analyze ETH
```

**About:**

```
Multi-exchange price scanner. Not financial advice.
```

---

## Частые проблемы

| Проблема | Решение |
|----------|---------|
| Бот не отвечает | Проверьте `fly logs` или что `start.bat` запущен |
| Два экземпляра бота | Остановите `start.bat` на ПК, если уже деплоили на Fly |
| «Conflict: terminated by other getUpdates» | Бот запущен в двух местах — оставьте только облако ИЛИ только ПК |
| Нет Python локально | Запустите `setup.bat` или используйте только Fly.io |
