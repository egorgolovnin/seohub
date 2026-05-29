from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.rates import get_cpa_rates, get_pp_conditions, get_rate_for_geo
from app.services.reflinks import check_link

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/rates/cpa")
async def api_cpa_rates(geo: str = Query(None), db: AsyncSession = Depends(get_db)):
    rates = await get_cpa_rates(db, geo)
    return {"type": "cpa", "count": len(rates), "data": rates}


@router.get("/rates/{geo}")
async def api_rate_by_geo(geo: str, db: AsyncSession = Depends(get_db)):
    data = await get_rate_for_geo(db, geo)
    if not data:
        return {"error": "GEO not found", "geo": geo}
    return data


@router.get("/pp")
async def api_pp_conditions(name: str = Query(None), db: AsyncSession = Depends(get_db)):
    conditions = await get_pp_conditions(db, name)
    return {"count": len(conditions), "data": conditions}


@router.get("/check-link")
async def api_check_link(url: str):
    from app.services.analytics import track
    await track("web_check", details=url[:100], source="web")
    result = await check_link(url)
    return result


class IoffersRequest(BaseModel):
    telegram: str
    site: str = ""
    comment: str = ""


@router.post("/ioffers-request")
async def api_ioffers_request(req: IoffersRequest):
    from app.bot.main import notify_admin
    text = (
        f"📊 <b>Заявка на iOffers</b>\n\n"
        f"👤 Telegram: {req.telegram}\n"
        f"🌐 Сайт: {req.site or 'не указан'}\n"
        f"💬 Комментарий: {req.comment or 'нет'}"
    )
    await notify_admin(text)
    return {"ok": True}


