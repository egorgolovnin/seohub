import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from aiogram.types import Update
from app.config import get_settings
from app.database import async_session, init_db
from app.api.routes import router as api_router
from app.bot.main import get_bot, create_dispatcher
from app.services.rates import get_cpa_rates
from app.services.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory="app/templates")
dp = create_dispatcher()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Seed catalogs (linkbuilding + SEO channels) if empty
    try:
        from app.services.catalog import seed_catalogs
        async with async_session() as db:
            await seed_catalogs(db)
            from app.services.content_analysis import seed_seo_channels
            await seed_seo_channels(db)
    except Exception as e:
        logger.error(f"Catalog seed failed: {e}")
    bot = get_bot()
    settings = get_settings()

    # Register bot commands menu
    from aiogram.types import BotCommand
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="rates", description="Ставки по ГЕО (DE, Германия...)"),
        BotCommand(command="cpa", description="Все CPA ставки"),
        BotCommand(command="check", description="Проверка ссылки — цепочка редиректов"),
        BotCommand(command="linkbuilding", description="Каталог линкбилдинга"),
        BotCommand(command="channels", description="Каталог SEO-каналов"),
        BotCommand(command="addlink", description="Добавить ссылку на мониторинг"),
        BotCommand(command="mylinks", description="Мои ссылки"),
        BotCommand(command="deletelink", description="Удалить ссылку"),
        BotCommand(command="report", description="Сводка по всем ссылкам"),
        BotCommand(command="analyze", description="Антишейв — скриншот или текст из ПП"),
        BotCommand(command="stats", description="📊 Аналитика (админ)"),
        BotCommand(command="help", description="Помощь"),
    ])

    # Set webhook for Railway (or use polling for dev)
    if settings.app_env == "production":
        # Webhook mode
        webhook_url = f"https://seohub-production.up.railway.app/webhook"
        await bot.set_webhook(webhook_url)
        logger.info(f"Webhook set: {webhook_url}")
    else:
        # Polling mode for local dev
        asyncio.create_task(dp.start_polling(bot))
        logger.info("Bot polling started")

    start_scheduler()
    yield

    if settings.app_env == "production":
        await bot.delete_webhook()
    await bot.session.close()


app = FastAPI(title="SEOhub", lifespan=lifespan)
app.include_router(api_router)


@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    bot = get_bot()
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
async def home():
    with open("app/templates/index.html", "r") as f:
        return HTMLResponse(f.read())


@app.get("/check", response_class=HTMLResponse)
async def check_page():
    with open("app/templates/check.html", "r") as f:
        return HTMLResponse(f.read())


@app.get("/rates", response_class=HTMLResponse)
async def rates_page(request: Request):
    async with async_session() as db:
        cpa = await get_cpa_rates(db)
    return templates.TemplateResponse(name="rates.html", request=request, context={
        "request": request,
        "cpa_rates": cpa,
        "total_geos": len(cpa),
    })


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    with open("app/templates/admin.html", "r") as f:
        return HTMLResponse(f.read())


@app.post("/api/admin/login")
async def admin_login(request: Request):
    import hashlib
    data = await request.json()
    settings = get_settings()
    if data.get("login") == settings.admin_login and data.get("password") == settings.admin_password:
        token = hashlib.sha256(f"{settings.admin_login}:{settings.admin_password}".encode()).hexdigest()[:32]
        return {"ok": True, "token": token}
    return {"ok": False}


def _check_admin_token(token: str) -> bool:
    import hashlib
    settings = get_settings()
    expected = hashlib.sha256(f"{settings.admin_login}:{settings.admin_password}".encode()).hexdigest()[:32]
    return token == expected


@app.get("/api/admin/stats")
async def admin_stats(days: int = 1, token: str = ""):
    if not _check_admin_token(token):
        return {"ok": False, "error": "unauthorized"}
    from app.services.analytics import get_stats
    stats = await get_stats(days)
    return {"ok": True, "stats": stats}


