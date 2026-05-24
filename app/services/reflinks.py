import logging
import time
from datetime import datetime
from urllib.parse import urlparse, parse_qs
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.features import RefLink, RefLinkCheck

logger = logging.getLogger(__name__)

KNOWN_ABUSE_PATTERNS = [
    "sub_id замещён",
    "параметр clickid изменён",
    "редирект на другой оффер",
    "параметры удалены из ссылки",
    "домен трекера изменился",
]

TRACKER_PARAMS = {"sub_id", "clickid", "click_id", "aff_id", "partner_id", "pid", "ref", "btag", "stag", "tracker", "utm_source", "utm_medium", "utm_campaign"}


async def check_link(url: str, timeout: int = 15) -> dict:
    """Check a referral link: follow redirects, record chain, detect issues."""
    result = {
        "original_url": url,
        "status_code": None,
        "final_url": None,
        "redirect_chain": [],
        "response_time_ms": 0,
        "issues": [],
    }

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
            current_url = url
            chain = [current_url]
            max_redirects = 10

            for _ in range(max_redirects):
                resp = await client.get(current_url, follow_redirects=False)
                result["status_code"] = resp.status_code

                if resp.status_code in (301, 302, 303, 307, 308):
                    next_url = resp.headers.get("location", "")
                    if not next_url:
                        break
                    if next_url.startswith("/"):
                        parsed = urlparse(current_url)
                        next_url = f"{parsed.scheme}://{parsed.netloc}{next_url}"
                    chain.append(next_url)
                    current_url = next_url
                else:
                    break

            result["final_url"] = current_url
            result["redirect_chain"] = chain
            result["response_time_ms"] = int((time.monotonic() - start) * 1000)

    except httpx.TimeoutException:
        result["issues"].append("⏰ Таймаут — ссылка не отвечает")
        result["status_code"] = 0
        return result
    except httpx.ConnectError:
        result["issues"].append("❌ Не удалось подключиться — домен не существует или заблокирован")
        result["status_code"] = 0
        return result
    except Exception as e:
        result["issues"].append(f"❌ Ошибка: {str(e)[:100]}")
        result["status_code"] = 0
        return result

    # Analyze issues
    result["issues"] = analyze_link_issues(url, result)
    return result


def analyze_link_issues(original_url: str, check_result: dict) -> list[str]:
    """Detect potential issues with the referral link."""
    issues = list(check_result.get("issues", []))
    final_url = check_result.get("final_url", "")
    chain = check_result.get("redirect_chain", [])
    status = check_result.get("status_code", 0)

    # Dead link
    if status == 0:
        return issues
    if status >= 400:
        issues.append(f"❌ Ссылка мертва (HTTP {status})")
        return issues

    # Too many redirects
    if len(chain) > 5:
        issues.append(f"⚠️ Слишком много редиректов ({len(chain)})")

    # Check if tracking params survived
    orig_params = parse_qs(urlparse(original_url).query)
    final_params = parse_qs(urlparse(final_url).query)

    orig_tracking = {k: v for k, v in orig_params.items() if k.lower() in TRACKER_PARAMS}
    final_tracking = {k: v for k, v in final_params.items() if k.lower() in TRACKER_PARAMS}

    for key, values in orig_tracking.items():
        if key not in final_params:
            issues.append(f"🚩 Параметр <b>{key}</b> пропал из ссылки")
        elif final_params[key] != values:
            issues.append(f"🚩 Параметр <b>{key}</b> изменён: {values[0]} → {final_params[key][0]}")

    # Domain change in redirect chain
    orig_domain = urlparse(original_url).netloc
    for i, redirect_url in enumerate(chain[1:], 1):
        redirect_domain = urlparse(redirect_url).netloc
        if redirect_domain and redirect_domain != orig_domain:
            # Check if it's suspicious (not expected tracker domain)
            if i < len(chain) - 1:  # intermediate redirect to unknown domain
                pass  # Normal for trackers
            break

    # Check if final domain looks suspicious
    if final_url:
        final_domain = urlparse(final_url).netloc
        if final_domain and orig_domain and final_domain != orig_domain:
            # This is normal for affiliate links, just note it
            pass

    # Slow response
    response_time = check_result.get("response_time_ms", 0)
    if response_time > 5000:
        issues.append(f"🐌 Медленный ответ: {response_time}ms")

    if not issues:
        issues.append("✅ Ссылка работает корректно")

    return issues


