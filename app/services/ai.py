import json
import base64
import logging
from anthropic import AsyncAnthropic
from app.config import get_settings

logger = logging.getLogger(__name__)

SCORE_SYSTEM = """Ты — редактор дайджеста по iGaming SEO. Оцени пост из Telegram-канала.

Оцени по шкале 0-10:
- 8-10: кейс с цифрами, важная новость индустрии, полезный гайд
- 5-7: интересная мысль, обсуждение инструмента, мнение эксперта
- 2-4: реклама, общие рассуждения, малополезно
- 0-1: спам, оффтоп, мусор

Определи категорию: case (кейс), guide (гайд), tool (инструмент), news (новость), insight (мысль/инсайт)

Напиши краткое саммари (1-2 предложения) для публикации.

Ответь СТРОГО в JSON:
{"score": 7.5, "category": "case", "summary": "Краткое описание на русском"}"""

WEEKLY_SYSTEM = """Ты — редактор недельного дайджеста по iGaming SEO.
На основе списка постов за неделю напиши итоговый обзор (5-8 предложений).
Выдели ключевые темы, тренды, важные события. Пиши на русском, кратко и по делу."""

ANALYZE_SYSTEM = """Ты — эксперт по iGaming аффилиатному маркетингу и антишейв-аналитик.

Пользователь прислал данные из партнёрской программы (скриншот дашборда, текст или таблицу).

Твоя задача:
1. Извлеки все метрики которые видишь: клики, регистрации, FTD, депозиты, GGR, комиссия, конверсии
2. Определи ПП (партнёрку), ГЕО, период если видно
3. Рассчитай ключевые показатели:
   - CR (клик→рег): норма 5-15%
   - Рег→FTD: норма 10-25%
   - Средний депозит: зависит от ГЕО ($50-200 EU, $20-80 RU/CIS)
   - GGR/FTD: норма $30-150
   - Комиссия/FTD (эффективный CPA): сравни с рыночными ставками
4. Выяви подозрительное:
   - CR слишком низкий/высокий → шейв регистраций или фрод
   - Рег→FTD слишком низкий → шейв FTD
   - GGR отрицательный или слишком высокий → манипуляция
   - Комиссия не сходится с условиями → шейв комиссии
5. Дай вердикт: ✅ Норма / ⚠️ Подозрительно / 🚩 Вероятный шейв

Отвечай на русском. Структурируй ответ с эмодзи. Будь конкретен — называй цифры и что именно не так.
Если данных мало — скажи что видишь и что нужно ещё для полного анализа."""


async def score_post(text: str) -> dict | None:
    settings = get_settings()
    if not settings.anthropic_api_key:
        logger.warning("No Anthropic API key, skipping scoring")
        return None
    try:
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=SCORE_SYSTEM,
            messages=[{"role": "user", "content": f"Пост из канала:\n\n{text[:2000]}"}],
        )
        raw = response.content[0].text.strip()
        raw = raw.removeprefix("```json").removesuffix("```").strip()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Score post error: {e}")
        return None


async def generate_weekly_summary(posts_text: str) -> str | None:
    settings = get_settings()
    if not settings.anthropic_api_key:
        return None
    try:
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system=WEEKLY_SYSTEM,
            messages=[{"role": "user", "content": f"Посты за неделю:\n\n{posts_text[:6000]}"}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error(f"Weekly summary error: {e}")
        return None


async def analyze_stats_ai(text: str = None, image_data: bytes = None, image_mime: str = "image/jpeg") -> str | None:
    """Analyze partner program stats from text, screenshot, or both."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        return "❌ API ключ не настроен. Обратись к администратору."
    try:
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)

        content = []
        if image_data:
            b64 = base64.b64encode(image_data).decode("utf-8")
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_mime,
                    "data": b64,
                }
            })
        if text:
            content.append({"type": "text", "text": f"Данные из партнёрки:\n\n{text[:4000]}"})
        elif not image_data:
            return "❌ Нет данных для анализа."

        if not any(c.get("type") == "text" for c in content):
            content.append({"type": "text", "text": "Проанализируй этот скриншот дашборда партнёрской программы."})

        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=ANALYZE_SYSTEM,
            messages=[{"role": "user", "content": content}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error(f"Analyze stats AI error: {e}")
        return f"❌ Ошибка анализа: {str(e)[:100]}"
