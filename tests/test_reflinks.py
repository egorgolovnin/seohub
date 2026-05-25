import pytest
from app.services.reflinks import (
    analyze_link_issues, _is_macro, _is_gambling_domain,
    _extract_tracking_params, _determine_status,
    add_ref_link, get_user_links, format_check_result,
)
from app.models.features import RefLink, RefLinkCheck


def test_is_macro():
    assert _is_macro("{clickid}") is True
    assert _is_macro("{sub_id}") is True
    assert _is_macro("{{click}}") is True
    assert _is_macro("[subid]") is True
    assert _is_macro("abc123") is False
    assert _is_macro("250393") is False


def test_is_gambling_domain():
    assert _is_gambling_domain("bassbt100.com") is False  # no keyword
    assert _is_gambling_domain("casino-bonus.guru") is True
    assert _is_gambling_domain("best-slots-online.com") is True
    assert _is_gambling_domain("play-fortune.com") is True
    assert _is_gambling_domain("google.com") is False


def test_extract_tracking_params():
    url = "https://track.com?sub_id=123&clickid={clickid}&foo=bar"
    params = _extract_tracking_params(url)
    assert "sub_id" in params
    assert params["sub_id"]["value"] == "123"
    assert params["sub_id"]["is_macro"] is False
    assert "clickid" in params
    assert params["clickid"]["is_macro"] is True
    assert "foo" not in params  # not a tracking param


def test_analyze_gambling_403():
    """Gambling site returning 403 should NOT be marked as dead."""
    result = {
        "original_url": "https://track.com?mid=250393",
        "final_url": "https://casino-bonus.com/reg?mid=250393",
        "redirect_chain": ["https://track.com?mid=250393", "https://casino-bonus.com/reg?mid=250393"],
        "status_code": 403,
        "response_time_ms": 500,
        "issues": [],
        "info": [],
    }
    issues, info = analyze_link_issues("https://track.com?mid=250393", result)
    # Should NOT have "dead" or "мертва"
    assert not any("💀" in i for i in issues)
    # Should have "работает" in info
    assert any("работает" in i for i in info)


def test_analyze_real_dead_link():
    result = {
        "original_url": "https://dead.com",
        "final_url": "https://dead.com",
        "redirect_chain": ["https://dead.com"],
        "status_code": 404,
        "response_time_ms": 100,
        "issues": [],
        "info": [],
    }
    issues, info = analyze_link_issues("https://dead.com", result)
    assert any("404" in i for i in issues)


def test_analyze_param_preserved():
    result = {
        "original_url": "https://track.com?sub_id=myid123",
        "final_url": "https://casino.com?sub_id=myid123",
        "redirect_chain": ["https://track.com?sub_id=myid123", "https://casino.com?sub_id=myid123"],
        "status_code": 200,
        "response_time_ms": 200,
        "issues": [],
        "info": [],
    }
    issues, info = analyze_link_issues("https://track.com?sub_id=myid123", result)
    assert not any("пропал" in i.lower() for i in issues)
    assert any("на месте" in i.lower() for i in info)


def test_analyze_param_lost():
    result = {
        "original_url": "https://track.com?sub_id=myid123&clickid=abc",
        "final_url": "https://casino.com?sub_id=myid123",
        "redirect_chain": ["https://track.com?sub_id=myid123&clickid=abc", "https://casino.com?sub_id=myid123"],
        "status_code": 200,
        "response_time_ms": 200,
        "issues": [],
        "info": [],
    }
    issues, info = analyze_link_issues("https://track.com?sub_id=myid123&clickid=abc", result)
    assert any("clickid" in i and "ПРОПАЛ" in i for i in issues)


def test_analyze_param_changed():
    result = {
        "original_url": "https://track.com?sub_id=myid",
        "final_url": "https://casino.com?sub_id=replaced",
        "redirect_chain": ["https://track.com?sub_id=myid", "https://casino.com?sub_id=replaced"],
        "status_code": 200,
        "response_time_ms": 200,
        "issues": [],
        "info": [],
    }
    issues, info = analyze_link_issues("https://track.com?sub_id=myid", result)
    assert any("sub_id" in i and "изменён" in i for i in issues)


def test_analyze_macro_param():
    """Macro params like {clickid} should be noted but not flagged as lost."""
    result = {
        "original_url": "https://track.com?clickid={clickid}&mid=123",
        "final_url": "https://casino.com?mid=123",
        "redirect_chain": ["https://track.com?clickid={clickid}&mid=123", "https://casino.com?mid=123"],
        "status_code": 200,
        "response_time_ms": 200,
        "issues": [],
        "info": [],
    }
    issues, info = analyze_link_issues("https://track.com?clickid={clickid}&mid=123", result)
    # clickid is a macro — should NOT be flagged as lost
    assert not any("clickid" in i and "ПРОПАЛ" in i for i in issues)


def test_analyze_too_many_redirects():
    chain = [f"https://hop{i}.com" for i in range(8)]
    result = {
        "original_url": chain[0],
        "final_url": chain[-1],
        "redirect_chain": chain,
        "status_code": 200,
        "response_time_ms": 200,
        "issues": [],
        "info": [],
    }
    issues, info = analyze_link_issues(chain[0], result)
    assert any("редиректов" in i.lower() for i in issues)


def test_analyze_slow_response():
    result = {
        "original_url": "https://a.com",
        "final_url": "https://casino.com",
        "redirect_chain": ["https://a.com", "https://casino.com"],
        "status_code": 200,
        "response_time_ms": 6000,
        "issues": [],
        "info": [],
    }
    issues, info = analyze_link_issues("https://a.com", result)
    assert any("медленно" in i.lower() or "Медленно" in i for i in issues)


def test_determine_status_ok_gambling():
    result = {"issues": [], "info": ["✅ Ссылка работает (казино отдаёт 403)"]}
    assert _determine_status(result) == "ok"


def test_determine_status_dead():
    result = {"issues": ["💀 Страница не найдена (404)"], "info": []}
    assert _determine_status(result) == "dead"


def test_determine_status_suspicious():
    result = {"issues": ["🚩 Параметр sub_id ПРОПАЛ"], "info": []}
    assert _determine_status(result) == "suspicious"


def test_determine_status_no_issues():
    result = {"issues": [], "info": []}
    assert _determine_status(result) == "ok"


@pytest.mark.asyncio
async def test_add_and_get_links(db):
    link = await add_ref_link(db, user_id=12345, url="https://test.com?sub_id=abc")
    assert link.id is not None

    links = await get_user_links(db, 12345)
    assert len(links) == 1


def test_format_check_result_ok():
    link = RefLink(
        id=1, user_id=1, url="https://track.com?mid=250393",
        program_name="Royal Partners", last_status="ok", check_count=1, alerts=[],
    )
    check = RefLinkCheck(
        link_id=1, status_code=403, final_url="https://casino.com?mid=250393",
        redirect_chain=["https://track.com", "https://casino.com"],
        response_time_ms=500, issues=[],
    )
    text = format_check_result(link, check)
    assert "✅" in text
    assert "Royal Partners" in text


def test_format_check_result_with_alerts():
    link = RefLink(
        id=1, user_id=1, url="https://track.com",
        last_status="suspicious", check_count=3,
        alerts=["🚨 Финальный URL изменился!"],
    )
    check = RefLinkCheck(
        link_id=1, status_code=200, final_url="https://other.com",
        redirect_chain=["https://track.com", "https://other.com"],
        response_time_ms=200, issues=["🚩 Параметр sub_id ПРОПАЛ"],
    )
    text = format_check_result(link, check)
    assert "🚩" in text
    assert "История изменений" in text