@app.get("/api/admin/events")
async def admin_events(days: int = 1, token: str = "", limit: int = 50):
    if not _check_admin_token(token):
        return {"ok": False, "error": "unauthorized"}
    from datetime import datetime, timedelta
    from sqlalchemy import select
    from app.models.models import AnalyticsEvent
    since = datetime.utcnow() - timedelta(days=days)
    async with async_session() as db:
        result = await db.execute(
            select(AnalyticsEvent)
            .where(AnalyticsEvent.created_at >= since)
            .order_by(AnalyticsEvent.created_at.desc())
            .limit(limit)
        )
        events = result.scalars().all()
    return {
        "ok": True,
        "events": [
            {
                "time": e.created_at.strftime("%d.%m %H:%M") if e.created_at else "",
                "type": e.event_type,
                "username": e.username,
                "details": e.details,
                "cost": e.cost,
                "source": e.source,
            }
            for e in events
        ]
    }


@app.get("/api/admin/rates")
async def admin_get_rates(token: str = ""):
    if not _check_admin_token(token):
        return {"ok": False}
    from app.models.models import GeoRateCPA
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(select(GeoRateCPA).order_by(GeoRateCPA.avg_cpa.desc()))
        rows = result.scalars().all()
    return {
        "ok": True,
        "rates": [
            {"id": r.id, "geo": r.geo, "min": r.min_cpa, "avg": r.avg_cpa, "max": r.max_cpa}
            for r in rows
        ]
    }


@app.put("/api/admin/rates/{rate_id}")
async def admin_update_rate(rate_id: int, request: Request):
    data = await request.json()
    if not _check_admin_token(data.get("token", "")):
        return {"ok": False}
    from app.models.models import GeoRateCPA
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(select(GeoRateCPA).where(GeoRateCPA.id == rate_id))
        rate = result.scalar_one_or_none()
        if not rate:
            return {"ok": False, "error": "not found"}
        if "geo" in data:
            rate.geo = data["geo"].upper()
        if "min" in data:
            rate.min_cpa = float(data["min"])
        if "avg" in data:
            rate.avg_cpa = float(data["avg"])
        if "max" in data:
            rate.max_cpa = float(data["max"])
        await db.commit()
    return {"ok": True}


@app.post("/api/admin/rates")
async def admin_add_rate(request: Request):
    data = await request.json()
    if not _check_admin_token(data.get("token", "")):
        return {"ok": False}
    from app.models.models import GeoRateCPA
    async with async_session() as db:
        rate = GeoRateCPA(
            geo=data["geo"].upper(),
            min_cpa=float(data["min"]),
            avg_cpa=float(data["avg"]),
            max_cpa=float(data["max"]),
            data_points=1,
            sources="admin",
            programs="",
        )
        db.add(rate)
        await db.commit()
        await db.refresh(rate)
    return {"ok": True, "id": rate.id}


@app.delete("/api/admin/rates/{rate_id}")
async def admin_delete_rate(rate_id: int, token: str = ""):
    if not _check_admin_token(token):
        return {"ok": False}
    from app.models.models import GeoRateCPA
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(select(GeoRateCPA).where(GeoRateCPA.id == rate_id))
        rate = result.scalar_one_or_none()
        if not rate:
            return {"ok": False, "error": "not found"}
        await db.delete(rate)
        await db.commit()
    return {"ok": True}


# ============ ADMIN: Linkbuilding catalog ============

@app.get("/api/admin/linkbuilding")
async def admin_get_lb(token: str = ""):
    if not _check_admin_token(token):
        return {"ok": False}
    from app.models.features import LinkbuildingService
    from sqlalchemy import select
    async with async_session() as db:
        rows = (await db.execute(
            select(LinkbuildingService).order_by(LinkbuildingService.id.desc())
        )).scalars().all()
    return {"ok": True, "items": [
        {"id": r.id, "name": r.name, "type": r.type, "geos": r.geos,
         "languages": r.languages, "dr": r.dr, "traffic": r.traffic,
         "price_from": r.price_from, "contact": r.contact, "url": r.url,
         "description": r.description, "verified": r.verified, "is_active": r.is_active}
        for r in rows
    ]}