async def add_ref_link(db: AsyncSession, user_id: int, url: str, program_name: str = "", geo: str = "") -> RefLink:
    link = RefLink(user_id=user_id, url=url, program_name=program_name, geo=geo)
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return link


async def get_user_links(db: AsyncSession, user_id: int) -> list[RefLink]:
    result = await db.execute(
        select(RefLink).where(RefLink.user_id == user_id, RefLink.is_active.is_(True)).order_by(RefLink.created_at.desc())
    )
    return list(result.scalars().all())


async def check_and_save(db: AsyncSession, link: RefLink) -> RefLinkCheck:
    result = await check_link(link.url)

    check = RefLinkCheck(
        link_id=link.id,
        status_code=result["status_code"],
        final_url=result["final_url"],
        redirect_chain=result["redirect_chain"],
        response_time_ms=result["response_time_ms"],
        issues=result["issues"],
    )
    db.add(check)

    # Update link status
    link.last_status = _determine_status(result)
    link.last_redirect_url = result["final_url"]
    link.last_redirect_chain = result["redirect_chain"]
    link.last_checked_at = datetime.utcnow()
    link.check_count = (link.check_count or 0) + 1

    # Detect changes from previous check
    new_alerts = _detect_changes(link, result)
    if new_alerts:
        link.alerts = (link.alerts or []) + new_alerts

    await db.commit()
    await db.refresh(check)
    return check


def _determine_status(result: dict) -> str:
    issues = result.get("issues", [])
    if any("мертва" in i or "Не удалось" in i or "Таймаут" in i for i in issues):
        return "dead"
    if any("🚩" in i for i in issues):
        return "suspicious"
    if any("⚠️" in i for i in issues):
        return "warning"
    return "ok"


def _detect_changes(link: RefLink, result: dict) -> list[str]:
    alerts = []
    if link.last_redirect_url and result["final_url"]:
        if link.last_redirect_url != result["final_url"]:
            alerts.append(f"🚨 Финальный URL изменился: {link.last_redirect_url} → {result['final_url']}")
    if link.last_redirect_chain and result["redirect_chain"]:
        if len(link.last_redirect_chain) != len(result["redirect_chain"]):
            alerts.append(f"⚠️ Количество редиректов изменилось: {len(link.last_redirect_chain)} → {len(result['redirect_chain'])}")
    return alerts


def format_check_result(link: RefLink, check: RefLinkCheck) -> str:
    status_emoji = {"ok": "✅", "dead": "💀", "suspicious": "🚩", "warning": "⚠️", "unknown": "❓"}
    emoji = status_emoji.get(link.last_status, "❓")

    lines = [
        f"{emoji} <b>Проверка реф.ссылки</b>\n",
        f"🔗 <code>{link.url[:80]}</code>",
    ]
    if link.program_name:
        lines.append(f"📋 ПП: {link.program_name}")
    lines.append(f"⏱ Ответ: {check.response_time_ms}ms")
    lines.append(f"🔄 Редиректов: {len(check.redirect_chain or []) - 1}")
    if check.final_url and check.final_url != link.url:
        lines.append(f"🎯 Финальный: <code>{check.final_url[:80]}</code>")
    lines.append("")
    for issue in (check.issues or []):
        lines.append(issue)

    if link.alerts:
        lines.append("\n<b>⚠️ Алерты:</b>")
        for alert in link.alerts[-3:]:  # last 3 alerts
            lines.append(alert)

    lines.append(f"\n📊 Проверок: {link.check_count}")
    return "\n".join(lines)
