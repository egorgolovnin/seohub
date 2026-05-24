import logging
from datetime import datetime, timedelta
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import DigestPost, DigestChannel, WeeklyDigest

logger = logging.getLogger(__name__)


async def save_raw_posts(db: AsyncSession, posts: list[dict]) -> int:
    saved = 0
    for p in posts:
        existing = await db.execute(
            select(DigestPost).where(
                and_(
                    DigestPost.channel_username == p.get("channel_username"),
                    DigestPost.original_message_id == p.get("message_id"),
                )
            )
        )
        if existing.scalar_one_or_none():
            continue
        post = DigestPost(
            channel_name=p.get("channel_name", ""),
            channel_username=p.get("channel_username", ""),
            original_text=p["text"],
            original_date=p.get("date"),
            original_message_id=p.get("message_id"),
            status="pending",
        )
        db.add(post)
        saved += 1
    await db.commit()
    return saved


async def get_pending_posts(db: AsyncSession, limit: int = 50) -> list[DigestPost]:
    result = await db.execute(
        select(DigestPost)
        .where(DigestPost.status == "pending")
        .where(DigestPost.importance_score.is_(None))
        .order_by(DigestPost.original_date.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_top_posts_for_today(db: AsyncSession, limit: int = 3) -> list[DigestPost]:
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(DigestPost)
        .where(DigestPost.status == "scored")
        .where(DigestPost.importance_score >= 6.0)
        .where(DigestPost.created_at >= today_start)
        .order_by(DigestPost.importance_score.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_approved_posts(db: AsyncSession, limit: int = 10) -> list[DigestPost]:
    result = await db.execute(
        select(DigestPost)
        .where(DigestPost.status == "approved")
        .order_by(DigestPost.importance_score.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def approve_post(db: AsyncSession, post_id: int) -> bool:
    result = await db.execute(select(DigestPost).where(DigestPost.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        return False
    post.status = "approved"
    await db.commit()
    return True


async def reject_post(db: AsyncSession, post_id: int) -> bool:
    result = await db.execute(select(DigestPost).where(DigestPost.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        return False
    post.status = "rejected"
    await db.commit()
    return True


async def mark_published(db: AsyncSession, post_id: int) -> bool:
    result = await db.execute(select(DigestPost).where(DigestPost.id == post_id))
    post = result.scalar_one_or_none()
    if not post:
        return False
    post.status = "published"
    post.published_at = datetime.utcnow()
    await db.commit()
    return True


async def get_week_posts(db: AsyncSession) -> list[DigestPost]:
    week_ago = datetime.utcnow() - timedelta(days=7)
    result = await db.execute(
        select(DigestPost)
        .where(DigestPost.status == "published")
        .where(DigestPost.published_at >= week_ago)
        .order_by(DigestPost.importance_score.desc())
    )
    return list(result.scalars().all())


async def save_weekly_digest(db: AsyncSession, summary: str, post_ids: list[int]) -> WeeklyDigest:
    now = datetime.utcnow()
    digest = WeeklyDigest(
        week_start=now - timedelta(days=7),
        week_end=now,
        summary=summary,
        post_ids=post_ids,
        status="pending",
    )
    db.add(digest)
    await db.commit()
    await db.refresh(digest)
    return digest


async def get_active_channels(db: AsyncSession) -> list[DigestChannel]:
    result = await db.execute(
        select(DigestChannel).where(DigestChannel.is_active.is_(True))
    )
    return list(result.scalars().all())


async def add_channel(db: AsyncSession, channel_id: str, name: str, username: str = "", category: str = "seo") -> DigestChannel:
    ch = DigestChannel(channel_id=channel_id, name=name, username=username, category=category)
    db.add(ch)
    await db.commit()
    await db.refresh(ch)
    return ch


def format_digest_post(post: DigestPost) -> str:
    category_emoji = {
        "case": "📋", "guide": "📖", "tool": "🛠",
        "news": "📰", "insight": "💡",
    }
    emoji = category_emoji.get(post.category, "📌")
    lines = [f"{emoji} <b>{post.summary or 'Новый пост'}</b>"]
    if post.channel_name:
        lines.append(f"📢 {post.channel_name}")
    if post.original_date:
        lines.append(f"📅 {post.original_date.strftime('%d.%m.%Y')}")
    return "\n".join(lines)


def format_weekly_digest(summary: str, posts: list[DigestPost]) -> str:
    lines = ["📋 <b>Итоги недели в iGaming SEO</b>\n"]
    lines.append(summary)
    lines.append(f"\n📊 Опубликовано {len(posts)} постов за неделю")
    return "\n".join(lines)