@app.post("/api/admin/linkbuilding")
async def admin_add_lb(request: Request):
    data = await request.json()
    if not _check_admin_token(data.get("token", "")):
        return {"ok": False}
    from app.models.features import LinkbuildingService
    def _i(v):
        try: return int(v)
        except: return None
    def _f(v):
        try: return float(v)
        except: return None
    async with async_session() as db:
        item = LinkbuildingService(
            name=data.get("name", "").strip(), type=data.get("type", "guest_post"),
            geos=data.get("geos", ""), languages=data.get("languages", ""),
            dr=_i(data.get("dr")), traffic=_i(data.get("traffic")),
            price_from=_f(data.get("price_from")), contact=data.get("contact", ""),
            url=data.get("url", ""), description=data.get("description", ""),
            verified=bool(data.get("verified", False)), is_active=True,
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)
    return {"ok": True, "id": item.id}


@app.put("/api/admin/linkbuilding/{item_id}")
async def admin_update_lb(item_id: int, request: Request):
    data = await request.json()
    if not _check_admin_token(data.get("token", "")):
        return {"ok": False}
    from app.models.features import LinkbuildingService
    from sqlalchemy import select
    async with async_session() as db:
        item = (await db.execute(select(LinkbuildingService).where(LinkbuildingService.id == item_id))).scalar_one_or_none()
        if not item:
            return {"ok": False, "error": "not found"}
        for f in ("name", "type", "geos", "languages", "contact", "url", "description"):
            if f in data: setattr(item, f, data[f])
        if "dr" in data:
            try: item.dr = int(data["dr"])
            except: pass
        if "traffic" in data:
            try: item.traffic = int(data["traffic"])
            except: pass
        if "price_from" in data:
            try: item.price_from = float(data["price_from"])
            except: pass
        if "verified" in data: item.verified = bool(data["verified"])
        if "is_active" in data: item.is_active = bool(data["is_active"])
        await db.commit()
    return {"ok": True}


@app.delete("/api/admin/linkbuilding/{item_id}")
async def admin_delete_lb(item_id: int, token: str = ""):
    if not _check_admin_token(token):
        return {"ok": False}
    from app.models.features import LinkbuildingService
    from sqlalchemy import select
    async with async_session() as db:
        item = (await db.execute(select(LinkbuildingService).where(LinkbuildingService.id == item_id))).scalar_one_or_none()
        if not item:
            return {"ok": False, "error": "not found"}
        await db.delete(item)
        await db.commit()
    return {"ok": True}


# ============ ADMIN: SEO channels catalog ============

@app.get("/api/admin/channels")
async def admin_get_channels(token: str = ""):
    if not _check_admin_token(token):
        return {"ok": False}
    from app.models.features import SeoChannelCatalog
    from sqlalchemy import select
    async with async_session() as db:
        rows = (await db.execute(
            select(SeoChannelCatalog).order_by(SeoChannelCatalog.id.desc())
        )).scalars().all()
    return {"ok": True, "items": [
        {"id": r.id, "name": r.name, "username": r.username, "url": r.url,
         "category": r.category, "language": r.language, "subscribers": r.subscribers,
         "description": r.description, "is_active": r.is_active}
        for r in rows
    ]}


