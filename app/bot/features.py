"""Bot handlers for ref link checking, redirect tracing, and stats analysis."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from app.database import async_session
from app.services.reflinks import add_ref_link, get_user_links, check_and_save, check_link, format_check_result
from app.services.stats_analyzer import analyze_stats, save_stats, format_analysis

router = Router()


# === Feature: Redirect Trace (/check) ===

@router.message(Command("check"))
async def cmd_check(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "🔗 <b>Проверка ссылки — цепочка редиректов</b>\n\n"
            "Формат: <code>/check https://track.partner.com/click?sub_id=123</code>\n\n"
            "Покажу:\n"
            "• Полную цепочку редиректов\n"
            "• HTTP-коды на каждом шаге\n"
            "• Потерянные трекинг-параметры\n"
            "• Скорость и проблемы\n\n"
            "Или проверь на сайте: https://seohub-production.up.railway.app/check"
        )
        return

    url = args[1].strip()
    if not url.startswith("http"):
        url = "https://" + url

    await message.answer("🔄 Проверяю цепочку редиректов...")

    result = await check_link(url)
    text = format_trace_result(result)
    await message.answer(text)


def format_trace_result(result: dict) -> str:
    """Format redirect trace result for Telegram (WhereGoes-style)."""
    chain = result.get("redirect_chain", [])
    issues = result.get("issues", [])
    info = result.get("info", [])
    status = result.get("status_code", 0)
    time_ms = result.get("response_time_ms", 0)
    num_redirects = max(0, len(chain) - 1)

    lines = ["🔗 <b>Проверка ссылки</b>\n"]

    # Summary line
    if any("💀" in i for i in issues):
        lines.append("❌ <b>Статус: Мёртвая</b>")
    elif any("🚩" in i for i in issues):
        lines.append("🚩 <b>Статус: Подозрительно</b>")
    elif any("⚠️" in i for i in issues):
        lines.append("⚠️ <b>Статус: Внимание</b>")
    else:
        lines.append("✅ <b>Статус: Работает</b>")

    lines.append(f"↪️ Редиректов: {num_redirects} | HTTP {status} | {time_ms}ms\n")

    # Chain visualization
    if chain:
        lines.append("📍 <b>Цепочка:</b>\n")
        for i, url in enumerate(chain):
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
            except Exception:
                domain = url

            if i == 0:
                prefix = "🟢 START"
            elif i == len(chain) - 1:
                prefix = "🔴 FINAL" if status >= 400 else "🟢 FINAL"
            else:
                prefix = f"🟡 30x"

            # Truncate URL for readability
            display_url = url if len(url) <= 70 else url[:67] + "..."
            lines.append(f"{prefix}")
            lines.append(f"<code>{display_url}</code>")

            if i < len(chain) - 1:
                # Check if domain changes
                try:
                    next_domain = urlparse(chain[i+1]).netloc
                    if domain != next_domain:
                        lines.append(f"  ↓ <i>{domain} → {next_domain}</i>")
                    else:
                        lines.append("  ↓")
                except Exception:
                    lines.append("  ↓")

    # Issues
    if issues:
        lines.append("\n⚠️ <b>Проблемы:</b>")
        for issue in issues[:5]:
            lines.append(issue)

    # Info
    if info:
        lines.append("\nℹ️ <b>Инфо:</b>")
        for item in info[:5]:
            lines.append(item)

    lines.append(f"\n🌐 <a href='https://seohub-production.up.railway.app/check?url={result.get(\"original_url\", \"\")}'>Подробнее на сайте →</a>")

    return "\n".join(lines)


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
