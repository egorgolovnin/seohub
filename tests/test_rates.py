import pytest
from app.services.rates import (
    get_cpa_rates, get_rs_rates, get_pp_conditions,
    get_rate_for_geo, format_rates_message, format_rates_list,
)


@pytest.mark.asyncio
async def test_get_cpa_rates_all(db_with_rates):
    rates = await get_cpa_rates(db_with_rates)
    assert len(rates) == 4
    assert rates[0]["avg"] >= rates[1]["avg"]  # sorted desc


@pytest.mark.asyncio
async def test_get_cpa_rates_filtered(db_with_rates):
    rates = await get_cpa_rates(db_with_rates, "DE")
    assert len(rates) == 1
    assert rates[0]["geo"] == "DE"


@pytest.mark.asyncio
async def test_get_rs_rates_all(db_with_rates):
    rates = await get_rs_rates(db_with_rates)
    assert len(rates) == 3


@pytest.mark.asyncio
async def test_get_rs_rates_filtered(db_with_rates):
    rates = await get_rs_rates(db_with_rates, "UA")
    assert len(rates) == 1
    assert rates[0]["geo"] == "UA"
    assert rates[0]["avg"] == 66


@pytest.mark.asyncio
async def test_get_rate_for_geo_found(db_with_rates):
    data = await get_rate_for_geo(db_with_rates, "DE")
    assert data is not None
    assert data["geo"] == "DE"
    assert data["cpa"]["avg"] == 260
    assert data["rs"]["avg"] == 30


@pytest.mark.asyncio
async def test_get_rate_for_geo_cpa_only(db_with_rates):
    data = await get_rate_for_geo(db_with_rates, "US")
    assert data is not None
    assert data["cpa"] is not None
    assert data["rs"] is None


@pytest.mark.asyncio
async def test_get_rate_for_geo_rs_only(db_with_rates):
    data = await get_rate_for_geo(db_with_rates, "UA")
    assert data is not None
    assert data["cpa"] is None
    assert data["rs"] is not None


@pytest.mark.asyncio
async def test_get_rate_for_geo_not_found(db_with_rates):
    data = await get_rate_for_geo(db_with_rates, "ZZ")
    assert data is None


@pytest.mark.asyncio
async def test_get_rate_case_insensitive(db_with_rates):
    data = await get_rate_for_geo(db_with_rates, "de")
    assert data is not None
    assert data["geo"] == "DE"


@pytest.mark.asyncio
async def test_get_pp_conditions(db_with_rates):
    pp = await get_pp_conditions(db_with_rates)
    assert len(pp) == 2
    assert pp[0]["records"] >= pp[1]["records"]


@pytest.mark.asyncio
async def test_get_pp_filtered(db_with_rates):
    pp = await get_pp_conditions(db_with_rates, "royal")
    assert len(pp) == 1
    assert pp[0]["name"] == "Royal Partners"


def test_format_rates_message():
    data = {
        "cpa": {"min": 120, "avg": 260, "max": 550, "points": 11},
        "rs": {"min": 20, "avg": 30, "max": 50, "points": 5},
    }
    msg = format_rates_message("DE", data)
    assert "DE" in msg
    assert "$260" in msg
    assert "30%" in msg


def test_format_rates_message_no_rs():
    data = {"cpa": {"min": 200, "avg": 400, "max": 800, "points": 3}, "rs": None}
    msg = format_rates_message("US", data)
    assert "$400" in msg
    assert "RevShare" not in msg


def test_format_rates_list_cpa():
    rates = [
        {"geo": "US", "min": 200, "avg": 400, "max": 800, "points": 3, "sources": "", "programs": ""},
        {"geo": "DE", "min": 120, "avg": 260, "max": 550, "points": 11, "sources": "", "programs": ""},
    ]
    msg = format_rates_list(rates, "cpa")
    assert "CPA" in msg
    assert "$400" in msg
    assert "$260" in msg


def test_format_rates_list_rs():
    rates = [
        {"geo": "UA", "min": 50, "avg": 66, "max": 80, "points": 6, "sources": "", "programs": ""},
    ]
    msg = format_rates_list(rates, "rs")
    assert "RevShare" in msg
    assert "66%" in msg
