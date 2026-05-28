import logging
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from app.config import get_settings
from app.database import async_session
from app.services.rates import get_rate_for_geo, get_cpa_rates, format_rates_message, format_rates_list, resolve_geo_alias
from app.services.digest import approve_post, reject_post, mark_published, format_digest_post, format_weekly_digest, get_approved_posts
from app.models.models import DigestPost, WeeklyDigest

logger = logging.getLogger(__name__)
router = Router()
bot: Bot | None = None
dp: Dispatcher | None = None


def get_bot() -> Bot:
    global bot
    if bot is None:
        settings = get_settings()
        bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    return bot


def _admin_chat() -> int:
    """Get admin group or fallback to admin chat."""
    settings = get_settings()
    return settings.admin_group_id or settings.admin_chat_id


async def notify_admin(text: str, reply_markup=None):
    """Send notification to admin group."""
    target = _admin_chat()
    if not target:
        return
    try:
        b = get_bot()
        await b.send_message(target, text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Admin notify error: {e}")


async def notify_activity(user: str, action: str, details: str = "", user_id: int = None):
    """Log user activity to admin group and DB."""
    text = f"👤 <b>{user}</b> → {action}"
    if details:
        text += f"\n{details}"
    await notify_admin(text)
    # Track in analytics DB
    from app.services.analytics import track
    event_type = action.split(" ")[1].replace("/", "") if "/" in action else action.split(" ")[0]
    await track(event_type=event_type, user_id=user_id, username=user, details=details)


# === RATES COMMANDS ===

@router.message(Command("start"))
async def cmd_start(message: Message):
    site = "https://seohub-production.up.railway.app"
    user = f"@{message.from_user.username}" if message.from_user.username else str(message.from_user.id)
    text = (
        "👋 <b>SEOhub Bot</b>\n"
        "📢 Канал: @seonewsbyhub\n\n"

        "💰 <b>Ставки CPA:</b>\n"
        "/rates DE — ставки (Германия, Germany...)\n"
        "/cpa — все CPA ставки\n\n"

        "🔗 <b>Мониторинг ссылок:</b>\n"
        "/check URL — цепочка редиректов\n"
        "/addlink URL — на мониторинг\n"
        "/mylinks — мои ссылки\n"
        "/deletelink — удалить ссылку\n"
        "/report — сводка по всем\n\n"

        "📊 <b>Антишейв-анализ:</b>\n"
        "/analyze — кинь скриншот или текст из ПП\n\n"

        f"🌐 <b>На сайте:</b>\n"
        f"<a href='{site}'>Главная</a> · "
        f"<a href='{site}/check'>Проверка ссылок</a> · "
        f"<a href='{site}/#geo'>Ставки</a> · "
        f"<a href='{site}/#tools'>Инструменты</a> · "
        f"<a href='{site}/#con'>Консьерж</a> · "
        f"<a href='{site}/#sites'>Купля/продажа</a>\n\n"

        "Или просто напиши ГЕО: DE, Германия, Germany..."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📢 Канал", url="https://t.me/seonewsbyhub"),
            InlineKeyboardButton(text="🌐 Сайт", url=site),
        ],
        [
            InlineKeyboardButton(text="🔗 Проверка ссылок", url=f"{site}/check"),
            InlineKeyboardButton(text="💰 Ставки", url=f"{site}/#geo"),
        ],
        [
            InlineKeyboardButton(text="🛠 Инструменты", url=f"{site}/#tools"),
            InlineKeyboardButton(text="🤝 Консьерж", url=f"{site}/#con"),
        ],
    ])
    await message.answer(text, reply_markup=kb)
    await notify_activity(user, "🚀 /start", user_id=message.from_user.id)


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    settings = get_settings()
    if message.from_user.id != settings.admin_chat_id:
        await message.answer("⛔ Только для админа")
        return
    from app.services.analytics import get_stats, format_stats
    # Day stats
    day = await get_stats(1)
    week = await get_stats(7)
    total = await get_stats(365)
    text = format_stats(day) + "\n\n" + format_stats(week) + "\n\n" + format_stats(total)
    await message.answer(text)


