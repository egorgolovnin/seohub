"""Deep content analysis of SEO content-makers.

Channels are the SAME unified set as the digest (digest_channels). This module
adds full-history parsing + AI insights on top of that single list.
"""
import logging
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import DigestChannel, ChannelMessage, ChannelAnalysis

logger = logging.getLogger(__name__)

# SEO content-maker channels to fold into the unified channel list.
SEO_CHANNELS_SEED = [
    "pavlutskiy", "tkhychs", "MoneyBeatsEvil", "diceseo", "reg2bet", "bakushevaseo",
    "heymoneymaker", "shakinru", "drmaxseo", "SEOBAZA", "itest_ua", "sealytics",
    "altblogru", "seoideas", "bez_seo", "vysokoffru", "mypbn", "seonica", "seofishku",
    "seosekretiki", "seospecialist", "kabinet_seo", "seopraktika", "linkbuilding_ls",
    "seokotenkov", "seofaqt", "seo_inside", "kgayd", "seoantteam", "siteclinic_doctor",
    "sneex_seo", "seonotfound", "affcatalog", "seodreamteamofficial", "seomnenie",
    "advancedseoblog", "seodre",
]


async def seed_seo_channels(db: AsyncSession):
    """Ensure the SEO content-maker channels exist in the unified digest_channels list."""
    existing = {(r[0] or "").lstrip("@").lower() for r in (await db.execute(select(DigestChannel.username))).all()}
    added = 0
    for uname in SEO_CHANNELS_SEED:
        u = uname.lstrip("@")
        if u.lower() in existing:
            continue
        db.add(DigestChannel(channel_id=f"seo_{u}", name=u, username=u, category="seo", is_active=True))
        existing.add(u.lower())
        added += 1
    if added:
        await db.commit()
        logger.info(f"Seeded {added} SEO content-maker channels into digest_channels")


async def _stats_by_channel(db: AsyncSession) -> dict:
    rows = (await db.execute(
        select(ChannelMessage.channel_username, func.count(ChannelMessage.id), func.max(ChannelMessage.date))
        .group_by(ChannelMessage.channel_username)
    )).all()
    return {(u or "").lower(): {"msgs": c, "last": last} for u, c, last in rows}


async def list_channels(db: AsyncSession) -> list[dict]:
    """Analysis targets = active digest channels, enriched with parsed-message stats."""
    chans = (await db.execute(
        select(DigestChannel).where(DigestChannel.is_active == True).order_by(DigestChannel.name)
    )).scalars().all()
    stats = await _stats_by_channel(db)
    out = []
    for r in chans:
        uname = (r.username or "").lstrip("@")
        if not uname:
            continue
        st = stats.get(uname.lower(), {})
        out.append({
            "username": uname, "name": r.name,
            "msg_count": st.get("msgs", 0),
            "last_parsed": st["last"].strftime("%d.%m %H:%M") if st.get("last") else None,
        })
    return out


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
        return {"ok": True, "fetched": 0, "stored": 0, "total": 0}
    uname = msgs[0]["channel_username"]
    existing = {r[0] for r in (await db.execute(
        select(ChannelMessage.message_id).where(ChannelMessage.channel_username == uname)
    )).all()}
    stored = 0
    for m in msgs:
        if m["message_id"] in existing:
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
    await db.commit()
    total = (await db.execute(
        select(func.count(ChannelMessage.id)).where(ChannelMessage.channel_username == uname)
    )).scalar() or 0
    return {"ok": True, "channel": uname, "fetched": len(msgs), "stored": stored, "total": total}


async def get_overview(db: AsyncSession) -> dict:
    rows = (await db.execute(
        select(ChannelMessage.channel_username, func.count(ChannelMessage.id),
               func.coalesce(func.sum(ChannelMessage.views), 0))
        .group_by(ChannelMessage.channel_username)
    )).all()
    channels = sorted(
        [{"username": u, "msgs": c, "total_views": int(v)} for u, c, v in rows],
        key=lambda x: x["msgs"], reverse=True,
    )
    top = (await db.execute(
        select(ChannelMessage).order_by(ChannelMessage.views.desc().nullslast()).limit(25)
    )).scalars().all()
    top_posts = [{
        "channel": t.channel_username, "views": t.views or 0, "forwards": t.forwards or 0,
        "reactions": t.reactions or 0, "link": t.link,
        "preview": (t.text or "")[:140].replace("\n", " "),
        "date": t.date.strftime("%d.%m.%y") if t.date else "",
    } for t in top]
    return {"channels": channels, "top_posts": top_posts,
            "total_msgs": sum(c["msgs"] for c in channels), "parsed_channels": len(channels)}


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
