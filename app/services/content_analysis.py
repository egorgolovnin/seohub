"""Deep content analysis of SEO content-makers: history parsing + AI insights."""
import logging
from datetime import datetime
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import AnalysisChannel, ChannelMessage, ChannelAnalysis

logger = logging.getLogger(__name__)

ANALYSIS_SEED = [
    "pavlutskiy", "tkhychs", "MoneyBeatsEvil", "diceseo", "reg2bet", "bakushevaseo",
    "heymoneymaker", "shakinru", "drmaxseo", "SEOBAZA", "itest_ua", "sealytics",
    "altblogru", "seoideas", "bez_seo", "vysokoffru", "mypbn", "seonica", "seofishku",
    "seosekretiki", "seospecialist", "kabinet_seo", "seopraktika", "linkbuilding_ls",
    "seokotenkov", "seofaqt", "seo_inside", "kgayd", "seoantteam", "siteclinic_doctor",
    "sneex_seo", "seonotfound", "affcatalog", "seodreamteamofficial", "seomnenie",
    "advancedseoblog", "seodre",
]


async def seed_analysis_channels(db: AsyncSession):
    existing = {r[0] for r in (await db.execute(select(AnalysisChannel.username))).all()}
    added = 0
    for uname in ANALYSIS_SEED:
        if uname.lower() in {e.lower() for e in existing}:
            continue
        db.add(AnalysisChannel(username=uname, name=uname, is_active=True))
        added += 1
    if added:
        await db.commit()
        logger.info(f"Seeded {added} analysis channels")


async def list_channels(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(select(AnalysisChannel).order_by(AnalysisChannel.username))).scalars().all()
    return [{"id": r.id, "username": r.username, "name": r.name, "is_active": r.is_active,
             "last_parsed": r.last_parsed.strftime("%d.%m %H:%M") if r.last_parsed else None,
             "msg_count": r.msg_count or 0} for r in rows]


async def add_channels(db: AsyncSession, usernames: list[str]) -> int:
    existing = {r[0].lower() for r in (await db.execute(select(AnalysisChannel.username))).all()}
    added = 0
    for u in usernames:
        uname = (u or "").lstrip("@").strip()
        if not uname or uname.lower() in existing:
            continue
        db.add(AnalysisChannel(username=uname, name=uname, is_active=True))
        existing.add(uname.lower())
        added += 1
    if added:
        await db.commit()
    return added


async def remove_channel(db: AsyncSession, channel_id: int) -> bool:
    ch = (await db.execute(select(AnalysisChannel).where(AnalysisChannel.id == channel_id))).scalar_one_or_none()
    if not ch:
        return False
    await db.execute(delete(ChannelMessage).where(ChannelMessage.channel_username == ch.username))
    await db.execute(delete(ChannelAnalysis).where(ChannelAnalysis.channel_username == ch.username))
    await db.delete(ch)
    await db.commit()
    return True


async def parse_channel(db: AsyncSession, username: str, limit: int = 80, days_back: int = 120) -> dict:
    """Fetch a channel's history via Telethon and upsert into channel_messages."""
    from app.services.parser import get_telethon_client, fetch_channel_history
    client = await get_telethon_client()
    if not client:
        return {"ok": False, "error": "telethon not configured"}
    try:
        msgs = await fetch_channel_history(client, username, limit=limit, days_back=days_back)
    finally:
        await client.disconnect()
    if not msgs:
        return {"ok": True, "fetched": 0, "stored": 0}
    uname = msgs[0]["channel_username"]
    title = msgs[0]["channel_name"]
    existing = {r[0] for r in (await db.execute(
        select(ChannelMessage.message_id).where(ChannelMessage.channel_username == uname)
    )).all()}
    stored = 0
    for m in msgs:
        if m["message_id"] in existing:
            # update engagement metrics on re-parse
            await db.execute(
                ChannelMessage.__table__.update()
                .where((ChannelMessage.channel_username == uname) & (ChannelMessage.message_id == m["message_id"]))
                .values(views=m["views"], forwards=m["forwards"], reactions=m["reactions"])
            )
            continue
        db.add(ChannelMessage(
            channel_username=uname, message_id=m["message_id"], date=m["date"],
            text=m["text"], views=m["views"], forwards=m["forwards"],
            reactions=m["reactions"], link=m["link"],
        ))
        stored += 1
    # update channel meta
    ch = (await db.execute(select(AnalysisChannel).where(AnalysisChannel.username == uname))).scalar_one_or_none()
    total = (await db.execute(
        select(func.count(ChannelMessage.id)).where(ChannelMessage.channel_username == uname)
    )).scalar() or 0
    if ch:
        ch.name = title
        ch.last_parsed = datetime.utcnow()
        ch.msg_count = total + stored
    await db.commit()
    return {"ok": True, "channel": uname, "fetched": len(msgs), "stored": stored, "total": total + stored}