@router.post("/admin/reload-cpa")
async def reload_cpa(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import text
    from app.models.models import GeoRateCPA
    CPA = [("NL",120,330,650),("DK",130,300,560),("NO",130,300,400),("CH",120,290,520),("IE",130,280,500),("DE",120,260,550),("SE",130,260,400),("AT",130,260,400),("AE",200,250,300),("BE",160,250,550),("SA",150,250,380),("AU",120,250,500),("CA",120,250,500),("ES",120,240,450),("FR",120,240,500),("SK",180,240,350),("IT",120,220,350),("UK",120,220,500),("HR",200,260,350),("SI",120,220,300),("CZ",120,220,350),("GR",120,210,400),("FI",120,210,400),("NZ",120,210,360),("JP",130,200,340),("HU",120,180,350),("PL",120,170,350),("PT",120,170,300),("US",120,160,300),("SG",120,160,250),("EE",100,150,180),("RU",35,140,250),("KZ",23,120,200),("BY",25,120,200),("UZ",20,90,150),("BR",6,70,120),("CL",15,70,120),("IN",11,70,120),("BD",16,70,100),("TR",30,60,120),("ZA",5,70,100),("MX",5,50,80),("AR",13,40,80),("TH",15,30,50),("CO",20,30,50)]
    await db.execute(text("DELETE FROM geo_rates_cpa"))
    for geo, mn, avg, mx in CPA:
        db.add(GeoRateCPA(geo=geo, min_cpa=float(mn), avg_cpa=float(avg), max_cpa=float(mx), data_points=1, sources="seohub", programs=""))
    await db.commit()
    return {"ok": True, "loaded": len(CPA)}

class BBLRequest(BaseModel):
    name: str = ""
    telegram: str


@router.post("/bbl-request")
async def api_bbl_request(req: BBLRequest):
    from app.bot.main import notify_admin
    text = (
        f"🔗 <b>Заявка на BetBuddy Link</b>\n\n"
        f"👤 Имя: {req.name or 'не указано'}\n"
        f"📱 Telegram: {req.telegram}"
    )
    await notify_admin(text)
    return {"ok": True}


class LeadRequest(BaseModel):
    name: str = ""
    telegram: str
    product: str = ""
    details: str = ""


@router.post("/lead")
async def api_lead(req: LeadRequest):
    from app.bot.main import notify_admin
    text = (
        f"📩 <b>Новая заявка</b>\n\n"
        f"🛒 Продукт: {req.product}\n"
        f"👤 Имя: {req.name or 'не указано'}\n"
        f"📱 Telegram: {req.telegram}"
    )
    if req.details:
        try:
            import json
            d = json.loads(req.details)
            detail_lines = []
            labels = {
                "vert": "Вертикаль", "geo": "ГЕО", "vol": "Объём",
                "model": "Модель", "rate": "Ставка", "budget": "Бюджет",
                "site": "Сайт", "domain": "Домен", "traffic": "Трафик",
                "income": "Доход", "price": "Цена", "pp": "ПП", "text": "Описание",
            }
            for k, v in d.items():
                if v:
                    label = labels.get(k, k)
                    detail_lines.append(f"  {label}: {v}")
            if detail_lines:
                text += "\n\n📋 <b>Детали:</b>\n" + "\n".join(detail_lines)
        except Exception:
            text += f"\n📋 {req.details}"
    await notify_admin(text)
    from app.services.analytics import track
    await track("lead", username=req.telegram, details=req.product, source="web")
    return {"ok": True}
async def load_channels(db: AsyncSession = Depends(get_db)):
    from app.services.digest import add_channel
    CHANNELS = [
        ("1","По Уши в Гембле","po_ushi_v_gambling","seo"),
        ("2","MAXGAMBLER","maxxxigaming","seo"),
        ("3","Igor Bakalov","bakalov_info","seo"),
        ("4","SEO Dream Team","seodreamteamofficial","seo"),
        ("5","SEOшница","bakushevaseo","seo"),
        ("6","Тихий час","tkhychs","seo"),
        ("7","Phoenix Project","seoetc","seo"),
        ("8","Netkela","netkela","seo"),
        ("9","SЕalytics","sealytics","seo"),
        ("10","Аффилиатка и АИшка","aiseosales","seo"),
        ("11","Партнеркин Гемблинг","partnerkin_gambling","news"),
        ("12","Highroller","highroller_affiliate","news"),
        ("13","iGaming in High-Risk","igaming_highrisk","news"),
        ("14","R2B.News","r2b_news","news"),
        ("15","Oleg Shestakov","shestakov_oleg","news"),
        ("16","Подслушано в гембле","podslushano_gamble","news"),
        ("17","iGaming PUSH","igaming_push","news"),
        ("18","iGaming Kitchen","igaming_kitchen","news"),
        ("19","Gambla4","gambla4","news"),
        ("20","iGamingNews","igamingnews_tg","news"),
        ("21","iGaming Редакция","igaming_redakciya","news"),
        ("22","R2B.Work","r2b_work","news"),
        ("23","Три топора","tri_topora","news"),
        ("24","Вредный бук","vredniy_buk","news"),
        ("25","ГэмблХаус","gamblehouse","news"),
        ("26","PMP Media","pmp_media","news"),
        ("27","whitehat.media","whitehattea","seo"),
        ("28","Бабло побеждает зло!","MoneyBeatsEvil","seo"),
        ("29","iGaming CMO","igaming_cmo","news"),
        ("30","iGaming Insides","igaming_insides","news"),
        ("31","GGM iGaming People","ggm_igaming","news"),
        ("32","C-lvl Лидеры iGaming","clvl_igaming","news"),
        ("33","Новости букмекеров","novosti_bk","news"),
        ("34","iGaming CEO","igaming_ceo","news"),
        ("35","Спортивный маркетолог","sport_marketolog","news"),
        ("36","Affiliate Diaries","affiliate_diaries","seo"),
        ("37","AffMoment","affmoment","news"),
        ("38","seomoneymaker","seomoneymaker_channel","seo"),
        ("39","PM Talents","pm_talents","news"),
        ("40","MOST","most_igaming","news"),
    ]
    loaded = 0
    for cid, name, username, cat in CHANNELS:
        try:
            await add_channel(db, cid, name, username, cat)
            loaded += 1
        except Exception:
            await db.rollback()
    return {"ok": True, "loaded": loaded, "total": len(CHANNELS)}


@router.post("/admin/test-telethon")
async def test_telethon():
    from app.config import get_settings
    settings = get_settings()
    diag = {
        "telethon_api_id": settings.telethon_api_id,
        "telethon_api_id_type": type(settings.telethon_api_id).__name__,
        "telethon_api_hash_set": bool(settings.telethon_api_hash),
        "telethon_session_set": bool(settings.telethon_session_string),
        "session_length": len(settings.telethon_session_string) if settings.telethon_session_string else 0,
    }
    if not settings.telethon_api_id or not settings.telethon_session_string:
        diag["error"] = "telethon_api_id or session_string not set"
        return diag

    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        client = TelegramClient(
            StringSession(settings.telethon_session_string),
            settings.telethon_api_id,
            settings.telethon_api_hash,
        )
        await client.connect()
        authorized = await client.is_user_authorized()
        me = None
        if authorized:
            me_obj = await client.get_me()
            me = f"@{me_obj.username}" if me_obj.username else str(me_obj.id)
        await client.disconnect()
        diag["authorized"] = authorized
        diag["me"] = me
    except Exception as e:
        diag["error"] = str(e)[:200]

    return diag


@router.post("/admin/trigger-digest")
async def trigger_digest():
    """Manually trigger channel fetch + scoring."""
    from app.services.scheduler import job_fetch_channels, job_score_posts
    result = {}
    try:
        await job_fetch_channels()
        result["fetch"] = "ok"
    except Exception as e:
        result["fetch_error"] = str(e)[:200]
    try:
        await job_score_posts()
        result["score"] = "ok"
    except Exception as e:
        result["score_error"] = str(e)[:200]
    return result


@router.post("/admin/trigger-approval")
async def trigger_approval():
    """Send scored posts to admin for approval."""
    from app.database import async_session
    from app.services.digest import get_top_posts_for_today
    from app.bot.main import send_digest_approval
    from sqlalchemy import select
    from app.models.models import DigestPost

    async with async_session() as db:
        # Get all scored posts (not just today, lower threshold for testing)
        result = await db.execute(
            select(DigestPost)
            .where(DigestPost.status == "scored")
            .where(DigestPost.importance_score >= 3.0)
            .order_by(DigestPost.importance_score.desc())
            .limit(10)
        )
        posts = list(result.scalars().all())

    if not posts:
        return {"ok": False, "message": "No scored posts found"}

    sent = 0
    for post in posts:
        try:
            await send_digest_approval(post)
            sent += 1
        except Exception as e:
            pass

    return {"ok": True, "sent": sent, "total_scored": len(posts)}
