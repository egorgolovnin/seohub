"""Bot handlers for ref link checking, redirect tracing, and stats analysis."""
import socket
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from app.database import async_session
from app.services.reflinks import (
    add_ref_link, get_user_links, check_and_save, check_link,
    format_check_result, find_existing_link, set_user_mute,
    delete_user_link, get_last_check,
)
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
            "Покажу полную цепочку редиректов, HTTP-коды, "
            "потерянные параметры и скорость.\n\n"
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


def _resolve_geo(domain: str) -> str:
    """Resolve domain to country via IP geolocation (basic)."""
    try:
        ip = socket.gethostbyname(domain)
        return ip
    except Exception:
        return ""


def format_trace_result(result: dict) -> str:
    """Format redirect trace result for Telegram (WhereGoes-style)."""
    chain = result.get("redirect_chain", [])
    codes = result.get("redirect_codes", [])
    issues = result.get("issues", [])
    info = result.get("info", [])
    status = result.get("status_code", 0)
    time_ms = result.get("response_time_ms", 0)
    landing = result.get("landing")
    server_geo = result.get("server_geo")
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

    # Chain visualization with HTTP codes
    if chain:
        lines.append("📍 <b>Цепочка:</b>\n")
        from urllib.parse import urlparse
        for i, url in enumerate(chain):
            try:
                domain = urlparse(url).netloc
            except Exception:
                domain = url

            code = codes[i] if i < len(codes) else ""

            if i == 0:
                prefix = "🟢 START"
            elif i == len(chain) - 1:
                prefix = f"🔴 {status}" if status >= 400 else f"🟢 {status}"
            else:
                prefix = f"🟡 {code}" if code else "🟡 30x"

            display_url = url if len(url) <= 70 else url[:67] + "..."
            lines.append(f"{prefix}")
            lines.append(f"<code>{display_url}</code>")

            if i < len(chain) - 1:
                try:
                    next_domain = urlparse(chain[i + 1]).netloc
                    if domain != next_domain:
                        lines.append(f"  ↓ <i>{domain} → {next_domain}</i>")
                    else:
                        lines.append("  ↓")
                except Exception:
                    lines.append("  ↓")

    # Landing page analysis
    if landing:
        lines.append("\n🌐 <b>Лендинг:</b>")
        if landing.get("title"):
            lines.append(f"📄 {landing['title'][:80]}")
        if landing.get("language"):
            lines.append(f"🗣 Язык: {landing['language']}")
        if landing.get("has_reg_form"):
            lines.append("📝 Форма регистрации: ✅")
        if landing.get("is_gambling"):
            lines.append("🎰 Гемблинг-сайт: ✅")
        size_kb = (landing.get("content_length") or 0) / 1024
        if size_kb > 0:
            lines.append(f"📦 Размер: {size_kb:.0f} KB")

    # Server geo
    if server_geo:
        if server_geo.get("ip"):
            geo_line = f"🌍 Сервер: {server_geo['ip']}"
            if server_geo.get("country"):
                geo_line += f" ({server_geo['country']})"
            lines.append(geo_line)

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

    orig_url = result.get("original_url", "")
    check_url = f"https://seohub-production.up.railway.app/check?url={orig_url}"
    lines.append(f"\n🌐 <a href='{check_url}'>Подробнее на сайте →</a>")

    # Show where checked from
    checked_from = result.get("checked_from")
    if checked_from:
        lines.append(f"📡 Проверено из: {checked_from}")

    return "\n".join(lines)


# === Feature 3: Ref Links ===

@router.message(Command("addlink"))
async def cmd_addlink(message: Message):
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.answer(
            "🔗 <b>Добавить реф.ссылку на мониторинг</b>\n\n"
            "Формат: <code>/addlink URL</code>\n"
            "С ГЕО: <code>/addlink URL CY</code>\n\n"
            "ГЕО нужен чтобы проверять через прокси нужной страны.\n"
            "Проверка автоматически 2 раза в день (9:00 и 21:00).\n"
            "Если что-то сломается или изменится — пришлю алерт."
        )
        return
    url = args[1].strip()
    if not url.startswith("http"):
        url = "https://" + url

    # Parse optional GEO
    geo = ""
    if len(args) > 2:
        from app.services.rates import resolve_geo_alias
        geo = resolve_geo_alias(args[2].strip())

    async with async_session() as db:
        existing = await find_existing_link(db, message.from_user.id, url)
        if existing:
            await message.answer("⚠️ Эта ссылка уже на мониторинге.\n\n/mylinks — посмотреть все")
            return
        link = await add_ref_link(db, message.from_user.id, url, geo=geo)
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
    buttons = []
    for idx, link in enumerate(links):
        emoji = status_emoji.get(link.last_status, "❓")
        geo_badge = f" [{link.geo}]" if link.geo else ""
        lines.append(f"{idx+1}. {emoji}{geo_badge} <code>{link.url[:50]}</code>")
        if link.last_checked_at:
            lines.append(f"   Проверено: {link.last_checked_at.strftime('%d.%m %H:%M')}")
        buttons.append([
            InlineKeyboardButton(text=f"🔄 Проверить #{idx+1}", callback_data=f"recheck_{link.id}"),
            InlineKeyboardButton(text=f"🗑 Удалить #{idx+1}", callback_data=f"dellink_{link.id}"),
        ])
    lines.append(f"\n🔄 Автопроверка: 09:00 и 21:00 ежедневно")
    lines.append(f"/mutelinks — выключить пуши")
    lines.append(f"/report — сводка по всем ссылкам")

    kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
    await message.answer("\n".join(lines), reply_markup=kb)


