# SEOhub — Гайд по деплою и тестированию

## Шаг 0: Что тебе нужно перед началом

- [ ] Аккаунт на [railway.com](https://railway.com)
- [ ] Git установлен (`git --version`)
- [ ] Python 3.11+ установлен локально (`python --version`)
- [ ] Telegram API credentials: зайди на https://my.telegram.org → API development tools → получи `api_id` и `api_hash`
- [ ] Anthropic API key: https://console.anthropic.com → API Keys
- [ ] Telegram-канал создан (бот будет постить дайджест туда)
- [ ] Бот добавлен как админ в этот канал

---

## Шаг 1: Распаковка и настройка локально

```bash
# Распакуй архив
mkdir seohub && cd seohub
tar -xzf seohub-v2.tar.gz

# Создай виртуальное окружение
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# или .venv\Scripts\activate  # Windows

# Установи зависимости
pip install -e ".[dev]"

# Скопируй .env
cp .env.example .env
```

---

## Шаг 2: Заполни .env

Открой `.env` и заполни:

```env
# Railway даст этот URL автоматически, для локальной разработки:
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/seohub

# Токен бота (уже есть)
BOT_TOKEN=8865741497:AAFiUaDoCkZ9A7LyhHX0y04PJwLG5tk66qQ

# Твой Telegram user ID (чтобы получать посты на апрув)
# Узнать: напиши @userinfobot в Telegram
ADMIN_CHAT_ID=ТВОЙ_TELEGRAM_ID

# ID канала для дайджеста (формат: -100XXXXXXXXXX)
# Узнать: добавь бота @getidsbot в канал
CHANNEL_ID=-100XXXXXXXXXX

# Для парсинга каналов (Telethon)
TELETHON_API_ID=твой_api_id
TELETHON_API_HASH=твой_api_hash
TELETHON_SESSION_STRING=  # заполним в шаге 3

# Claude API для дайджеста
ANTHROPIC_API_KEY=sk-ant-...

# Режим
APP_ENV=development
APP_PORT=8000
```

---

## Шаг 3: Генерация Telethon-сессии

Это нужно сделать **один раз локально**:

```bash
python scripts/gen_session.py
```

Скрипт попросит:
1. `api_id` → введи свой
2. `api_hash` → введи свой
3. Номер телефона → твой номер с +
4. Код из Telegram → введи

Скрипт выведет длинную строку — это сессия.
Скопируй её в `.env` → `TELETHON_SESSION_STRING=...`

---

## Шаг 4: Локальные тесты (без БД)

```bash
# Запусти все тесты
python -m pytest tests/ -v

# Ожидаемый результат: 55 passed
```

Если все 55 тестов прошли — код работает. Тесты используют SQLite in-memory, PostgreSQL не нужен.

---

## Шаг 5: Деплой на Railway

### 5.1. Создай проект

1. Зайди на https://railway.com → New Project
2. Deploy from GitHub repo (или Empty project)

### 5.2. Добавь PostgreSQL

1. В проекте нажми "+ New" → Database → PostgreSQL
2. Railway автоматически создаст `DATABASE_URL`

### 5.3. Залей код

**Вариант А: Через GitHub (рекомендую)**
```bash
cd seohub
git init
git add .
git commit -m "Initial commit: features 1-4"
git remote add origin https://github.com/YOUR/seohub.git
git push -u origin main
```
В Railway: "+ New" → GitHub Repo → выбери seohub

**Вариант Б: Через Railway CLI**
```bash
npm install -g @railway/cli
railway login
railway init
railway up
```

### 5.4. Настрой переменные окружения

В Railway → твой сервис → Variables → добавь все из `.env`:

```
BOT_TOKEN=8865741497:AAFiUaDoCkZ9A7LyhHX0y04PJwLG5tk66qQ
ADMIN_CHAT_ID=твой_id
CHANNEL_ID=-100xxx
TELETHON_API_ID=xxx
TELETHON_API_HASH=xxx
TELETHON_SESSION_STRING=длинная_строка
ANTHROPIC_API_KEY=sk-ant-xxx
APP_ENV=production
```

`DATABASE_URL` Railway подставит сам — проверь что он в формате `postgresql+asyncpg://...`. Если Railway даёт `postgresql://...`, добавь переменную:
```
DATABASE_URL=${PGDATABASE_URL}  # или замени postgresql:// на postgresql+asyncpg://
```

### 5.5. Обнови webhook URL

В файле `app/main.py` замени:
```python
webhook_url = f"https://your-app.railway.app/webhook"
```
На твой реальный Railway URL:
```python
webhook_url = f"https://seohub-production-xxxx.up.railway.app/webhook"
```

Или лучше — добавь переменную `WEBHOOK_URL` в Railway и используй её.

### 5.6. Загрузи ставки в БД

После деплоя, когда сервис запущен:

```bash
# Через Railway CLI
railway run python scripts/load_rates.py data/seohub_rates_database.xlsx
```

Или добавь одноразовый cron в Railway: `python scripts/load_rates.py data/seohub_rates_database.xlsx`

---

## Шаг 6: Проверка что всё работает

### 6.1. Health check

Открой в браузере:
```
https://твой-url.railway.app/health
```
Ожидаемый ответ: `{"status": "ok"}`

### 6.2. Веб-страница ставок

Открой:
```
https://твой-url.railway.app/rates
```
Должна появиться таблица CPA/RS с переключением и фильтром.

### 6.3. API

Проверь API в браузере или через curl:

```bash
# Все CPA ставки
curl https://твой-url.railway.app/api/rates/cpa

# Ставки по конкретному ГЕО
curl https://твой-url.railway.app/api/rates/DE

# RS ставки
curl https://твой-url.railway.app/api/rates/rs

# Проверка реф.ссылки
curl "https://твой-url.railway.app/api/check-link?url=https://example.com"

# Анализ статистики
curl -X POST https://твой-url.railway.app/api/analyze-stats \
  -H "Content-Type: application/json" \
  -d '{"clicks":10000,"registrations":800,"ftd":120,"deposits_sum":15000,"ggr":5000,"commission":2000,"model":"RS","geo":"DE"}'
```

### 6.4. Telegram бот

Открой бота в Telegram и проверь каждую команду:

```
/start
→ Должен показать список всех команд

/rates DE
→ Должен показать CPA и RS для Германии

/cpa
→ Список всех CPA ставок

/rs
→ Список всех RevShare ставок

DE
→ Просто напиши код ГЕО — бот должен ответить ставками

/addlink https://track.example.com?sub_id=test123
→ Добавит ссылку и сразу проверит

/mylinks
→ Покажет список твоих ссылок

/checklinks
→ Перепроверит все ссылки

/analyze
→ Покажет формат ввода

# Затем отправь:
ПП: Royal Partners
ГЕО: DE
Период: 2026-04
Модель: RS
Клики: 15000
Реги: 1200
FTD: 180
Депозиты: 24000
GGR: 8500
Комиссия: 2550

→ Должен показать анализ с метриками и вердиктом
```

### 6.5. Дайджест (проверка вручную)

Дайджест работает по расписанию, но можно проверить вручную. Добавь тестовый канал через Python shell на Railway:

```bash
railway run python -c "
import asyncio
from app.database import async_session, init_db
from app.services.digest import add_channel

async def main():
    await init_db()
    async with async_session() as db:
        await add_channel(db, '1234', 'Test Channel', 'test_channel_username', 'seo')
        print('Channel added')

asyncio.run(main())
"
```

Или подожди — scheduler запустится автоматически и начнёт парсить каналы по расписанию (каждые 6 часов).

---

## Шаг 7: Чеклист "всё работает"

### Фича 1: Ставки
- [ ] `/rates DE` возвращает данные
- [ ] `/cpa` показывает таблицу
- [ ] `/rs` показывает таблицу  
- [ ] Ввод "BR" (просто текст) показывает ставки
- [ ] Веб-страница /rates отображается
- [ ] API /api/rates/cpa отдаёт JSON
- [ ] API /api/rates/DE отдаёт JSON

### Фича 2: Дайджест
- [ ] TELETHON_SESSION_STRING заполнен
- [ ] ANTHROPIC_API_KEY заполнен
- [ ] ADMIN_CHAT_ID заполнен
- [ ] CHANNEL_ID заполнен
- [ ] Каналы добавлены в БД
- [ ] Scheduler запустился (видно в логах: "Scheduler started")
- [ ] Тестовый пост приходит на апрув (кнопки ✅/❌)
- [ ] После апрува пост публикуется в канал

### Фича 3: Реф.ссылки
- [ ] `/addlink URL` добавляет и проверяет ссылку
- [ ] `/mylinks` показывает список
- [ ] `/checklinks` перепроверяет все
- [ ] Мёртвая ссылка показывает 💀
- [ ] API /api/check-link?url=... работает

### Фича 4: Антишейв-анализ
- [ ] `/analyze` показывает формат
- [ ] Отправка статистики возвращает анализ
- [ ] Шейв детектится (RS 10% при норме 30-60%)
- [ ] Нормальная стата показывает ✅
- [ ] API /api/analyze-stats работает

---

## Проблемы и решения

### Бот не отвечает
1. Проверь логи Railway: `railway logs`
2. Проверь webhook: `curl https://api.telegram.org/bot{TOKEN}/getWebhookInfo`
3. Если webhook не установлен — проверь URL в `app/main.py`

### Ставки пустые
1. Загрузил ли ты данные? `python scripts/load_rates.py`
2. Проверь подключение к БД в логах

### Telethon не работает
1. Сессия могла протухнуть → перегенерируй: `python scripts/gen_session.py`
2. Проверь `TELETHON_API_ID` и `TELETHON_API_HASH`

### Дайджест не приходит
1. Проверь `ADMIN_CHAT_ID` — это числовой ID, не username
2. Проверь `CHANNEL_ID` — должен начинаться с -100
3. Проверь что бот — админ канала с правом постить
4. Проверь `ANTHROPIC_API_KEY`

### Railway не деплоит
1. Проверь Dockerfile — должен быть в корне
2. Проверь что `railway.toml` на месте
3. В логах Railway ищи ошибку

---

## Мониторинг

### Логи
```bash
railway logs -f  # в реальном времени
```

### Статус бота
```bash
curl https://api.telegram.org/bot8865741497:AAFiUaDoCkZ9A7LyhHX0y04PJwLG5tk66qQ/getWebhookInfo
```

### БД
```bash
railway connect postgres  # подключиться к БД
\dt                        # список таблиц
SELECT count(*) FROM geo_rates_cpa;
SELECT count(*) FROM digest_posts;
SELECT count(*) FROM ref_links;
```
