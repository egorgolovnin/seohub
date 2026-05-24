import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.features import PartnerStatsUpload

logger = logging.getLogger(__name__)

# Industry benchmarks from chat analysis (480K messages)
BENCHMARKS = {
    "click_to_reg": {"low": 0.02, "normal_min": 0.05, "normal_max": 0.20, "high": 0.35},
    "reg_to_ftd": {"low": 0.05, "normal_min": 0.10, "normal_max": 0.40, "high": 0.60},
    "avg_deposit": {
        "TIER1": {"low": 20, "normal_min": 40, "normal_max": 200, "high": 500},
        "TIER2": {"low": 10, "normal_min": 20, "normal_max": 100, "high": 300},
        "TIER3": {"low": 5, "normal_min": 10, "normal_max": 50, "high": 150},
        "default": {"low": 10, "normal_min": 25, "normal_max": 150, "high": 400},
    },
    "ggr_per_ftd": {
        "default": {"low": 5, "normal_min": 15, "normal_max": 80, "high": 200},
    },
}

GEO_TIERS = {
    "TIER1": ["US", "UK", "CA", "AU", "DE", "AT", "CH", "NL", "DK", "NO", "SE", "FI", "FR", "IE", "NZ", "BE", "IT", "ES"],
    "TIER2": ["RU", "KZ", "PL", "CZ", "PT", "GR", "HU", "HR", "SK", "SI", "EE", "JP", "SG"],
    "TIER3": ["BR", "MX", "IN", "TR", "ZA", "TH", "CO", "AR", "CL", "BD", "UZ", "BY"],
}


def get_geo_tier(geo: str) -> str:
    geo = geo.upper().strip()
    for tier, countries in GEO_TIERS.items():
        if geo in countries:
            return tier
    return "default"


def compute_metrics(stats: dict) -> dict:
    """Compute derived metrics from raw stats."""
    clicks = stats.get("clicks", 0) or 0
    regs = stats.get("registrations", 0) or 0
    ftd = stats.get("ftd", 0) or 0
    deposits = stats.get("deposits_sum", 0) or 0
    ggr = stats.get("ggr", 0) or 0

    return {
        "click_to_reg": regs / clicks if clicks > 0 else 0,
        "reg_to_ftd": ftd / regs if regs > 0 else 0,
        "avg_deposit": deposits / ftd if ftd > 0 else 0,
        "ggr_per_ftd": ggr / ftd if ftd > 0 else 0,
    }


def analyze_stats(stats: dict, geo: str = "") -> dict:
    """Analyze partner stats and return flags, risk score, and recommendations."""
    metrics = compute_metrics(stats)
    tier = get_geo_tier(geo)
    flags = []
    recommendations = []
    risk_score = 0.0

    clicks = stats.get("clicks", 0) or 0
    regs = stats.get("registrations", 0) or 0
    ftd = stats.get("ftd", 0) or 0
    deposits = stats.get("deposits_sum", 0) or 0
    ggr = stats.get("ggr", 0) or 0
    commission = stats.get("commission", 0) or 0

    # 1. Click to Registration rate
    ctr = metrics["click_to_reg"]
    bench = BENCHMARKS["click_to_reg"]
    if clicks > 0 and ctr < bench["low"]:
        flags.append(f"🚩 Конверсия клик→рега слишком низкая: {ctr:.1%} (норма {bench['normal_min']:.0%}-{bench['normal_max']:.0%})")
        risk_score += 2
        recommendations.append("Проверь: трафик может не доходить до лендинга, или ПП срезает клики")
    elif clicks > 0 and ctr > bench["high"]:
        flags.append(f"⚠️ Конверсия клик→рега подозрительно высокая: {ctr:.1%}")
        risk_score += 1

    # 2. Registration to FTD rate
    rtf = metrics["reg_to_ftd"]
    bench_rtf = BENCHMARKS["reg_to_ftd"]
    if regs > 0 and rtf < bench_rtf["low"]:
        flags.append(f"🚩 Конверсия рега→FTD слишком низкая: {rtf:.1%} (норма {bench_rtf['normal_min']:.0%}-{bench_rtf['normal_max']:.0%})")
        risk_score += 2.5
        recommendations.append("Возможные причины: тяжёлая верификация, плохой UX казино, или ПП списывает FTD")
    elif regs > 0 and rtf > bench_rtf["high"]:
        flags.append(f"⚠️ Конверсия рега→FTD подозрительно высокая: {rtf:.1%}")
        risk_score += 1

    # 3. Average deposit
    avg_dep = metrics["avg_deposit"]
    dep_bench = BENCHMARKS["avg_deposit"].get(tier, BENCHMARKS["avg_deposit"]["default"])
    if ftd > 0 and avg_dep < dep_bench["low"]:
        flags.append(f"⚠️ Средний депозит низкий: ${avg_dep:.0f} (норма ${dep_bench['normal_min']}-${dep_bench['normal_max']} для {tier})")
        risk_score += 1
    elif ftd > 0 and avg_dep > dep_bench["high"]:
        flags.append(f"⚠️ Средний депозит подозрительно высокий: ${avg_dep:.0f}")
        risk_score += 0.5

    # 4. GGR per FTD
    ggr_ftd = metrics["ggr_per_ftd"]
    ggr_bench = BENCHMARKS["ggr_per_ftd"]["default"]
    if ftd > 0 and ggr_ftd < ggr_bench["low"]:
        flags.append(f"🚩 GGR на FTD слишком низкий: ${ggr_ftd:.0f} (норма ${ggr_bench['normal_min']}-${ggr_bench['normal_max']})")
        risk_score += 2
        recommendations.append("Низкий GGR может означать: шейв GGR, кроссмаркетинг игроков, или ПП режет доход")

    # 5. Commission sanity check (for CPA)
    model = stats.get("model", "").upper()
    if model == "CPA" and ftd > 0 and commission > 0:
        cpa_actual = commission / ftd
        if geo:
            from app.services.rates import get_rate_for_geo
            # Can't do async here, so just use benchmarks
            pass
        if cpa_actual < 10:
            flags.append(f"🚩 CPA за FTD слишком низкий: ${cpa_actual:.0f}")
            risk_score += 1.5

    # 6. RevShare sanity check
    if model in ("RS", "REVSHARE", "HYBRID") and ggr > 0 and commission > 0:
        rs_pct = (commission / ggr) * 100
        if rs_pct < 15:
            flags.append(f"🚩 Фактический RevShare: {rs_pct:.0f}% — подозрительно низкий (норма 30-60%)")
            risk_score += 2
            recommendations.append("Возможен шейв GGR или скрытые вычеты. Сравни с заявленным % в договоре")
        elif rs_pct > 80:
            flags.append(f"⚠️ Фактический RevShare: {rs_pct:.0f}% — подозрительно высокий")
            risk_score += 0.5

    # 7. Cross-marketing detection
    if ftd > 10 and regs > 0:
        ftd_drop_ratio = ftd / regs
        if ftd_drop_ratio < 0.03:
            flags.append("🚩 Возможный кроссмаркетинг: очень мало FTD при нормальных регах")
            risk_score += 2
            recommendations.append("Казино может переводить твоих игроков на другой бренд холдинга")

    # Cap risk score
    risk_score = min(risk_score, 10.0)

    # Overall verdict
    if risk_score >= 7:
        verdict = "🔴 Высокий риск шейва/абуза"
    elif risk_score >= 4:
        verdict = "🟡 Есть подозрительные метрики — рекомендуем проверить"
    elif risk_score >= 1:
        verdict = "🟢 В целом нормально, мелкие отклонения"
    else:
        verdict = "✅ Метрики в норме"

    if not flags:
        flags.append("✅ Все метрики в пределах нормы")

    return {
        "metrics": metrics,
        "flags": flags,
        "recommendations": recommendations,
        "risk_score": risk_score,
        "verdict": verdict,
    }


