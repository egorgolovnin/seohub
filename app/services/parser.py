import logging
from datetime import datetime, timedelta
from telethon import TelegramClient
from telethon.sessions import StringSession
from app.config import get_settings

logger = logging.getLogger(__name__)


async def get_telethon_client() -> TelegramClient | None:
    settings = get_settings()
    if not settings.telethon_api_id or not settings.telethon_session_string:
        logger.warning("Telethon not configured")
        return None
    client = TelegramClient(
        StringSession(settings.telethon_session_string),
        settings.telethon_api_id,
        settings.telethon_api_hash,
    )
    await client.connect()
    if not await client.is_user_authorized():
        logger.error("Telethon session not authorized")
        return None
    return client


async def fetch_channel_posts(
    client: TelegramClient,
    channel_username: str,
    hours_back: int = 24,
    limit: int = 50,
) -> list[dict]:
    posts = []
    try:
        entity = await client.get_entity(channel_username)
        since = datetime.utcnow() - timedelta(hours=hours_back)
        async for message in client.iter_messages(entity, limit=limit, offset_date=None):
            if message.date.replace(tzinfo=None) < since:
                break
            if not message.text or len(message.text) < 30:
                continue
            posts.append({
                "channel_name": getattr(entity, "title", channel_username),
                "channel_username": channel_username,
                "text": message.text,
                "date": message.date.replace(tzinfo=None),
                "message_id": message.id,
            })
    except Exception as e:
        logger.error(f"Error fetching {channel_username}: {e}")
    return posts


async def fetch_all_channels(channels: list[dict], hours_back: int = 24) -> list[dict]:
    client = await get_telethon_client()
    if not client:
        return []
    all_posts = []
    try:
        for ch in channels:
            username = ch.get("username", "")
            if not username:
                continue
            posts = await fetch_channel_posts(client, username, hours_back)
            all_posts.extend(posts)
            logger.info(f"Fetched {len(posts)} posts from {username}")
    finally:
        await client.disconnect()
    return all_posts


async def check_channels_resolve(usernames: list[str]) -> dict:
    """Resolve each username via Telethon. Returns {username: (ok: bool, info: str)}."""
    out = {}
    client = await get_telethon_client()
    if not client:
        return {u: (False, "telethon not configured") for u in usernames}
    try:
        for u in usernames:
            uname = (u or "").lstrip("@").strip()
            if not uname:
                out[u] = (False, "empty username")
                continue
            try:
                entity = await client.get_entity(uname)
                title = getattr(entity, "title", uname)
                out[u] = (True, title)
            except Exception as e:
                out[u] = (False, type(e).__name__)
    finally:
        await client.disconnect()
    return out


async def fetch_channel_history(client, username: str, limit: int = 80, days_back: int = 120) -> list[dict]:
    """Fetch recent history of a channel with engagement metrics."""
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    uname = (username or "").lstrip("@").strip()
    out = []
    try:
        entity = await client.get_entity(uname)
        title = getattr(entity, "title", uname)
        async for m in client.iter_messages(entity, limit=limit):
            if m.date and m.date < cutoff:
                break
            text = (m.message or "").strip()
            if not text:
                continue
            reactions = 0
            if getattr(m, "reactions", None) and getattr(m.reactions, "results", None):
                reactions = sum((r.count or 0) for r in m.reactions.results)
            out.append({
                "channel_username": uname,
                "channel_name": title,
                "message_id": m.id,
                "date": m.date.replace(tzinfo=None) if m.date else None,
                "text": text,
                "views": int(getattr(m, "views", 0) or 0),
                "forwards": int(getattr(m, "forwards", 0) or 0),
                "reactions": reactions,
                "link": f"https://t.me/{uname}/{m.id}",
            })
    except Exception as e:
        logger.error(f"History fetch failed for {uname}: {e}")
        return []
    return out