@app.post("/api/admin/channels")
async def admin_add_channel(request: Request):
    data = await request.json()
    if not _check_admin_token(data.get("token", "")):
        return {"ok": False}
    from app.models.features import SeoChannelCatalog
    uname = (data.get("username", "") or "").lstrip("@").strip()
    def _i(v):
        try: return int(v)
        except: return None
    async with async_session() as db:
        item = SeoChannelCatalog(
            name=data.get("name", "").strip(), username=uname,
            url=data.get("url", "") or (f"https://t.me/{uname}" if uname else ""),
            category=data.get("category", "seo"), language=data.get("language", "ru"),
            subscribers=_i(data.get("subscribers")), description=data.get("description", ""),
            is_active=True,
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)
    return {"ok": True, "id": item.id}


@app.put("/api/admin/channels/{item_id}")
async def admin_update_channel(item_id: int, request: Request):
    data = await request.json()
    if not _check_admin_token(data.get("token", "")):
        return {"ok": False}
    from app.models.features import SeoChannelCatalog
    from sqlalchemy import select
    async with async_session() as db:
        item = (await db.execute(select(SeoChannelCatalog).where(SeoChannelCatalog.id == item_id))).scalar_one_or_none()
        if not item:
            return {"ok": False, "error": "not found"}
        for f in ("name", "category", "language", "description", "url"):
            if f in data: setattr(item, f, data[f])
        if "username" in data:
            item.username = (data["username"] or "").lstrip("@").strip()
        if "subscribers" in data:
            try: item.subscribers = int(data["subscribers"])
            except: pass
        if "is_active" in data: item.is_active = bool(data["is_active"])
        await db.commit()
    return {"ok": True}


@app.delete("/api/admin/channels/{item_id}")
async def admin_delete_channel(item_id: int, token: str = ""):
    if not _check_admin_token(token):
        return {"ok": False}
    from app.models.features import SeoChannelCatalog
    from sqlalchemy import select
    async with async_session() as db:
        item = (await db.execute(select(SeoChannelCatalog).where(SeoChannelCatalog.id == item_id))).scalar_one_or_none()
        if not item:
            return {"ok": False, "error": "not found"}
        await db.delete(item)
        await db.commit()
    return {"ok": True}


# ============ ADMIN: Weekly digest (post selection) ============

@app.get("/api/admin/weekly/posts")
async def admin_weekly_posts(token: str = ""):
    if not _check_admin_token(token):
        return {"ok": False}
    from app.services.digest import get_week_posts, _source_link
    async with async_session() as db:
        posts = await get_week_posts(db)
    return {"ok": True, "posts": [
        {"id": p.id, "summary": p.summary or (p.original_text or "")[:120],
         "category": p.category, "score": p.importance_score,
         "channel": p.channel_name or p.channel_username,
         "source": _source_link(p),
         "published_at": p.published_at.strftime("%d.%m %H:%M") if p.published_at else ""}
        for p in posts
    ]}


@app.post("/api/admin/weekly/generate")
async def admin_weekly_generate(request: Request):
    data = await request.json()
    if not _check_admin_token(data.get("token", "")):
        return {"ok": False}
    post_ids = [int(x) for x in data.get("post_ids", [])]
    if not post_ids:
        return {"ok": False, "error": "Не выбрано ни одного поста"}
    from app.services.digest import get_posts_by_ids, save_weekly_digest, format_weekly_digest, pick_weekly_intro
    async with async_session() as db:
        posts = await get_posts_by_ids(db, post_ids)
        if not posts:
            return {"ok": False, "error": "Посты не найдены"}
        summary = pick_weekly_intro()
        weekly = await save_weekly_digest(db, summary, [p.id for p in posts])
        preview = format_weekly_digest(summary, posts)
    return {"ok": True, "weekly_id": weekly.id, "summary": summary, "preview": preview}


