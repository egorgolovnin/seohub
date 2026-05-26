from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.rates import get_cpa_rates, get_pp_conditions, get_rate_for_geo
from app.services.reflinks import check_link
from app.services.stats_analyzer import analyze_stats

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
    result = await check_link(url)
    return result


class StatsRequest(BaseModel):
    program_name: str = ""
    geo: str = ""
    period: str = ""
    model: str = ""
    clicks: int = 0
    registrations: int = 0
    ftd: int = 0
    deposits_sum: float = 0
    ggr: float = 0
    commission: float = 0


@router.post("/analyze-stats")
async def api_analyze_stats(req: StatsRequest):
    stats = req.model_dump()
    analysis = analyze_stats(stats, stats.get("geo", ""))
    return {"stats": stats, "analysis": analysis}


class IoffersRequest(BaseModel):
    telegram: str
    site: str = ""
    comment: str = ""


@router.post("/ioffers-request")
async def api_ioffers_request(req: IoffersRequest):
    from app.bot.main import get_bot
    from app.config import get_settings
    settings = get_settings()
    if settings.admin_chat_id:
        bot = get_bot()
        text = (
            f"📊 <b>Заявка на iOffers</b>\n\n"
            f"👤 Telegram: {req.telegram}\n"
            f"🌐 Сайт: {req.site or 'не указан'}\n"
            f"💬 Комментарий: {req.comment or 'нет'}"
        )
        try:
            await bot.send_message(settings.admin_chat_id, text)
        except Exception:
            pass
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
    from app.bot.main import get_bot
    from app.config import get_settings
    settings = get_settings()
    if settings.admin_chat_id:
        bot = get_bot()
        text = (
            f"🔗 <b>Заявка на BetBuddy Link</b>\n\n"
            f"👤 Имя: {req.name or 'не указано'}\n"
            f"📱 Telegram: {req.telegram}"
        )
        try:
            await bot.send_message(settings.admin_chat_id, text)
        except Exception:
            pass
    return {"ok": True}


class LeadRequest(BaseModel):
    name: str = ""
    telegram: str
    product: str = ""
    details: str = ""


@router.post("/lead")
async def api_lead(req: LeadRequest):
    from app.bot.main import get_bot
    from app.config import get_settings
    settings = get_settings()
    if settings.admin_chat_id:
        bot = get_bot()
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
        try:
            await bot.send_message(settings.admin_chat_id, text)
        except Exception:
            pass
    return {"ok": True}
