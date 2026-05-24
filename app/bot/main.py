import logging
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
from app.config import get_settings
from app.database import async_session
from app.services.rates import get_rate_for_geo, get_cpa_rates, get_rs_rates, format_rates_message, format_rates_list
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
        bot = Bot(token=settings.bot_token, parse_mode=ParseMode.HTML)
    return bot


# === RATES COMMANDS ===

@router.message(Command("start"))
async def cmd_start(message: Message):
    text = (
        "👋 <b>SEOhub Bot</b>\n\n"
        "💰 <b>Ставки CPA/RS:</b>\n"
        "/rates DE — ставки по ГЕО\n"
        "/cpa — все CPA ставки\n"
        "/rs — все RevShare ставки\n\n"
        "🔗 <b>Реф.ссылки:</b>\n"
        "/addlink URL — добавить на мониторинг\n"
        "/checklinks — проверить все ссылки\n"
        "/mylinks — мои ссылки\n\n"
        "📊 <b>Антишейв-анализ:</b>\n"
        "/analyze — проверить стату из ПП\n\n"
        "Или просто напиши код ГЕО (DE, BR, RU...)"
    )
    await message.answer(text)


@router.message(Command("rates"))
async def cmd_rates(message: Message):
    args = message.text.split(maxsplit=1)
    geo = args[1].strip().upper() if len(args) > 1 else None
    if not geo:
        await message.answer("Укажи ГЕО: <code>/rates DE</code>")
        return
    async with async_session() as db:
        data = await get_rate_for_geo(db, geo)
    if not data:
        await message.answer(f"❌ Нет данных по ГЕО: {geo}\n\nПопробуй: DE, BR, RU, IN, KZ, US, UK, TR")
        return
    await message.answer(format_rates_message(geo, data))


@router.message(Command("cpa"))
async def cmd_cpa(message: Message):
    async with async_session() as db:
        rates = await get_cpa_rates(db)
    await message.answer(format_rates_list(rates, "cpa"))


@router.message(Command("rs"))
async def cmd_rs(message: Message):
    async with async_session() as db:
        rates = await get_rs_rates(db)
    await message.answer(format_rates_list(rates, "rs"))


@router.message(Command("help"))
async def cmd_help(message: Message):
    await cmd_start(message)


# === GEO shortcut - just type country code ===

@router.message(F.text.regexp(r"^[A-Za-z]{2,6}$"))
async def geo_shortcut(message: Message):
    geo = message.text.strip().upper()
    async with async_session() as db:
        data = await get_rate_for_geo(db, geo)
    if data:
        await message.answer(format_rates_message(geo, data))


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
            # Publish to channel
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
        # Publish weekly digest to channel
        text = callback.message.text or callback.message.caption or ""
        b = get_bot()
        if settings.channel_id:
            await b.send_message(settings.channel_id, text, parse_mode=ParseMode.HTML)
        await callback.answer("✅ Опубликовано")
        await callback.message.edit_reply_markup(reply_markup=None)


# === SEND FUNCTIONS (called from scheduler) ===

async def send_digest_approval(post: DigestPost):
    settings = get_settings()
    if not settings.admin_chat_id:
        return
    b = get_bot()
    text = (
        f"📝 <b>Пост на апрув</b>\n\n"
        f"📢 {post.channel_name}\n"
        f"⭐ Оценка: {post.importance_score:.1f}/10\n"
        f"🏷 {post.category}\n\n"
        f"<b>{post.summary}</b>\n\n"
        f"<i>{post.original_text[:500]}{'...' if len(post.original_text) > 500 else ''}</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"digest_approve_{post.id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"digest_reject_{post.id}"),
        ]
    ])
    await b.send_message(settings.admin_chat_id, text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def send_weekly_digest_approval(weekly: WeeklyDigest, posts: list[DigestPost]):
    settings = get_settings()
    if not settings.admin_chat_id:
        return
    b = get_bot()
    text = format_weekly_digest(weekly.summary, posts)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Опубликовать", callback_data="weekly_publish")]
    ])
    await b.send_message(settings.admin_chat_id, text, reply_markup=kb, parse_mode=ParseMode.HTML)


def create_dispatcher() -> Dispatcher:
    global dp
    from app.bot.features import router as features_router
    dp = Dispatcher()
    dp.include_router(router)
    dp.include_router(features_router)
    return dp
