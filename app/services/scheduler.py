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
    """Score pending posts with AI, then immediately send for approval."""
    logger.info("Starting scoring job")
    async with async_session() as db:
        pending = await digest.get_pending_posts(db, limit=30)
        scored = 0
        scored_posts = []
        for post in pending:
            result = await ai.score_post(post.original_text)
            if result:
                post.importance_score = result.get("score", 0)
                post.category = result.get("category", "insight")
                post.summary = result.get("summary", "")
                post.status = "scored"
                scored += 1
                if post.importance_score >= 3.0:
                    scored_posts.append(post)
        await db.commit()
        logger.info(f"Scored {scored}/{len(pending)} posts")

    # Send scored posts for approval immediately
    if scored_posts:
        from app.bot.main import send_digest_approval
        for post in scored_posts:
            try:
                await send_digest_approval(post)
            except Exception as e:
                logger.error(f"Failed to send approval for post {post.id}: {e}")
        logger.info(f"Sent {len(scored_posts)} posts for approval")


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
        from app.bot.main import send_digest_approval
        for post in top_posts:
            await send_digest_approval(post)


async def job_weekly_digest():
    """Friday 18:00 — remind admin to assemble the weekly digest (manual post selection)."""
    logger.info("Starting weekly digest reminder job")
    async with async_session() as db:
        posts = await digest.get_week_posts(db)
    from app.bot.main import notify_admin
    if not posts:
        logger.info("No published posts this week")
        return
    text = (
        f"📅 <b>Пора собрать недельный дайджест</b>\n\n"
        f"За неделю опубликовано постов: <b>{len(posts)}</b>\n\n"
        f"Открой админку → вкладка «Недельный дайджест», "
        f"отметь нужные посты и опубликуй:\n"
        f"https://seohub-production.up.railway.app/admin"
    )
    await notify_admin(text)
    logger.info(f"Weekly digest reminder sent ({len(posts)} posts available)")


async def job_check_links():
    """Check all active ref links twice a day, alert on changes."""
    logger.info("Starting link monitoring job")
    from app.services.reflinks import get_all_active_links, check_and_save
    from app.bot.main import send_link_alert

    async with async_session() as db:
        links = await get_all_active_links(db)
        if not links:
            logger.info("No active links to check")
            return

        logger.info(f"Checking {len(links)} links")
        alerts_sent = 0

        for link in links:
            old_status = link.last_status
            old_final_url = link.last_redirect_url

            try:
                check = await check_and_save(db, link)
            except Exception as e:
                logger.error(f"Error checking link {link.id}: {e}")
                continue

            new_status = link.last_status
            new_final_url = link.last_redirect_url

            # Alert if status changed to bad
            should_alert = False
            alert_lines = [f"🚨 <b>Алерт: реф.ссылка</b>\n"]
            alert_lines.append(f"🔗 <code>{link.url[:70]}</code>\n")

            if old_status in ("ok", "unknown") and new_status in ("dead", "suspicious"):
                should_alert = True
                status_emoji = {"dead": "💀 Мёртвая", "suspicious": "🚩 Подозрительно"}
                alert_lines.append(f"❌ Статус: {old_status} → <b>{status_emoji.get(new_status, new_status)}</b>")

            if old_final_url and new_final_url and old_final_url != new_final_url:
                should_alert = True
                alert_lines.append(f"↪️ Финальный URL изменился!")
                alert_lines.append(f"   Было: <code>{old_final_url[:60]}</code>")
                alert_lines.append(f"   Стало: <code>{new_final_url[:60]}</code>")

            if check.issues:
                new_issues = [i for i in check.issues if "🚩" in i or "💀" in i]
                if new_issues and old_status == "ok":
                    should_alert = True
                    alert_lines.append("\n⚠️ <b>Новые проблемы:</b>")
                    for issue in new_issues[:3]:
                        alert_lines.append(issue)

            if should_alert and not getattr(link, 'alerts_muted', False):
                alert_lines.append(f"\n/checklinks — проверить все")
                await send_link_alert(link.user_id, "\n".join(alert_lines))
                alerts_sent += 1

        logger.info(f"Link check done: {len(links)} checked, {alerts_sent} alerts sent")


def start_scheduler():
    # Fetch channels every 6 hours
    scheduler.add_job(job_fetch_channels, CronTrigger(hour="2,8,14,20", minute=0))
    # Score posts 30 min after fetch
    scheduler.add_job(job_score_posts, CronTrigger(hour="2,8,14,20", minute=30))
    # Daily digest candidates at 12:00
    scheduler.add_job(job_send_daily_digest, CronTrigger(hour=12, minute=0))
    # Weekly digest on Fridays at 18:00
    scheduler.add_job(job_weekly_digest, CronTrigger(day_of_week="fri", hour=18, minute=0))
    # Link monitoring at 9:00 and 21:00 UTC
    scheduler.add_job(job_check_links, CronTrigger(hour="6,18", minute=0))
    # Daily analytics report at 21:00 UTC
    scheduler.add_job(job_daily_analytics, CronTrigger(hour=18, minute=0))

    scheduler.start()
    logger.info("Scheduler started")


async def job_daily_analytics():
    """Send daily analytics summary to admin group."""
    logger.info("Sending daily analytics")
    from app.services.analytics import get_stats, format_stats
    from app.bot.main import notify_admin
    day_stats = await get_stats(1)
    week_stats = await get_stats(7)
    text = format_stats(day_stats) + "\n\n" + format_stats(week_stats)
    await notify_admin(text)
