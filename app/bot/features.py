"""Bot handlers for ref link checking and stats analysis."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from app.database import async_session
from app.services.reflinks import add_ref_link, get_user_links, check_and_save, format_check_result
from app.services.stats_analyzer import analyze_stats, save_stats, format_analysis

router = Router()


# === Feature 3: Ref Links ===

@router.message(Command("addlink"))
async def cmd_addlink(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "🔗 <b>Добавить реф.ссылку на мониторинг</b>\n\n"
            "Формат: <code>/addlink https://your-link.com?sub_id=123</code>\n\n"
            "Я проверю: работает ли ссылка, не меняется ли редирект, "
            "не пропадают ли параметры трекинга."
        )
        return
    url = args[1].strip()
    if not url.startswith("http"):
        url = "https://" + url
    async with async_session() as db:
        link = await add_ref_link(db, message.from_user.id, url)
        check = await check_and_save(db, link)
        await message.answer(format_check_result(link, check))


@router.message(Command("checklinks"))
async def cmd_checklinks(message: Message):
    async with async_session() as db:
        links = await get_user_links(db, message.from_user.id)
    if not links:
        await message.answer("У тебя нет ссылок. Добавь: <code>/addlink URL</code>")
        return
    await message.answer(f"🔄 Проверяю {len(links)} ссылок...")
    async with async_session() as db:
        for link in links:
            check = await check_and_save(db, link)
            await message.answer(format_check_result(link, check))


@router.message(Command("mylinks"))
async def cmd_mylinks(message: Message):
    async with async_session() as db:
        links = await get_user_links(db, message.from_user.id)
    if not links:
        await message.answer("У тебя нет ссылок. Добавь: <code>/addlink URL</code>")
        return
    status_emoji = {"ok": "✅", "dead": "💀", "suspicious": "🚩", "warning": "⚠️", "unknown": "❓"}
    lines = [f"🔗 <b>Твои ссылки ({len(links)})</b>\n"]
    for link in links:
        emoji = status_emoji.get(link.last_status, "❓")
        lines.append(f"{emoji} <code>{link.url[:60]}</code>")
        if link.last_checked_at:
            lines.append(f"   Проверено: {link.last_checked_at.strftime('%d.%m %H:%M')}")
    lines.append(f"\n/checklinks — проверить все заново")
    await message.answer("\n".join(lines))


# === Feature 4: Stats Analysis ===

class StatsInput(StatesGroup):
    waiting_data = State()


@router.message(Command("analyze"))
async def cmd_analyze(message: Message, state: FSMContext):
    await message.answer(
        "📊 <b>Анализ статистики партнёрки</b>\n\n"
        "Отправь данные в формате:\n"
        "<code>ПП: Royal Partners\n"
        "ГЕО: DE\n"
        "Период: 2026-04\n"
        "Модель: RS\n"
        "Клики: 15000\n"
        "Реги: 1200\n"
        "FTD: 180\n"
        "Депозиты: 24000\n"
        "GGR: 8500\n"
        "Комиссия: 2550</code>\n\n"
        "Я проверю метрики и скажу если что-то подозрительно."
    )
    await state.set_state(StatsInput.waiting_data)


@router.message(StatsInput.waiting_data)
async def process_stats(message: Message, state: FSMContext):
    await state.clear()
    parsed = parse_stats_input(message.text)
    if not parsed:
        await message.answer("❌ Не удалось разобрать данные. Проверь формат и попробуй снова: /analyze")
        return
    analysis = analyze_stats(parsed, parsed.get("geo", ""))
    async with async_session() as db:
        await save_stats(db, message.from_user.id, parsed, analysis)
    await message.answer(format_analysis(parsed, analysis))


def parse_stats_input(text: str) -> dict | None:
    """Parse user input for stats analysis."""
    lines = text.strip().split("\n")
    data = {}
    field_map = {
        "пп": "program_name", "pp": "program_name", "партнёрка": "program_name", "партнерка": "program_name",
        "гео": "geo", "geo": "geo",
        "период": "period", "period": "period",
        "модель": "model", "model": "model",
        "клики": "clicks", "clicks": "clicks",
        "реги": "registrations", "реги": "registrations", "registrations": "registrations", "регистрации": "registrations",
        "ftd": "ftd", "фтд": "ftd",
        "депозиты": "deposits_sum", "deposits": "deposits_sum", "сумма депозитов": "deposits_sum",
        "ggr": "ggr", "ггр": "ggr",
        "комиссия": "commission", "commission": "commission", "доход": "commission",
    }
    numeric_fields = {"clicks", "registrations", "ftd", "deposits_sum", "ggr", "commission"}

    for line in lines:
        line = line.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        field = field_map.get(key)
        if field:
            if field in numeric_fields:
                try:
                    value = value.replace("$", "").replace(",", "").replace(" ", "")
                    data[field] = float(value)
                except ValueError:
                    continue
            else:
                data[field] = value

    if not data.get("clicks") and not data.get("ftd"):
        return None
    return data
