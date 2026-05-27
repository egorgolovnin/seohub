import logging
from datetime import datetime, timedelta
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import async_session
from app.models.models import AnalyticsEvent

logger = logging.getLogger(__name__)


async def track(event_type: str, user_id: int = None, username: str = None,
                details: str = None, cost: float = 0, source: str = "bot"):
    """Track an analytics event."""
    try:
        async with async_session() as db:
            event = AnalyticsEvent(
                event_type=event_type,
                user_id=user_id,
                username=username,
                details=details,
                cost=cost,
                source=source,
            )
            db.add(event)
            await db.commit()
    except Exception as e:
        logger.error(f"Analytics track error: {e}")


async def get_stats(days: int = 1) -> dict:
    """Get analytics stats for the last N days."""
    since = datetime.utcnow() - timedelta(days=days)
    async with async_session() as db:
        # Total events
        total_q = await db.execute(
            select(func.count(AnalyticsEvent.id))
            .where(AnalyticsEvent.created_at >= since)
        )
        total = total_q.scalar() or 0

        # Unique users
        users_q = await db.execute(
            select(func.count(func.distinct(AnalyticsEvent.user_id)))
            .where(AnalyticsEvent.created_at >= since)
            .where(AnalyticsEvent.user_id.isnot(None))
        )
        unique_users = users_q.scalar() or 0

        # Events by type
        by_type_q = await db.execute(
            select(AnalyticsEvent.event_type, func.count(AnalyticsEvent.id))
            .where(AnalyticsEvent.created_at >= since)
            .group_by(AnalyticsEvent.event_type)
            .order_by(func.count(AnalyticsEvent.id).desc())
        )
        by_type = {row[0]: row[1] for row in by_type_q.all()}

        # Total API cost
        cost_q = await db.execute(
            select(func.sum(AnalyticsEvent.cost))
            .where(AnalyticsEvent.created_at >= since)
            .where(AnalyticsEvent.cost > 0)
        )
        total_cost = cost_q.scalar() or 0

        # By source
        by_source_q = await db.execute(
            select(AnalyticsEvent.source, func.count(AnalyticsEvent.id))
            .where(AnalyticsEvent.created_at >= since)
            .group_by(AnalyticsEvent.source)
        )
        by_source = {row[0]: row[1] for row in by_source_q.all()}

        # New users (first /start)
        new_users_q = await db.execute(
            text("""
                SELECT COUNT(*) FROM (
                    SELECT user_id, MIN(created_at) as first_seen
                    FROM analytics_events
                    WHERE event_type = 'start' AND user_id IS NOT NULL
                    GROUP BY user_id
                    HAVING MIN(created_at) >= :since
                ) sub
            """),
            {"since": since}
        )
        new_users = new_users_q.scalar() or 0

        # Top users
        top_users_q = await db.execute(
            select(AnalyticsEvent.username, func.count(AnalyticsEvent.id))
            .where(AnalyticsEvent.created_at >= since)
            .where(AnalyticsEvent.username.isnot(None))
            .group_by(AnalyticsEvent.username)
            .order_by(func.count(AnalyticsEvent.id).desc())
            .limit(5)
        )
        top_users = [(row[0], row[1]) for row in top_users_q.all()]

    return {
        "days": days,
        "total_events": total,
        "unique_users": unique_users,
        "new_users": new_users,
        "by_type": by_type,
        "by_source": by_source,
        "total_cost": total_cost,
        "top_users": top_users,
    }


def format_stats(stats: dict) -> str:
    days = stats["days"]
    period = "за день" if days == 1 else f"за {days} дней" if days < 7 else "за неделю" if days == 7 else f"за {days} дней"

    lines = [f"📊 <b>Аналитика {period}</b>\n"]
    lines.append(f"👥 Уникальных пользователей: <b>{stats['unique_users']}</b>")
    lines.append(f"🆕 Новых: <b>{stats['new_users']}</b>")
    lines.append(f"📈 Всего событий: {stats['total_events']}")
    lines.append(f"💰 Расходы API: <b>${stats['total_cost']:.4f}</b>")

    if stats["by_type"]:
        lines.append("\n<b>По типам:</b>")
        emoji_map = {
            "start": "🚀", "check": "🔗", "addlink": "➕",
            "analyze": "📊", "lead": "📩", "rates": "💰",
            "checklinks": "🔄", "mylinks": "📋", "deletelink": "🗑",
            "report": "📊", "web_check": "🌐", "web_lead": "📩",
        }
        for event_type, count in stats["by_type"].items():
            emoji = emoji_map.get(event_type, "•")
            lines.append(f"  {emoji} {event_type}: {count}")

    if stats["by_source"]:
        lines.append("\n<b>Источники:</b>")
        source_emoji = {"bot": "🤖", "web": "🌐"}
        for source, count in stats["by_source"].items():
            emoji = source_emoji.get(source, "•")
            lines.append(f"  {emoji} {source}: {count}")

    if stats["top_users"]:
        lines.append("\n<b>Топ пользователей:</b>")
        for i, (username, count) in enumerate(stats["top_users"]):
            lines.append(f"  {i+1}. {username}: {count} действий")

    return "\n".join(lines)
