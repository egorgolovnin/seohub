"""Catalogs: linkbuilding services + SEO channels directory."""
import logging
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.features import LinkbuildingService, SeoChannelCatalog
from app.models.models import DigestChannel

logger = logging.getLogger(__name__)

LB_TYPES = {
    "guest_post": "Гостевые посты",
    "pbn": "PBN / сетки",
    "crowd": "Крауд-маркетинг",
    "outreach": "Outreach",
    "marketplace": "Биржа / маркетплейс",
    "exchange": "Обмен ссылками",
}

CH_CATEGORIES = {
    "seo": "SEO",
    "gambling": "Gambling",
    "traffic": "Трафик",
    "news": "Новости",
    "cases": "Кейсы",
    "tools": "Инструменты",
    "am": "AM / ПП",
}


# ---------- Linkbuilding ----------

async def get_linkbuilding(db: AsyncSession, lb_type: str = None, geo: str = None) -> list[dict]:
    q = select(LinkbuildingService).where(LinkbuildingService.is_active == True)
    if lb_type:
        q = q.where(LinkbuildingService.type == lb_type)
    q = q.order_by(LinkbuildingService.verified.desc(), LinkbuildingService.dr.desc().nullslast())
    result = await db.execute(q)
    rows = result.scalars().all()
    out = []
    for r in rows:
        if geo and r.geos and geo.upper() not in (r.geos or "").upper():
            continue
        out.append({
            "id": r.id, "name": r.name, "type": r.type,
            "type_label": LB_TYPES.get(r.type, r.type),
            "geos": r.geos, "languages": r.languages,
            "dr": r.dr, "traffic": r.traffic, "price_from": r.price_from,
            "contact": r.contact, "url": r.url, "description": r.description,
            "verified": r.verified,
        })
    return out


# ---------- SEO channels (public catalog = live digest channels) ----------

async def get_seo_channels(db: AsyncSession, category: str = None) -> list[dict]:
    q = select(DigestChannel).where(DigestChannel.is_active == True)
    if category:
        q = q.where(DigestChannel.category == category)
    q = q.order_by(DigestChannel.subscribers.desc().nullslast(), DigestChannel.name)
    result = await db.execute(q)
    rows = result.scalars().all()
    out = []
    for r in rows:
        uname = (r.username or "").lstrip("@")
        if not uname:
            continue
        out.append({
            "id": r.id, "name": r.name, "username": uname,
            "url": f"https://t.me/{uname}",
            "category": r.category, "category_label": CH_CATEGORIES.get(r.category, r.category),
            "language": "ru",
            "subscribers": getattr(r, "subscribers", None),
            "description": getattr(r, "description", "") or "",
        })
    return out


# ---------- Seeds (run once on startup if tables empty) ----------

_LB_SEED = [
    # Real iGaming link-building providers (source: AFFCatalog link-building directory).
    # Leads route to our concierge (@bdmseo); detailed metrics filled where publicly known.
    ("AWISEE", "outreach", "US,UK,LatAm,APAC,EU", "en,30+", None, None, None, "@bdmseo", "https://awisee.com", "Агентство с 2014, специализация — gambling/казино/iGaming. Гостевые посты и нишевые вставки, 20+ рынков, 30+ языков. Цена по запросу.", True),
    ("PRPosting", "marketplace", "Global", "en,ru,ua", None, None, None, "@bdmseo", "https://prposting.com", "Биржа гостевых постов: 12000+ площадок, отдельный раздел под казино. Самостоятельный подбор по метрикам.", True),
    ("Editorial.link", "outreach", "US,UK,CA,AT,EU", "en", None, None, 375, "@bdmseo", "https://editorial.link", "Редакционные ссылки через ручной аутрич, Digital PR, HARO. Работают без предоплаты, в т.ч. по iGaming. От $375 за ссылку.", True),
    ("GRIT Leaders", "outreach", "Global", "en", None, None, None, "@bdmseo", "", "Под Gambling и Betting: аутрич, крауд из тематических комьюнити, гостевые и PBN-ссылки.", True),
    ("Rankexplore", "outreach", "BR,UK,DE,ES,IT,NL,PL,PT,US,FR", "en", None, None, 50, "@bdmseo", "", "Ссылки для серых ниш (iGaming, sweeps, nutra). Размещения на главных и вставки в текст. $50-800 за ссылку/год, оплата крипто.", False),
    ("Getlinksnow", "pbn", "Global", "en,multi", None, None, None, "@bdmseo", "", "7+ лет на международных рынках: казино, беттинг, крипто. Сабмиты, крауд, PBN. Аудит сайта при заказе PBN.", False),
    ("BackLinker", "outreach", "20+ стран", "en,9", None, None, None, "@bdmseo", "", "Украинский подрядчик: гостевые, сабмиты, крауд, Quora/Reddit. 9 языков, 5000+ площадок. Оплата картой/Payoneer/PayPal/USDT.", False),
    ("Tier1.shop", "pbn", "Global", "en,ru", None, None, None, "@bdmseo", "", "Ссылки с главных страниц PBN-сети (~4000 сайтов). До 5 внешних ссылок с сайта.", False),
    ("Bazoom", "marketplace", "Global", "en", None, None, None, "@bdmseo", "https://bazoom.com", "Self-serve платформа линкбилдинга: сам управляешь размещениями, гемблинг среди вертикалей.", False),
    ("Goblin Links", "outreach", "Global", "en", None, None, None, "@bdmseo", "", "", False),
    ("WhenIpost", "outreach", "Global", "en", None, None, None, "@bdmseo", "", "", False),
    ("Link Masters", "outreach", "Global", "en,ru", None, None, None, "@bdmseo", "", "", False),
    ("Trust1ink", "outreach", "Global", "en,ru", None, None, None, "@bdmseo", "", "", False),
    ("Soogle", "outreach", "Global", "en,ru", None, None, None, "@bdmseo", "", "", False),
    ("Shared Domains", "pbn", "Global", "en", None, None, None, "@bdmseo", "", "", False),
    ("Weblinks Agency", "outreach", "Global", "en", None, None, None, "@bdmseo", "", "", False),
    ("Mellow Promo", "outreach", "Global", "en,ru", None, None, None, "@bdmseo", "", "", False),
    ("BlackhatSEO", "crowd", "Global", "en,ru", None, None, None, "@bdmseo", "", "", False),
    ("TopLinks", "outreach", "Global", "en,ru", None, None, None, "@bdmseo", "", "", False),
    ("LinkyWay Team", "outreach", "Global", "en,ru", None, None, None, "@bdmseo", "", "", False),
    ("BootyBoost", "outreach", "Global", "en", None, None, None, "@bdmseo", "", "", False),
    ("BuyLink", "marketplace", "Global", "en,ru", None, None, None, "@bdmseo", "", "", False),
    ("WMLinks", "outreach", "Global", "en,ru", None, None, None, "@bdmseo", "", "", False),
    ("PR-X Links", "outreach", "Global", "en,ru", None, None, None, "@bdmseo", "", "", False),
    ("GoSeoLinks", "outreach", "Global", "en,ru", None, None, None, "@bdmseo", "", "", False),
    ("Cryptoboost", "outreach", "Global", "en", None, None, None, "@bdmseo", "", "Линкбилдинг с акцентом на crypto/iGaming.", False),
    ("A_LinksContent", "outreach", "Global", "en,ru", None, None, None, "@bdmseo", "", "", False),
    ("Natural Links", "outreach", "Global", "en,ru", None, None, None, "@bdmseo", "", "", False),
    ("Juicify", "outreach", "Global", "en", None, None, None, "@bdmseo", "", "", False),
    ("DataParsed", "outreach", "Global", "en,ru", None, None, None, "@bdmseo", "", "", False),
    ("Victoria's Links", "outreach", "Global", "en,ru", None, None, None, "@bdmseo", "", "", False),
    ("Get Rankly", "outreach", "Global", "en", None, None, None, "@bdmseo", "", "", False),
    ("Zhenia Krasnov", "outreach", "Global", "en,ru", None, None, None, "@bdmseo", "", "", False),
    ("Качественное SEO", "outreach", "RU,CIS", "ru", None, None, None, "@bdmseo", "", "", False),
]

