import pytest
from app.services.stats_analyzer import (
    analyze_stats, compute_metrics, get_geo_tier,
    save_stats, format_analysis,
)
from app.bot.features import parse_stats_input


def test_geo_tiers():
    assert get_geo_tier("US") == "TIER1"
    assert get_geo_tier("DE") == "TIER1"
    assert get_geo_tier("RU") == "TIER2"
    assert get_geo_tier("BR") == "TIER3"
    assert get_geo_tier("ZZ") == "default"


def test_compute_metrics_normal():
    stats = {"clicks": 10000, "registrations": 800, "ftd": 120, "deposits_sum": 15000, "ggr": 5000}
    m = compute_metrics(stats)
    assert m["click_to_reg"] == pytest.approx(0.08, abs=0.01)
    assert m["reg_to_ftd"] == pytest.approx(0.15, abs=0.01)
    assert m["avg_deposit"] == pytest.approx(125, abs=1)
    assert m["ggr_per_ftd"] == pytest.approx(41.67, abs=1)


def test_compute_metrics_zeros():
    stats = {"clicks": 0, "registrations": 0, "ftd": 0, "deposits_sum": 0, "ggr": 0}
    m = compute_metrics(stats)
    assert m["click_to_reg"] == 0
    assert m["reg_to_ftd"] == 0
    assert m["avg_deposit"] == 0


def test_analyze_normal_stats():
    stats = {
        "clicks": 10000, "registrations": 800, "ftd": 120,
        "deposits_sum": 15000, "ggr": 5000, "commission": 2000, "model": "RS",
    }
    result = analyze_stats(stats, "DE")
    assert result["risk_score"] < 4
    assert "🟢" in result["verdict"] or "✅" in result["verdict"]


def test_analyze_suspicious_low_ftd():
    stats = {
        "clicks": 15000, "registrations": 1200, "ftd": 30,
        "deposits_sum": 3000, "ggr": 1000, "commission": 200, "model": "RS",
    }
    result = analyze_stats(stats, "DE")
    assert result["risk_score"] >= 2
    assert any("рега→FTD" in f for f in result["flags"])


def test_analyze_shave_detected():
    stats = {
        "clicks": 10000, "registrations": 800, "ftd": 120,
        "deposits_sum": 24000, "ggr": 8500, "commission": 850, "model": "RS",
    }
    result = analyze_stats(stats, "DE")
    # Commission is 10% of GGR but should be 30-60% → shave flag
    assert any("RevShare" in f and "низкий" in f for f in result["flags"])
    assert result["risk_score"] >= 2


def test_analyze_crossmarketing():
    stats = {
        "clicks": 20000, "registrations": 2000, "ftd": 15,
        "deposits_sum": 1500, "ggr": 500, "commission": 100, "model": "CPA",
    }
    result = analyze_stats(stats, "RU")
    assert any("кроссмаркетинг" in f.lower() for f in result["flags"])


def test_analyze_low_ggr():
    stats = {
        "clicks": 5000, "registrations": 500, "ftd": 80,
        "deposits_sum": 8000, "ggr": 200, "commission": 60, "model": "RS",
    }
    result = analyze_stats(stats, "BR")
    assert any("GGR" in f for f in result["flags"])


def test_analyze_high_risk():
    stats = {
        "clicks": 50000, "registrations": 500, "ftd": 10,
        "deposits_sum": 500, "ggr": 50, "commission": 5, "model": "RS",
    }
    result = analyze_stats(stats, "DE")
    assert result["risk_score"] >= 5
    assert "🔴" in result["verdict"] or "🟡" in result["verdict"]


def test_analyze_everything_normal():
    stats = {
        "clicks": 10000, "registrations": 1000, "ftd": 200,
        "deposits_sum": 20000, "ggr": 6000, "commission": 2400, "model": "RS",
    }
    result = analyze_stats(stats, "DE")
    assert result["risk_score"] < 3


def test_parse_stats_input_valid():
    text = """ПП: Royal Partners
ГЕО: DE
Период: 2026-04
Модель: RS
Клики: 15000
Реги: 1200
FTD: 180
Депозиты: 24000
GGR: 8500
Комиссия: 2550"""
    data = parse_stats_input(text)
    assert data is not None
    assert data["program_name"] == "Royal Partners"
    assert data["geo"] == "DE"
    assert data["clicks"] == 15000
    assert data["ftd"] == 180
    assert data["ggr"] == 8500


def test_parse_stats_input_with_dollar_signs():
    text = """Клики: 10,000
FTD: 120
Депозиты: $24,000
GGR: $8,500"""
    data = parse_stats_input(text)
    assert data["clicks"] == 10000
    assert data["deposits_sum"] == 24000


def test_parse_stats_input_empty():
    data = parse_stats_input("hello world")
    assert data is None


def test_format_analysis():
    stats = {"program_name": "Royal Partners", "geo": "DE", "period": "2026-04"}
    analysis = {
        "metrics": {"click_to_reg": 0.08, "reg_to_ftd": 0.15, "avg_deposit": 125, "ggr_per_ftd": 42},
        "flags": ["✅ Все метрики в норме"],
        "recommendations": [],
        "risk_score": 1.5,
        "verdict": "🟢 В целом нормально",
    }
    text = format_analysis(stats, analysis)
    assert "Royal Partners" in text
    assert "DE" in text
    assert "1.5/10" in text
    assert "🟢" in text


@pytest.mark.asyncio
async def test_save_stats(db):
    stats = {"clicks": 10000, "registrations": 800, "ftd": 120, "deposits_sum": 15000, "ggr": 5000, "commission": 2000, "model": "RS", "program_name": "Test", "geo": "DE", "period": "2026-04"}
    analysis = analyze_stats(stats, "DE")
    upload = await save_stats(db, user_id=123, stats=stats, analysis=analysis)
    assert upload.id is not None
    assert upload.clicks == 10000
    assert upload.risk_score is not None
