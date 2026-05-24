import pytest
from app.services.reflinks import (
    analyze_link_issues, check_link,
    add_ref_link, get_user_links, format_check_result,
    _determine_status,
)
from app.models.features import RefLink, RefLinkCheck


def test_analyze_clean_link():
    result = {
        "original_url": "https://track.example.com?sub_id=123",
        "final_url": "https://casino.com?sub_id=123",
        "redirect_chain": ["https://track.example.com?sub_id=123", "https://casino.com?sub_id=123"],
        "status_code": 200,
        "response_time_ms": 300,
        "issues": [],
    }
    issues = analyze_link_issues("https://track.example.com?sub_id=123", result)
    assert any("✅" in i for i in issues)


def test_analyze_dead_link():
    result = {
        "final_url": "", "redirect_chain": [], "status_code": 404,
        "response_time_ms": 100, "issues": [],
    }
    issues = analyze_link_issues("https://dead.example.com", result)
    assert any("мертва" in i for i in issues)


def test_analyze_missing_param():
    result = {
        "original_url": "https://track.com?sub_id=123&clickid=abc",
        "final_url": "https://casino.com?sub_id=123",
        "redirect_chain": ["https://track.com?sub_id=123&clickid=abc", "https://casino.com?sub_id=123"],
        "status_code": 200,
        "response_time_ms": 200,
        "issues": [],
    }
    issues = analyze_link_issues("https://track.com?sub_id=123&clickid=abc", result)
    assert any("clickid" in i and "пропал" in i for i in issues)


def test_analyze_changed_param():
    result = {
        "original_url": "https://track.com?sub_id=myid",
        "final_url": "https://casino.com?sub_id=replaced",
        "redirect_chain": ["https://track.com?sub_id=myid", "https://casino.com?sub_id=replaced"],
        "status_code": 200,
        "response_time_ms": 200,
        "issues": [],
    }
    issues = analyze_link_issues("https://track.com?sub_id=myid", result)
    assert any("sub_id" in i and "изменён" in i for i in issues)


def test_analyze_too_many_redirects():
    chain = [f"https://hop{i}.com" for i in range(7)]
    result = {
        "final_url": chain[-1], "redirect_chain": chain,
        "status_code": 200, "response_time_ms": 200, "issues": [],
    }
    issues = analyze_link_issues(chain[0], result)
    assert any("редиректов" in i for i in issues)


def test_analyze_slow_response():
    result = {
        "final_url": "https://casino.com", "redirect_chain": ["https://a.com", "https://casino.com"],
        "status_code": 200, "response_time_ms": 6000, "issues": [],
    }
    issues = analyze_link_issues("https://a.com", result)
    assert any("Медленный" in i for i in issues)


def test_determine_status_ok():
    assert _determine_status({"issues": ["✅ Ссылка работает"]}) == "ok"


def test_determine_status_dead():
    assert _determine_status({"issues": ["❌ Ссылка мертва (HTTP 404)"]}) == "dead"


def test_determine_status_suspicious():
    assert _determine_status({"issues": ["🚩 Параметр sub_id пропал"]}) == "suspicious"


@pytest.mark.asyncio
async def test_add_and_get_links(db):
    link = await add_ref_link(db, user_id=12345, url="https://test.com?sub_id=abc")
    assert link.id is not None
    assert link.url == "https://test.com?sub_id=abc"

    links = await get_user_links(db, 12345)
    assert len(links) == 1


@pytest.mark.asyncio
async def test_add_multiple_links(db):
    await add_ref_link(db, user_id=99, url="https://a.com")
    await add_ref_link(db, user_id=99, url="https://b.com")
    links = await get_user_links(db, 99)
    assert len(links) == 2


def test_format_check_result():
    link = RefLink(
        id=1, user_id=1, url="https://test.com?sub_id=123",
        program_name="Royal Partners", last_status="ok", check_count=3, alerts=[],
    )
    check = RefLinkCheck(
        link_id=1, status_code=200, final_url="https://casino.com?sub_id=123",
        redirect_chain=["https://test.com", "https://casino.com"], response_time_ms=250,
        issues=["✅ Ссылка работает корректно"],
    )
    text = format_check_result(link, check)
    assert "Royal Partners" in text
    assert "250ms" in text
    assert "✅" in text