_CH_SEED = [
    ("Gambling SEO", "gamblingseo", "seo", "ru", 14000, "Кейсы и обсуждения SEO в гемблинге."),
    ("Affiliate Valley", "affiliatevalley", "am", "ru", 22000, "Новости арбитража и партнёрских программ."),
    ("Black Traffic", "blacktraffic", "traffic", "ru", 18000, "Серый и чёрный трафик, связки, кейсы."),
    ("SEO для бизнеса", "seopro", "seo", "ru", 31000, "Белое SEO, алгоритмы Google, аналитика."),
    ("Casino Affiliate News", "casinoaffnews", "news", "en", 9000, "Новости gambling-индустрии и регуляций."),
    ("PBN & Links", "pbnlinks", "tools", "ru", 7500, "Линкбилдинг, сетки сайтов, индексация."),
    ("Партнёрки и офферы", "ppoffers", "am", "ru", 26000, "Свежие офферы, ставки CPA/RevShare по ГЕО."),
    ("SEO Cases", "seocases", "cases", "ru", 11000, "Разборы реальных кейсов продвижения."),
]


async def seed_catalogs(db: AsyncSession):
    # --- Schema migrations (idempotent) ---
    from sqlalchemy import text
    try:
        await db.execute(text("ALTER TABLE digest_channels ADD COLUMN IF NOT EXISTS description TEXT"))
        await db.execute(text("ALTER TABLE digest_channels ADD COLUMN IF NOT EXISTS subscribers INTEGER"))
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.warning(f"digest_channels migration skipped: {e}")

    # Migrate any legacy contact handle to current one (idempotent)
    try:
        from sqlalchemy import update
        await db.execute(
            update(LinkbuildingService)
            .where(LinkbuildingService.contact == "@seohub_lb")
            .values(contact="@bdmseo")
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.warning(f"Contact migration skipped: {e}")

    # Remove legacy placeholder/fake linkbuilding rows (one-time cleanup)
    try:
        from sqlalchemy import delete
        _FAKE = ["Tier-1 Guest Posts", "Casino PBN Network", "Crowd Boost", "Outreach Pro",
                 "LinkMarket iGaming", "Link Swap Club", "EU Casino Editorials",
                 "LatAm Traffic Links", "Asia Tier Network", "Sports Niche Outreach"]
        await db.execute(delete(LinkbuildingService).where(LinkbuildingService.name.in_(_FAKE)))
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.warning(f"Fake LB cleanup skipped: {e}")

    # Linkbuilding
    cnt = (await db.execute(select(func.count(LinkbuildingService.id)))).scalar() or 0
    if cnt == 0:
        for name, typ, geos, langs, dr, traffic, price, contact, url, desc, verified in _LB_SEED:
            db.add(LinkbuildingService(
                name=name, type=typ, geos=geos, languages=langs, dr=dr,
                traffic=traffic, price_from=price, contact=contact, url=url,
                description=desc, verified=verified, is_active=True,
            ))
        await db.commit()
        logger.info(f"Seeded {len(_LB_SEED)} linkbuilding services")
    # NOTE: SEO channels catalog now sources directly from active digest_channels
    #       (see get_seo_channels), so no separate seeding here.