@app.post("/api/admin/weekly/publish")
async def admin_weekly_publish(request: Request):
    data = await request.json()
    if not _check_admin_token(data.get("token", "")):
        return {"ok": False}
    weekly_id = int(data.get("weekly_id", 0))
    from app.services.digest import get_weekly_by_id, get_posts_by_ids, format_weekly_digest, mark_weekly_published
    from app.bot.main import get_bot
    from aiogram.enums import ParseMode
    settings = get_settings()
    async with async_session() as db:
        weekly = await get_weekly_by_id(db, weekly_id)
        if not weekly:
            return {"ok": False, "error": "not found"}
        posts = await get_posts_by_ids(db, weekly.post_ids or [])
        text = format_weekly_digest(weekly.summary, posts)
        if settings.channel_id:
            b = get_bot()
            await b.send_message(settings.channel_id, text, parse_mode=ParseMode.HTML)
        await mark_weekly_published(db, weekly_id)
    return {"ok": True}


# ============ ADMIN: Digest channels management ============

@app.get("/api/admin/digest-channels")
async def admin_get_digest_channels(token: str = ""):
    if not _check_admin_token(token):
        return {"ok": False}
    from app.models.models import DigestChannel, DigestPost
    from sqlalchemy import select, func
    async with async_session() as db:
        rows = (await db.execute(select(DigestChannel).order_by(DigestChannel.is_active.desc(), DigestChannel.id))).scalars().all()
        # post counts per channel username
        counts = {}
        cres = await db.execute(
            select(DigestPost.channel_username, func.count(DigestPost.id)).group_by(DigestPost.channel_username)
        )
        for uname, c in cres.all():
            counts[(uname or "").lstrip("@").lower()] = c
    items = []
    for r in rows:
        key = (r.username or "").lstrip("@").lower()
        items.append({
            "id": r.id, "name": r.name, "username": (r.username or "").lstrip("@"),
            "category": r.category, "is_active": r.is_active,
            "posts": counts.get(key, 0),
            "description": getattr(r, "description", "") or "",
            "subscribers": getattr(r, "subscribers", None),
        })
    return {"ok": True, "items": items, "active": sum(1 for r in rows if r.is_active), "total": len(rows)}


@app.post("/api/admin/digest-channels/health")
async def admin_digest_channels_health(request: Request):
    data = await request.json()
    if not _check_admin_token(data.get("token", "")):
        return {"ok": False}
    deactivate = bool(data.get("deactivate", True))
    from app.models.models import DigestChannel
    from sqlalchemy import select
    from app.services.parser import check_channels_resolve
    async with async_session() as db:
        rows = (await db.execute(select(DigestChannel).where(DigestChannel.is_active == True))).scalars().all()
        usernames = [(r.username or "").lstrip("@") for r in rows]
        results = await check_channels_resolve(usernames)
        broken, ok = [], []
        by_uname = {(r.username or "").lstrip("@"): r for r in rows}
        for uname, (good, info) in results.items():
            if good:
                ok.append({"username": uname, "title": info})
            else:
                broken.append({"username": uname, "error": info,
                               "name": by_uname[uname].name if uname in by_uname else uname})
                if deactivate and uname in by_uname:
                    by_uname[uname].is_active = False
        if deactivate and broken:
            await db.commit()
    return {"ok": True, "checked": len(usernames), "ok_count": len(ok),
            "broken_count": len(broken), "broken": broken, "deactivated": deactivate}


@app.post("/api/admin/digest-channels")
async def admin_add_digest_channel(request: Request):
    data = await request.json()
    if not _check_admin_token(data.get("token", "")):
        return {"ok": False}
    from app.models.models import DigestChannel
    from sqlalchemy import select, func
    uname = (data.get("username", "") or "").lstrip("@").strip()
    name = (data.get("name", "") or uname).strip()
    cat = data.get("category", "seo")
    desc = data.get("description", "") or ""
    def _i(v):
        try: return int(v)
        except: return None
    subs = _i(data.get("subscribers"))
    if not uname:
        return {"ok": False, "error": "username обязателен"}
    async with async_session() as db:
        exists = (await db.execute(select(DigestChannel).where(DigestChannel.username == uname))).scalar_one_or_none()
        if exists:
            exists.is_active = True
            if name: exists.name = name
            exists.category = cat
            if desc: exists.description = desc
            if subs is not None: exists.subscribers = subs
            await db.commit()
            return {"ok": True, "id": exists.id, "reactivated": True}
        maxid = (await db.execute(select(func.max(DigestChannel.id)))).scalar() or 0
        ch = DigestChannel(channel_id=str(maxid + 1000), name=name, username=uname,
                           category=cat, description=desc, subscribers=subs, is_active=True)
        db.add(ch)
        await db.commit()
        await db.refresh(ch)
    return {"ok": True, "id": ch.id}


