from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import GeoRateCPA, GeoRateRS, RateRaw, PPCondition


async def get_cpa_rates(db: AsyncSession, geo_filter: str | None = None) -> list[dict]:
    query = select(GeoRateCPA).order_by(GeoRateCPA.avg_cpa.desc())
    if geo_filter:
        query = query.where(GeoRateCPA.geo.ilike(f"%{geo_filter}%"))
    result = await db.execute(query)
    rows = result.scalars().all()
    return [
        {
            "geo": r.geo, "min": r.min_cpa, "avg": r.avg_cpa,
            "max": r.max_cpa, "points": r.data_points,
            "sources": r.sources, "programs": r.programs,
        }
        for r in rows
    ]


async def get_rs_rates(db: AsyncSession, geo_filter: str | None = None) -> list[dict]:
    query = select(GeoRateRS).order_by(GeoRateRS.avg_rs.desc())
    if geo_filter:
        query = query.where(GeoRateRS.geo.ilike(f"%{geo_filter}%"))
    result = await db.execute(query)
    rows = result.scalars().all()
    return [
        {
            "geo": r.geo, "min": r.min_rs, "avg": r.avg_rs,
            "max": r.max_rs, "points": r.data_points,
            "sources": r.sources, "programs": r.programs,
        }
        for r in rows
    ]


async def get_pp_conditions(db: AsyncSession, name_filter: str | None = None) -> list[dict]:
    query = select(PPCondition).order_by(PPCondition.records_count.desc())
    if name_filter:
        query = query.where(PPCondition.name.ilike(f"%{name_filter}%"))
    result = await db.execute(query)
    rows = result.scalars().all()
    return [
        {
            "name": r.name, "geos": r.geos,
            "cpa_min": r.cpa_min, "cpa_max": r.cpa_max,
            "rs_min": r.rs_min, "rs_max": r.rs_max,
            "records": r.records_count, "source": r.source,
        }
        for r in rows
    ]


async def get_rate_for_geo(db: AsyncSession, geo: str) -> dict | None:
    geo_upper = geo.upper().strip()
    cpa_q = select(GeoRateCPA).where(GeoRateCPA.geo == geo_upper)
    rs_q = select(GeoRateRS).where(GeoRateRS.geo == geo_upper)

    cpa_result = await db.execute(cpa_q)
    rs_result = await db.execute(rs_q)
    cpa = cpa_result.scalar_one_or_none()
    rs = rs_result.scalar_one_or_none()

    if not cpa and not rs:
        return None

    return {
        "geo": geo_upper,
        "cpa": {"min": cpa.min_cpa, "avg": cpa.avg_cpa, "max": cpa.max_cpa, "points": cpa.data_points} if cpa else None,
        "rs": {"min": rs.min_rs, "avg": rs.avg_rs, "max": rs.max_rs, "points": rs.data_points} if rs else None,
    }


def format_rates_message(geo: str, data: dict) -> str:
    lines = [f"🌍 <b>{geo}</b>\n"]
    if data.get("cpa"):
        c = data["cpa"]
        lines.append(f"💰 <b>CPA:</b> ${c['min']:.0f} → <b>${c['avg']:.0f}</b> → ${c['max']:.0f}")
        lines.append(f"   ({c['points']} точек данных)")
    if data.get("rs"):
        r = data["rs"]
        lines.append(f"📊 <b>RevShare:</b> {r['min']:.0f}% → <b>{r['avg']:.0f}%</b> → {r['max']:.0f}%")
        lines.append(f"   ({r['points']} точек данных)")
    if not data.get("cpa") and not data.get("rs"):
        lines.append("Нет данных по этому ГЕО")
    return "\n".join(lines)


def format_rates_list(rates: list[dict], rate_type: str) -> str:
    if rate_type == "cpa":
        header = "💰 <b>CPA ставки по ГЕО</b>\n\n"
        lines = []
        for r in rates[:20]:
            lines.append(f"<b>{r['geo']}</b>: ${r['min']:.0f} → <b>${r['avg']:.0f}</b> → ${r['max']:.0f}")
        return header + "\n".join(lines)
    else:
        header = "📊 <b>RevShare по ГЕО</b>\n\n"
        lines = []
        for r in rates[:20]:
            lines.append(f"<b>{r['geo']}</b>: {r['min']:.0f}% → <b>{r['avg']:.0f}%</b> → {r['max']:.0f}%")
        return header + "\n".join(lines)