async def get_overview(db: AsyncSession) -> dict:
    # per-channel message counts
    rows = (await db.execute(
        select(ChannelMessage.channel_username, func.count(ChannelMessage.id),
               func.coalesce(func.sum(ChannelMessage.views), 0))
        .group_by(ChannelMessage.channel_username)
    )).all()
    channels = sorted(
        [{"username": u, "msgs": c, "total_views": int(v)} for u, c, v in rows],
        key=lambda x: x["msgs"], reverse=True,
    )
    # global top posts by views
    top = (await db.execute(
        select(ChannelMessage).order_by(ChannelMessage.views.desc().nullslast()).limit(25)
    )).scalars().all()
    top_posts = [{
        "channel": t.channel_username, "views": t.views or 0, "forwards": t.forwards or 0,
        "reactions": t.reactions or 0, "link": t.link,
        "preview": (t.text or "")[:140].replace("\n", " "),
        "date": t.date.strftime("%d.%m.%y") if t.date else "",
    } for t in top]
    total_msgs = sum(c["msgs"] for c in channels)
    return {"channels": channels, "top_posts": top_posts,
            "total_msgs": total_msgs, "parsed_channels": len(channels)}


async def analyze_channel(db: AsyncSession, username: str) -> dict:
    from app.services import ai
    uname = (username or "").lstrip("@").strip()
    msgs = (await db.execute(
        select(ChannelMessage).where(ChannelMessage.channel_username == uname)
        .order_by(ChannelMessage.views.desc().nullslast()).limit(100)
    )).scalars().all()
    if not msgs:
        return {"ok": False, "error": "Нет спарсенных сообщений. Сначала запусти парсинг."}
    sample = "\n\n---\n\n".join((m.text or "")[:350] for m in msgs[:80])
    result = await ai.analyze_content(uname, sample)
    if not result:
        return {"ok": False, "error": "AI не вернул результат (проверь ANTHROPIC_API_KEY)"}
    top3 = (await db.execute(
        select(ChannelMessage).where(ChannelMessage.channel_username == uname)
        .order_by(ChannelMessage.views.desc().nullslast()).limit(3)
    )).scalars().all()
    top_posts = [{"link": t.link, "views": t.views or 0, "preview": (t.text or "")[:100].replace("\n", " ")} for t in top3]
    existing = (await db.execute(select(ChannelAnalysis).where(ChannelAnalysis.channel_username == uname))).scalar_one_or_none()
    if existing:
        existing.problems = result.get("problems", "")
        existing.products = result.get("products", "")
        existing.themes = result.get("themes", "")
        existing.top_posts = top_posts
        existing.msg_count = len(msgs)
        existing.analyzed_at = datetime.utcnow()
    else:
        db.add(ChannelAnalysis(
            channel_username=uname, problems=result.get("problems", ""),
            products=result.get("products", ""), themes=result.get("themes", ""),
            top_posts=top_posts, msg_count=len(msgs),
        ))
    await db.commit()
    return {"ok": True, "username": uname, **result, "top_posts": top_posts}


async def get_reports(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(select(ChannelAnalysis).order_by(ChannelAnalysis.analyzed_at.desc()))).scalars().all()
    return [{"username": r.channel_username, "problems": r.problems, "products": r.products,
             "themes": r.themes, "top_posts": r.top_posts or [], "msg_count": r.msg_count,
             "analyzed_at": r.analyzed_at.strftime("%d.%m %H:%M") if r.analyzed_at else ""} for r in rows]
