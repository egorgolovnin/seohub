import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.database import async_session
from app.services import parser, digest, ai
from app.config import get_settings

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def job_fetch_channels():
    """Fetch posts from all channels every 6 hours."""
    logger.info("Starting channel fetch job")
    async with async_session() as db:
        channels = await digest.get_active_channels(db)
        if not channels:
            logger.info("No active channels")
            return
        ch_list = [{"username": ch.username} for ch in channels if ch.username]
        posts = await parser.fetch_all_channels(ch_list, hours_back=8)
        saved = await digest.save_raw_posts(db, posts)
        logger.info(f"Fetched {len(posts)} posts, saved {saved} new")


async def job_score_posts():
    """Score pending posts with AI every 6 hours."""
    logger.info("Starting scoring job")
    async with async_session() as db:
        pending = await digest.get_pending_posts(db, limit=30)
        scored = 0
        for post in pending:
            result = await ai.score_post(post.original_text)
            if result:
                post.importance_score = result.get("score", 0)
                post.category = result.get("category", "insight")
                post.summary = result.get("summary", "")
                post.status = "scored"
                scored += 1
        await db.commit()
        logger.info(f"Scored {scored}/{len(pending)} posts")


async def job_send_daily_digest():
    """Send top-3 posts for admin approval at 10:00, 14:00, 18:00."""
    logger.info("Starting daily digest job")
    settings = get_settings()
    if not settings.admin_chat_id:
        return
    async with async_session() as db:
        top_posts = await digest.get_top_posts_for_today(db, limit=3)
        if not top_posts:
            logger.info("No posts to send for digest")
            return
        # Import bot here to avoid circular imports
        from app.bot.main import send_digest_approval
        for post in top_posts:
            await send_digest_approval(post)


async def job_weekly_digest():
    """Generate weekly digest on Fridays at 18:00."""
    logger.info("Starting weekly digest job")
    async with async_session() as db:
        posts = await digest.get_week_posts(db)
        if not posts:
            logger.info("No posts for weekly digest")
            return
        posts_text = "\n\n---\n\n".join(
            [f"[{p.category}] {p.summary}" for p in posts if p.summary]
        )
        summary = await ai.generate_weekly_summary(posts_text)
        if summary:
            weekly = await digest.save_weekly_digest(
                db, summary, [p.id for p in posts]
            )
            settings = get_settings()
            if settings.admin_chat_id:
                from app.bot.main import send_weekly_digest_approval
                await send_weekly_digest_approval(weekly, posts)


def start_scheduler():
    # Fetch channels every 6 hours
    scheduler.add_job(job_fetch_channels, CronTrigger(hour="2,8,14,20", minute=0))
    # Score posts 30 min after fetch
    scheduler.add_job(job_score_posts, CronTrigger(hour="2,8,14,20", minute=30))
    # Daily digest candidates at 12:00
    scheduler.add_job(job_send_daily_digest, CronTrigger(hour=12, minute=0))
    # Weekly digest on Fridays at 18:00
    scheduler.add_job(job_weekly_digest, CronTrigger(day_of_week="fri", hour=18, minute=0))

    scheduler.start()
    logger.info("Scheduler started")