@router.message(Command("rates"))
async def cmd_rates(message: Message):
    args = message.text.split(maxsplit=1)
    geo_input = args[1].strip() if len(args) > 1 else None
    if not geo_input:
        await message.answer("Укажи ГЕО: <code>/rates DE</code> или <code>/rates Германия</code>")
        return
    geo = resolve_geo_alias(geo_input)
    async with async_session() as db:
        data = await get_rate_for_geo(db, geo)
    if not data:
        await message.answer(
            f"❌ Нет данных по: {geo_input} (→ {geo})\n\n"
            f"Попробуй: DE, BR, RU, IN, KZ, US, UK, TR\n"
            f"Или: Германия, Бразилия, Россия, Germany..."
        )
        return
    header = f" ({geo_input})" if geo_input.upper() != geo else ""
    await message.answer(format_rates_message(geo + header, data))


@router.message(Command("cpa"))
async def cmd_cpa(message: Message):
    async with async_session() as db:
        rates = await get_cpa_rates(db)
    await message.answer(format_rates_list(rates, "cpa"))


@router.message(Command("help"))
async def cmd_help(message: Message):
    await cmd_start(message)


# === GEO shortcut - type country code OR name ===

@router.message(F.text.regexp(r"^[A-Za-zА-Яа-яёЁ\s]{2,20}$"))
async def geo_shortcut(message: Message):
    text = message.text.strip()
    geo = resolve_geo_alias(text)
    async with async_session() as db:
        data = await get_rate_for_geo(db, geo)
    if data:
        header = f" ({text})" if text.upper() != geo else ""
        await message.answer(format_rates_message(geo + header, data))


# === DIGEST APPROVAL (admin only) ===

@router.callback_query(F.data.startswith("digest_"))
async def digest_callback(callback: CallbackQuery):
    settings = get_settings()
    if callback.from_user.id != settings.admin_chat_id:
        await callback.answer("⛔ Только для админа")
        return

    action, post_id_str = callback.data.split("_", 2)[1], callback.data.split("_", 2)[2]
    post_id = int(post_id_str)

    async with async_session() as db:
        if action == "approve":
            await approve_post(db, post_id)
            await callback.answer("✅ Одобрено")
            await callback.message.edit_reply_markup(reply_markup=None)
            settings = get_settings()
            if settings.channel_id:
                from sqlalchemy import select
                result = await db.execute(select(DigestPost).where(DigestPost.id == post_id))
                post = result.scalar_one_or_none()
                if post:
                    b = get_bot()
                    await b.send_message(settings.channel_id, format_digest_post(post), parse_mode=ParseMode.HTML)
                    await mark_published(db, post_id)
        elif action == "reject":
            await reject_post(db, post_id)
            await callback.answer("❌ Отклонено")
            await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("weekly_"))
async def weekly_callback(callback: CallbackQuery):
    settings = get_settings()
    if callback.from_user.id != settings.admin_chat_id:
        await callback.answer("⛔ Только для админа")
        return

    action = callback.data.split("_")[1]
    if action == "publish":
        text = callback.message.text or callback.message.caption or ""
        b = get_bot()
        if settings.channel_id:
            await b.send_message(settings.channel_id, text, parse_mode=ParseMode.HTML)
        await callback.answer("✅ Опубликовано")
        await callback.message.edit_reply_markup(reply_markup=None)


# === SEND FUNCTIONS (called from scheduler) ===

async def send_digest_approval(post: DigestPost):
    from app.services.digest import format_digest_approval
    text = format_digest_approval(post)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"digest_approve_{post.id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"digest_reject_{post.id}"),
        ]
    ])
    await notify_admin(text, reply_markup=kb)


async def send_weekly_digest_approval(weekly: WeeklyDigest, posts: list[DigestPost]):
    text = format_weekly_digest(weekly.summary, posts)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Опубликовать", callback_data="weekly_publish")]
    ])
    await notify_admin(text, reply_markup=kb)


# === ALERT for link monitoring (called from scheduler) ===

async def send_link_alert(user_id: int, text: str):
    """Send alert to user AND admin group about link status change."""
    try:
        b = get_bot()
        await b.send_message(user_id, text, parse_mode=ParseMode.HTML)
        # Also notify admin group
        await notify_admin(f"🔔 Link alert sent to {user_id}:\n{text[:300]}")
    except Exception as e:
        logger.error(f"Failed to send link alert to {user_id}: {e}")


def create_dispatcher() -> Dispatcher:
    global dp
    from app.bot.features import router as features_router
    dp = Dispatcher()
    dp.include_router(router)
    dp.include_router(features_router)
    return dp