async def save_stats(db: AsyncSession, user_id: int, stats: dict, analysis: dict) -> PartnerStatsUpload:
    metrics = analysis.get("metrics", {})
    upload = PartnerStatsUpload(
        user_id=user_id,
        program_name=stats.get("program_name", ""),
        geo=stats.get("geo", ""),
        period=stats.get("period", ""),
        clicks=stats.get("clicks"),
        registrations=stats.get("registrations"),
        ftd=stats.get("ftd"),
        deposits_sum=stats.get("deposits_sum"),
        ggr=stats.get("ggr"),
        commission=stats.get("commission"),
        model=stats.get("model", ""),
        click_to_reg=metrics.get("click_to_reg"),
        reg_to_ftd=metrics.get("reg_to_ftd"),
        avg_deposit=metrics.get("avg_deposit"),
        ggr_per_ftd=metrics.get("ggr_per_ftd"),
        analysis=analysis,
        risk_score=analysis.get("risk_score", 0),
        flags=analysis.get("flags", []),
    )
    db.add(upload)
    await db.commit()
    await db.refresh(upload)
    return upload


async def get_user_uploads(db: AsyncSession, user_id: int) -> list[PartnerStatsUpload]:
    result = await db.execute(
        select(PartnerStatsUpload)
        .where(PartnerStatsUpload.user_id == user_id)
        .order_by(PartnerStatsUpload.created_at.desc())
        .limit(10)
    )
    return list(result.scalars().all())


def format_analysis(stats: dict, analysis: dict) -> str:
    lines = ["📊 <b>Анализ статистики</b>\n"]

    if stats.get("program_name"):
        lines.append(f"📋 ПП: {stats['program_name']}")
    if stats.get("geo"):
        lines.append(f"🌍 ГЕО: {stats['geo']}")
    if stats.get("period"):
        lines.append(f"📅 Период: {stats['period']}")

    lines.append("")

    m = analysis.get("metrics", {})
    lines.append("<b>Метрики:</b>")
    if m.get("click_to_reg"):
        lines.append(f"  Клик → Рега: {m['click_to_reg']:.1%}")
    if m.get("reg_to_ftd"):
        lines.append(f"  Рега → FTD: {m['reg_to_ftd']:.1%}")
    if m.get("avg_deposit"):
        lines.append(f"  Средний депозит: ${m['avg_deposit']:.0f}")
    if m.get("ggr_per_ftd"):
        lines.append(f"  GGR/FTD: ${m['ggr_per_ftd']:.0f}")

    lines.append(f"\n<b>Риск:</b> {analysis.get('risk_score', 0):.1f}/10")
    lines.append(f"<b>Вердикт:</b> {analysis.get('verdict', '')}")

    lines.append("\n<b>Детали:</b>")
    for flag in analysis.get("flags", []):
        lines.append(flag)

    if analysis.get("recommendations"):
        lines.append("\n<b>Рекомендации:</b>")
        for rec in analysis["recommendations"]:
            lines.append(f"💡 {rec}")

    return "\n".join(lines)
