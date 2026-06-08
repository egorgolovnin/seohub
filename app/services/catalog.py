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


# ---------- SEO channels ----------

async def get_seo_channels(db: AsyncSession, category: str = None) -> list[dict]:
    q = select(SeoChannelCatalog).where(SeoChannelCatalog.is_active == True)
    if category:
        q = q.where(SeoChannelCatalog.category == category)
    q = q.order_by(SeoChannelCatalog.subscribers.desc().nullslast())
    result = await db.execute(q)
    rows = result.scalars().all()
    return [
        {
            "id": r.id, "name": r.name, "username": r.username,
            "url": r.url or (f"https://t.me/{r.username}" if r.username else ""),
            "category": r.category, "category_label": CH_CATEGORIES.get(r.category, r.category),
            "language": r.language, "subscribers": r.subscribers,
            "description": r.description,
        }
        for r in rows
    ]


# ---------- Seeds (run once on startup if tables empty) ----------

_LB_SEED = [
    ("Tier-1 Guest Posts", "guest_post", "DE,UK,FR,IT,ES,US,CA", "en,de,fr,it,es", 55, 80000, 120, "@bdmseo", "", "Размещение на тематических Tier-1 сайтах казино/беттинг ниши. Белые анкоры, dofollow, индексация в течение 30 дней.", True),
    ("Casino PBN Network", "pbn", "RU,UA,KZ,UZ,TR,BR", "ru,en,tr,pt", 35, 15000, 45, "@bdmseo", "", "Приватная сетка из 200+ доменов под gambling. Полный контроль анкоров, разные ASN/IP, очищенные домены с историей.", True),
    ("Crowd Boost", "crowd", "ALL", "ru,en", 0, 0, 15, "@bdmseo", "", "Крауд-маркетинг: форумы, комментарии, Q&A. Естественный ссылочный профиль и трафиковые упоминания бренда.", False),
    ("Outreach Pro", "outreach", "UK,US,CA,AU,DE,NL", "en,de", 50, 120000, 200, "@bdmseo", "", "Ручной аутрич к реальным сайтам. Согласование анкоров и контента под ваш бренд, переговоры о цене напрямую с вебмастерами.", True),
    ("LinkMarket iGaming", "marketplace", "DE,ES,IT,FR,PL,PT,GR", "en,de,es,it", 42, 40000, 60, "@bdmseo", "", "Биржа площадок под iGaming с фильтром по DR, трафику, ГЕО и языку. Прозрачные метрики Ahrefs/Semrush.", False),
    ("Link Swap Club", "exchange", "ALL", "ru,en", 30, 25000, 0, "@bdmseo", "", "Обмен ссылками между проверенными SEO-командами. Трёхсторонние схемы (A→B→C→A), модерация качества.", False),
    ("EU Casino Editorials", "guest_post", "DE,AT,CH,NL,BE", "de,nl", 48, 60000, 150, "@bdmseo", "", "Редакционные статьи на немецкоязычных площадках. Высокий траст, подходит под YMYL-тематику.", True),
    ("LatAm Traffic Links", "outreach", "BR,MX,CL,CO,AR,PE", "pt,es", 38, 90000, 70, "@bdmseo", "", "Аутрич по латиноамериканскому рынку. Локальные новостники и спортивные порталы.", False),
    ("Asia Tier Network", "pbn", "IN,BD,TH,JP,KR,PH", "en", 32, 30000, 40, "@bdmseo", "", "Сетка под азиатские ГЕО. Особенно сильно по IN/BD беттингу.", False),
    ("Sports Niche Outreach", "outreach", "UK,US,DE,IT,ES,BR", "en,de,it,es,pt", 52, 150000, 180, "@bdmseo", "", "Спортивные и беттинговые порталы. Идеально под прематч/лайв-ставки.", True),
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
        logger.warning(f"Contact migration skipped: {e}")

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

    # SEO channels: curated + pull active digest channels
    cnt = (await db.execute(select(func.count(SeoChannelCatalog.id)))).scalar() or 0
    if cnt == 0:
        seen = set()
        for name, username, cat, lang, subs, desc in _CH_SEED:
            seen.add(username.lower())
            db.add(SeoChannelCatalog(
                name=name, username=username, url=f"https://t.me/{username}",
                category=cat, language=lang, subscribers=subs, description=desc, is_active=True,
            ))
        # import active digest channels not already present
        dch = (await db.execute(
            select(DigestChannel).where(DigestChannel.is_active == True)
        )).scalars().all()
        for ch in dch:
            uname = (ch.username or "").lstrip("@").lower()
            if not uname or uname in seen:
                continue
            seen.add(uname)
            db.add(SeoChannelCatalog(
                name=ch.name, username=uname, url=f"https://t.me/{uname}",
                category=ch.category or "seo", language="ru", subscribers=None,
                description="", is_active=True,
            ))
        await db.commit()
        logger.info("Seeded SEO channels catalog")