@app.put("/api/admin/digest-channels/{item_id}")
async def admin_update_digest_channel(item_id: int, request: Request):
    data = await request.json()
    if not _check_admin_token(data.get("token", "")):
        return {"ok": False}
    from app.models.models import DigestChannel
    from sqlalchemy import select
    async with async_session() as db:
        item = (await db.execute(select(DigestChannel).where(DigestChannel.id == item_id))).scalar_one_or_none()
        if not item:
            return {"ok": False, "error": "not found"}
        if "name" in data: item.name = data["name"]
        if "category" in data: item.category = data["category"]
        if "username" in data: item.username = (data["username"] or "").lstrip("@").strip()
        if "description" in data: item.description = data["description"]
        if "subscribers" in data:
            try: item.subscribers = int(data["subscribers"])
            except: pass
        if "is_active" in data: item.is_active = bool(data["is_active"])
        await db.commit()
    return {"ok": True}


@app.delete("/api/admin/digest-channels/{item_id}")
async def admin_delete_digest_channel(item_id: int, token: str = ""):
    if not _check_admin_token(token):
        return {"ok": False}
    from app.models.models import DigestChannel
    from sqlalchemy import select
    async with async_session() as db:
        item = (await db.execute(select(DigestChannel).where(DigestChannel.id == item_id))).scalar_one_or_none()
        if not item:
            return {"ok": False, "error": "not found"}
        await db.delete(item)
        await db.commit()
    return {"ok": True}


# ============ ADMIN: Content analysis ============

@app.get("/api/admin/analysis/channels")
async def admin_analysis_channels(token: str = ""):
    if not _check_admin_token(token):
        return {"ok": False}
    from app.services.content_analysis import list_channels
    async with async_session() as db:
        items = await list_channels(db)
    return {"ok": True, "items": items}


@app.post("/api/admin/analysis/parse")
async def admin_analysis_parse(request: Request):
    data = await request.json()
    if not _check_admin_token(data.get("token", "")):
        return {"ok": False}
    username = (data.get("username", "") or "").lstrip("@").strip()
    if not username:
        return {"ok": False, "error": "username required (parse one channel per call)"}
    from app.services.content_analysis import parse_channel
    async with async_session() as db:
        res = await parse_channel(db, username,
                                  limit=int(data.get("limit", 80)),
                                  days_back=int(data.get("days_back", 120)))
    return res


@app.get("/api/admin/analysis/overview")
async def admin_analysis_overview(token: str = ""):
    if not _check_admin_token(token):
        return {"ok": False}
    from app.services.content_analysis import get_overview
    async with async_session() as db:
        ov = await get_overview(db)
    return {"ok": True, **ov}


@app.post("/api/admin/analysis/ai")
async def admin_analysis_ai(request: Request):
    data = await request.json()
    if not _check_admin_token(data.get("token", "")):
        return {"ok": False}
    username = (data.get("username", "") or "").lstrip("@").strip()
    if not username:
        return {"ok": False, "error": "username required"}
    from app.services.content_analysis import analyze_channel
    async with async_session() as db:
        res = await analyze_channel(db, username)
    return res


@app.get("/api/admin/analysis/reports")
async def admin_analysis_reports(token: str = ""):
    if not _check_admin_token(token):
        return {"ok": False}
    from app.services.content_analysis import get_reports
    async with async_session() as db:
        reports = await get_reports(db)
    return {"ok": True, "reports": reports}
