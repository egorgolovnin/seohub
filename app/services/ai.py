import json
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


async def score_post(text: str) -> dict | None:
    settings = get_settings()
    if not settings.anthropic_api_key:
        logger.warning("No Anthropic API key, skipping scoring")
        return None
    try:
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
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
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=WEEKLY_SYSTEM,
            messages=[{"role": "user", "content": f"Посты за неделю:\n\n{posts_text[:6000]}"}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error(f"Weekly summary error: {e}")
        return None