# Inline: recheck one link
@router.callback_query(F.data.startswith("recheck_"))
async def cb_recheck(callback: CallbackQuery):
    link_id = int(callback.data.split("_")[1])
    await callback.answer("🔄 Проверяю...")
    async with async_session() as db:
        from sqlalchemy import select
        from app.models.features import RefLink
        result = await db.execute(
            select(RefLink).where(RefLink.id == link_id, RefLink.user_id == callback.from_user.id)
        )
        link = result.scalar_one_or_none()
        if not link:
            await callback.message.answer("❌ Ссылка не найдена")
            return
        check = await check_and_save(db, link)
        await callback.message.answer(format_check_result(link, check))


# Inline: delete link
@router.callback_query(F.data.startswith("dellink_"))
async def cb_dellink(callback: CallbackQuery):
    link_id = int(callback.data.split("_")[1])
    async with async_session() as db:
        success = await delete_user_link(db, callback.from_user.id, link_id)
    if success:
        await callback.answer("🗑 Удалено")
        await callback.message.answer("🗑 Ссылка удалена с мониторинга.\n\n/mylinks — оставшиеся ссылки")
    else:
        await callback.answer("❌ Не найдена")


@router.message(Command("deletelink"))
async def cmd_deletelink(message: Message):
    async with async_session() as db:
        links = await get_user_links(db, message.from_user.id)
    if not links:
        await message.answer("У тебя нет ссылок.")
        return
    lines = ["🗑 <b>Удалить ссылку</b>\n\nНажми кнопку чтобы удалить:\n"]
    buttons = []
    for idx, link in enumerate(links):
        lines.append(f"{idx+1}. <code>{link.url[:55]}</code>")
        buttons.append([InlineKeyboardButton(
            text=f"🗑 Удалить #{idx+1}",
            callback_data=f"dellink_{link.id}"
        )])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("\n".join(lines), reply_markup=kb)


# === /report — summary of all links ===

@router.message(Command("report"))
async def cmd_report(message: Message):
    async with async_session() as db:
        links = await get_user_links(db, message.from_user.id)
    if not links:
        await message.answer("У тебя нет ссылок. Добавь: <code>/addlink URL</code>")
        return

    total = len(links)
    ok = sum(1 for l in links if l.last_status == "ok")
    dead = sum(1 for l in links if l.last_status == "dead")
    suspicious = sum(1 for l in links if l.last_status == "suspicious")
    warning = sum(1 for l in links if l.last_status == "warning")
    unknown = sum(1 for l in links if l.last_status == "unknown")

    lines = ["📊 <b>Отчёт по ссылкам</b>\n"]
    lines.append(f"Всего: {total}")
    lines.append(f"✅ Работают: {ok}")
    if dead:
        lines.append(f"💀 Мёртвые: {dead}")
    if suspicious:
        lines.append(f"🚩 Подозрительные: {suspicious}")
    if warning:
        lines.append(f"⚠️ Внимание: {warning}")
    if unknown:
        lines.append(f"❓ Не проверены: {unknown}")

    # Problem links details
    problem_links = [l for l in links if l.last_status in ("dead", "suspicious", "warning")]
    if problem_links:
        lines.append("\n<b>Проблемные ссылки:</b>")
        status_emoji = {"dead": "💀", "suspicious": "🚩", "warning": "⚠️"}
        for link in problem_links:
            emoji = status_emoji.get(link.last_status, "⚠️")
            lines.append(f"\n{emoji} <code>{link.url[:60]}</code>")
            if link.alerts:
                for alert in link.alerts[-2:]:
                    lines.append(f"   {alert}")

    # Alerts summary
    total_alerts = sum(len(l.alerts or []) for l in links)
    if total_alerts:
        lines.append(f"\n🚨 Всего алертов: {total_alerts}")

    muted = sum(1 for l in links if getattr(l, 'alerts_muted', False))
    if muted:
        lines.append(f"🔇 Замьючено: {muted}")

    lines.append("\n/checklinks — проверить все сейчас")
    await message.answer("\n".join(lines))


@router.message(Command("mutelinks"))
async def cmd_mutelinks(message: Message):
    async with async_session() as db:
        count = await set_user_mute(db, message.from_user.id, True)
    if count:
        await message.answer(f"🔇 Пуши выключены для {count} ссылок.\n\n/unmutelinks — включить обратно")
    else:
        await message.answer("У тебя нет ссылок. Добавь: <code>/addlink URL</code>")


@router.message(Command("unmutelinks"))
async def cmd_unmutelinks(message: Message):
    async with async_session() as db:
        count = await set_user_mute(db, message.from_user.id, False)
    if count:
        await message.answer(f"🔔 Пуши включены для {count} ссылок.\n\nПроверка: 09:00 и 21:00 ежедневно.")
    else:
        await message.answer("У тебя нет ссылок. Добавь: <code>/addlink URL</code>")


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
