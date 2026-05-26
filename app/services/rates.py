from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import GeoRateCPA, GeoRateRS, RateRaw, PPCondition

# GEO aliases: name → ISO code
GEO_ALIASES = {
    # Russian names
    "германия": "DE", "немецкий": "DE",
    "австрия": "AT", "австрийский": "AT",
    "швейцария": "CH", "швейцарский": "CH",
    "великобритания": "UK", "англия": "UK", "британия": "UK", "английский": "UK",
    "франция": "FR", "французский": "FR",
    "испания": "ES", "испанский": "ES",
    "италия": "IT", "итальянский": "IT",
    "нидерланды": "NL", "голландия": "NL", "голландский": "NL",
    "бельгия": "BE", "бельгийский": "BE",
    "португалия": "PT", "португальский": "PT",
    "польша": "PL", "польский": "PL",
    "чехия": "CZ", "чешский": "CZ",
    "словакия": "SK", "словацкий": "SK",
    "хорватия": "HR", "хорватский": "HR",
    "словения": "SI", "словенский": "SI",
    "венгрия": "HU", "венгерский": "HU",
    "румыния": "RO", "румынский": "RO",
    "болгария": "BG", "болгарский": "BG",
    "греция": "GR", "греческий": "GR",
    "турция": "TR", "турецкий": "TR",
    "финляндия": "FI", "финский": "FI",
    "швеция": "SE", "шведский": "SE",
    "норвегия": "NO", "норвежский": "NO",
    "дания": "DK", "датский": "DK",
    "ирландия": "IE", "ирландский": "IE",
    "эстония": "EE", "эстонский": "EE",
    "латвия": "LV", "латвийский": "LV",
    "литва": "LT", "литовский": "LT",
    "россия": "RU", "русский": "RU", "рф": "RU", "российский": "RU",
    "казахстан": "KZ", "казахский": "KZ",
    "узбекистан": "UZ", "узбекский": "UZ",
    "беларусь": "BY", "белоруссия": "BY", "белорусский": "BY",
    "украина": "UA", "украинский": "UA",
    "бразилия": "BR", "бразильский": "BR",
    "мексика": "MX", "мексиканский": "MX",
    "аргентина": "AR", "аргентинский": "AR",
    "чили": "CL", "чилийский": "CL",
    "колумбия": "CO", "колумбийский": "CO",
    "индия": "IN", "индийский": "IN",
    "бангладеш": "BD",
    "таиланд": "TH", "тайский": "TH",
    "япония": "JP", "японский": "JP",
    "сингапур": "SG",
    "австралия": "AU", "австралийский": "AU",
    "новая зеландия": "NZ",
    "канада": "CA", "канадский": "CA",
    "сша": "US", "америка": "US", "американский": "US", "штаты": "US",
    "юар": "ZA", "южная африка": "ZA",
    "оаэ": "AE", "эмираты": "AE", "дубай": "AE",
    "саудовская аравия": "SA",
    # English names
    "germany": "DE", "german": "DE",
    "austria": "AT", "austrian": "AT",
    "switzerland": "CH", "swiss": "CH",
    "united kingdom": "UK", "england": "UK", "britain": "UK", "british": "UK",
    "france": "FR", "french": "FR",
    "spain": "ES", "spanish": "ES",
    "italy": "IT", "italian": "IT",
    "netherlands": "NL", "holland": "NL", "dutch": "NL",
    "belgium": "BE",
    "portugal": "PT", "portuguese": "PT",
    "poland": "PL", "polish": "PL",
    "czech republic": "CZ", "czechia": "CZ", "czech": "CZ",
    "slovakia": "SK",
    "croatia": "HR",
    "slovenia": "SI",
    "hungary": "HU", "hungarian": "HU",
    "romania": "RO",
    "bulgaria": "BG",
    "greece": "GR", "greek": "GR",
    "turkey": "TR", "turkish": "TR",
    "finland": "FI", "finnish": "FI",
    "sweden": "SE", "swedish": "SE",
    "norway": "NO", "norwegian": "NO",
    "denmark": "DK", "danish": "DK",
    "ireland": "IE", "irish": "IE",
    "estonia": "EE",
    "latvia": "LV",
    "lithuania": "LT",
    "russia": "RU", "russian": "RU",
    "kazakhstan": "KZ",
    "uzbekistan": "UZ",
    "belarus": "BY",
    "ukraine": "UA", "ukrainian": "UA",
    "brazil": "BR", "brazilian": "BR",
    "mexico": "MX", "mexican": "MX",
    "argentina": "AR",
    "chile": "CL",
    "colombia": "CO",
    "india": "IN", "indian": "IN",
    "bangladesh": "BD",
    "thailand": "TH", "thai": "TH",
    "japan": "JP", "japanese": "JP",
    "singapore": "SG",
    "australia": "AU", "australian": "AU",
    "new zealand": "NZ",
    "canada": "CA", "canadian": "CA",
    "usa": "US", "united states": "US", "america": "US", "american": "US",
    "south africa": "ZA",
    "uae": "AE", "dubai": "AE", "emirates": "AE",
    "saudi arabia": "SA", "saudi": "SA",
    # DACH / region shortcuts
    "dach": "DE", "латам": "BR", "latam": "BR",
    "скандинавия": "SE", "scandinavia": "SE", "nordics": "SE",
}


def resolve_geo_alias(query: str) -> str:
    """Resolve a GEO alias to its ISO code. Returns original if not found."""
    q = query.strip().lower()
    if q in GEO_ALIASES:
        return GEO_ALIASES[q]
    # Already a code (2-6 chars uppercase)
    if len(q) <= 6 and q.isalpha():
        return q.upper()
    return query.upper()


async def get_cpa_rates(db: AsyncSession, geo_filter: str | None = None) -> list[dict]:
    query = select(GeoRateCPA).order_by(GeoRateCPA.avg_cpa.desc())
    if geo_filter:
        resolved = resolve_geo_alias(geo_filter)
        query = query.where(GeoRateCPA.geo.ilike(f"%{resolved}%"))
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
        resolved = resolve_geo_alias(geo_filter)
        query = query.where(GeoRateRS.geo.ilike(f"%{resolved}%"))
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
    geo_upper = resolve_geo_alias(geo)
    cpa_q = select(GeoRateCPA).where(GeoRateCPA.geo == geo_upper)

    cpa_result = await db.execute(cpa_q)
    cpa = cpa_result.scalar_one_or_none()

    if not cpa:
        return None

    return {
        "geo": geo_upper,
        "cpa": {"min": cpa.min_cpa, "avg": cpa.avg_cpa, "max": cpa.max_cpa} if cpa else None,
    }


def format_rates_message(geo: str, data: dict) -> str:
    lines = [f"🌍 <b>{geo}</b>\n"]
    if data.get("cpa"):
        c = data["cpa"]
        lines.append(f"💰 <b>CPA:</b> ${c['min']:.0f} → <b>${c['avg']:.0f}</b> → ${c['max']:.0f}")
    else:
        lines.append("Нет данных по этому ГЕО")
    return "\n".join(lines)


def format_rates_list(rates: list[dict], rate_type: str) -> str:
    header = "💰 <b>CPA ставки по ГЕО</b>\n\n"
    lines = []
    for r in rates:
        lines.append(f"<b>{r['geo']}</b>: ${r['min']:.0f} → <b>${r['avg']:.0f}</b> → ${r['max']:.0f}")
    return header + "\n".join(lines)
