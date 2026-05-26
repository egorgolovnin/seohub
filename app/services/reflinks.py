import logging
import time
import re
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.features import RefLink, RefLinkCheck

logger = logging.getLogger(__name__)

# Gambling sites return 403/401/406 for bot requests — this is normal
GAMBLING_OK_STATUSES = {401, 403, 406, 503}

# Known tracker/affiliate domains — redirects through these are expected
KNOWN_TRACKER_DOMAINS = {
    "trk.", "track.", "click.", "go.", "rdr.", "redirect.",
    "aff.", "partner.", "promo.", "offer.", "ref.",
}

# All tracking params that matter for affiliate attribution
TRACKER_PARAMS = {
    "sub_id", "subid", "sub1", "sub2", "sub3", "sub4", "sub5",
    "clickid", "click_id", "clid",
    "aff_id", "affiliate_id", "partner_id", "pid", "aid",
    "ref", "ref_id", "refid",
    "btag", "stag", "mtag", "tag",
    "tracker", "tracker_id",
    "mid", "serial", "creative_id", "anid",
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "tsrc",
}

# Macro patterns — these are templates filled by trackers, not actual values
MACRO_PATTERN = re.compile(r'\{[^}]+\}|\[.*?\]|\{\{.*?\}\}')

# Known gambling/betting domain keywords
GAMBLING_KEYWORDS = {
    "casino", "slot", "bet", "poker", "game", "play", "spin",
    "jackpot", "bonus", "win", "lucky", "fortune", "777",
    "bingo", "roulette", "blackjack", "vegas",
}

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}


def _is_macro(value: str) -> bool:
    """Check if value is a tracker macro like {clickid} or [sub_id]."""
    return bool(MACRO_PATTERN.fullmatch(value.strip()))


def _is_gambling_domain(domain: str) -> bool:
    """Check if domain looks like a gambling site."""
    domain_lower = domain.lower()
    return any(kw in domain_lower for kw in GAMBLING_KEYWORDS)


def _is_tracker_domain(domain: str) -> bool:
    """Check if domain is a known tracker/redirect service."""
    domain_lower = domain.lower()
    return any(prefix in domain_lower for prefix in KNOWN_TRACKER_DOMAINS)


def _extract_tracking_params(url: str) -> dict:
    """Extract tracking params from URL, separating real values from macros."""
    params = parse_qs(urlparse(url).query, keep_blank_values=True)
    tracking = {}
    for key, values in params.items():
        if key.lower() in TRACKER_PARAMS:
            val = values[0] if values else ""
            tracking[key] = {
                "value": val,
                "is_macro": _is_macro(val),
            }
    return tracking


async def check_link(url: str, timeout: int = 15) -> dict:
    """Check a referral link with browser-like headers."""
    result = {
        "original_url": url,
        "status_code": None,
        "final_url": None,
        "redirect_chain": [],
        "redirect_codes": [],  # HTTP codes for each redirect step
        "response_time_ms": 0,
        "issues": [],
        "info": [],
        "landing": None,  # landing page analysis
    }

    start = time.monotonic()
    final_response = None
    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=timeout,
            headers=BROWSER_HEADERS,
            verify=False,  # gambling sites often have bad SSL
        ) as client:
            current_url = url
            chain = [current_url]
            codes = []
            max_redirects = 15

            for _ in range(max_redirects):
                try:
                    resp = await client.get(current_url, follow_redirects=False)
                except httpx.TooManyRedirects:
                    result["issues"].append("🔄 Бесконечный редирект — ссылка зациклена")
                    break
                except httpx.ConnectError:
                    result["issues"].append(f"❌ Не удалось подключиться к {urlparse(current_url).netloc}")
                    break

                result["status_code"] = resp.status_code
                codes.append(resp.status_code)

                if resp.status_code in (301, 302, 303, 307, 308):
                    next_url = resp.headers.get("location", "")
                    if not next_url:
                        break
                    if next_url.startswith("/"):
                        parsed = urlparse(current_url)
                        next_url = f"{parsed.scheme}://{parsed.netloc}{next_url}"
                    elif not next_url.startswith("http"):
                        parsed = urlparse(current_url)
                        next_url = f"{parsed.scheme}://{parsed.netloc}/{next_url}"
                    chain.append(next_url)
                    current_url = next_url
                else:
                    final_response = resp
                    break

            result["final_url"] = current_url
            result["redirect_chain"] = chain
            result["redirect_codes"] = codes
            result["response_time_ms"] = int((time.monotonic() - start) * 1000)

    except httpx.TimeoutException:
        result["issues"].append("⏰ Таймаут — сайт не отвечает более 15 секунд")
        result["status_code"] = 0
        result["response_time_ms"] = int((time.monotonic() - start) * 1000)
        return result
    except httpx.ConnectError:
        result["issues"].append("💀 Домен не существует или заблокирован")
        result["status_code"] = 0
        return result
    except Exception as e:
        result["issues"].append(f"❌ Ошибка: {str(e)[:100]}")
        result["status_code"] = 0
        return result

    # Analyze landing page
    if final_response is not None:
        result["landing"] = _analyze_landing(final_response, result["final_url"])

    # Analyze
    result["issues"], result["info"] = analyze_link_issues(url, result)
    return result


def _analyze_landing(resp, url: str) -> dict:
    """Analyze the final landing page."""
    landing = {
        "title": None,
        "has_reg_form": False,
        "language": None,
        "content_length": 0,
        "content_type": None,
        "server": None,
        "is_gambling": False,
    }

    content_type = resp.headers.get("content-type", "")
    landing["content_type"] = content_type.split(";")[0].strip()
    landing["server"] = resp.headers.get("server", None)
    landing["content_length"] = len(resp.content) if resp.content else 0

    # Only parse HTML
    if "text/html" not in content_type:
        return landing

    try:
        body = resp.text[:50000]  # limit parsing
    except Exception:
        return landing

    body_lower = body.lower()

    # Title
    title_match = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    if title_match:
        landing["title"] = title_match.group(1).strip()[:120]

    # Language
    lang_match = re.search(r'<html[^>]*\slang=["\']?([a-zA-Z-]+)', body, re.IGNORECASE)
    if lang_match:
        landing["language"] = lang_match.group(1)

    # Registration form detection
    reg_keywords = ["registration", "register", "sign up", "signup", "reg_form",
                     "регистрация", "зарегистрироваться", "создать аккаунт"]
    if any(kw in body_lower for kw in reg_keywords):
        landing["has_reg_form"] = True
    if re.search(r'<form[^>]*>', body_lower):
        if any(kw in body_lower for kw in ["password", "email", "пароль", "логин"]):
            landing["has_reg_form"] = True

    # Gambling detection
    gambling_words = ["casino", "slot", "bet", "poker", "jackpot", "bonus",
                       "spin", "roulette", "blackjack", "deposit", "казино"]
    gambling_count = sum(1 for w in gambling_words if w in body_lower)
    if gambling_count >= 2:
        landing["is_gambling"] = True

    return landing


def analyze_link_issues(original_url: str, check_result: dict) -> tuple[list[str], list[str]]:
    """Analyze link and return (issues, info)."""
    issues = []
    info = []
    final_url = check_result.get("final_url", "")
    chain = check_result.get("redirect_chain", [])
    status = check_result.get("status_code", 0)

    if status == 0:
        return issues, info

    # --- STATUS CODE ANALYSIS ---
    final_domain = urlparse(final_url).netloc if final_url else ""
    is_gambling = _is_gambling_domain(final_domain)

    if status >= 500:
        issues.append(f"💀 Сервер казино упал (HTTP {status})")
    elif status in GAMBLING_OK_STATUSES:
        if is_gambling or len(chain) > 1:
            # Gambling site blocking direct/bot access — NORMAL
            info.append(f"✅ Ссылка работает (казино отдаёт {status} без браузера — это норма)")
        else:
            issues.append(f"⚠️ Сайт отдаёт {status} — возможно блокировка")
    elif status == 404:
        issues.append("💀 Страница не найдена (404) — оффер удалён или ссылка битая")
    elif status >= 400:
        issues.append(f"⚠️ Ошибка HTTP {status}")
    elif status == 200:
        info.append("✅ Ссылка работает (HTTP 200)")

    # --- REDIRECT ANALYSIS ---
    num_redirects = len(chain) - 1
    if num_redirects == 0:
        info.append("↪️ Без редиректов — прямая ссылка")
    elif num_redirects <= 3:
        info.append(f"↪️ {num_redirects} редирект(а/ов) — нормально")
    elif num_redirects <= 6:
        issues.append(f"⚠️ Много редиректов ({num_redirects}) — может терять параметры")
    else:
        issues.append(f"🚩 Слишком много редиректов ({num_redirects}) — подозрительно")

    # --- TRACKING PARAMS ANALYSIS ---
    orig_tracking = _extract_tracking_params(original_url)
    final_tracking = _extract_tracking_params(final_url) if final_url else {}

    params_ok = 0
    params_macro = 0
    params_lost = 0
    params_changed = 0

    for key, orig_data in orig_tracking.items():
        if orig_data["is_macro"]:
            params_macro += 1
            # Macros like {clickid} — check if key exists in final URL
            if key in final_tracking:
                info.append(f"🏷 <b>{key}</b> = макрос ({orig_data['value']}) — передаётся ✓")
            else:
                # Macro not in final URL — might be consumed by tracker, that's ok
                info.append(f"🏷 <b>{key}</b> = макрос — обработан трекером")
        else:
            # Real value — must survive
            if key not in final_tracking:
                # Check case-insensitive
                found = False
                for fk in final_tracking:
                    if fk.lower() == key.lower():
                        found = True
                        break
                if not found:
                    params_lost += 1
                    issues.append(f"🚩 Параметр <b>{key}</b> ({orig_data['value']}) ПРОПАЛ из финального URL")
                else:
                    params_ok += 1
            elif final_tracking[key]["value"] != orig_data["value"]:
                if final_tracking[key]["is_macro"]:
                    # Value replaced with macro — suspicious
                    issues.append(f"🚩 <b>{key}</b> заменён на макрос: {orig_data['value']} → {final_tracking[key]['value']}")
                    params_changed += 1
                else:
                    issues.append(f"🚩 <b>{key}</b> изменён: {orig_data['value'][:30]} → {final_tracking[key]['value'][:30]}")
                    params_changed += 1
            else:
                params_ok += 1

    # New params in final URL that weren't in original
    new_tracking = {}
    for key, data in final_tracking.items():
        if key not in orig_tracking and not data["is_macro"]:
            new_tracking[key] = data
    if new_tracking:
        added_keys = ", ".join(new_tracking.keys())
        info.append(f"➕ Добавлены параметры: {added_keys}")

    # Summary of params
    if orig_tracking:
        total = len(orig_tracking)
        if params_lost > 0 or params_changed > 0:
            issues.append(f"\n📊 Параметры: {params_ok} ок, {params_lost} потеряно, {params_changed} изменено, {params_macro} макросов")
        else:
            info.append(f"📊 Все {total} параметров на месте ✓")

    # --- DOMAIN CHAIN ANALYSIS ---
    if len(chain) > 1:
        domains_in_chain = []
        for u in chain:
            d = urlparse(u).netloc
            if d and d not in domains_in_chain:
                domains_in_chain.append(d)
        if len(domains_in_chain) > 1:
            chain_str = " → ".join(domains_in_chain)
            info.append(f"🔀 Цепочка: {chain_str}")

    # --- SPEED ---
    response_time = check_result.get("response_time_ms", 0)
    if response_time > 5000:
        issues.append(f"🐌 Очень медленно: {response_time}ms — пользователи могут уходить")
    elif response_time > 3000:
        issues.append(f"⚠️ Медленно: {response_time}ms")
    elif response_time > 0:
        info.append(f"⚡ Скорость: {response_time}ms")

    return issues, info


async def find_existing_link(db: AsyncSession, user_id: int, url: str) -> RefLink | None:
    """Check if user already has this URL on monitoring."""
    result = await db.execute(
        select(RefLink).where(
            RefLink.user_id == user_id,
            RefLink.url == url,
            RefLink.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


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


async def delete_user_link(db: AsyncSession, user_id: int, link_id: int) -> bool:
    result = await db.execute(
        select(RefLink).where(RefLink.id == link_id, RefLink.user_id == user_id)
    )
    link = result.scalar_one_or_none()
    if not link:
        return False
    link.is_active = False
    await db.commit()
    return True


async def check_and_save(db: AsyncSession, link: RefLink) -> RefLinkCheck:
    result = await check_link(link.url)

    check = RefLinkCheck(
        link_id=link.id,
        status_code=result["status_code"],
        final_url=result["final_url"],
        redirect_chain=result["redirect_chain"],
        redirect_codes=result.get("redirect_codes", []),
        response_time_ms=result["response_time_ms"],
        issues=result["issues"],
        landing=result.get("landing"),
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
    info = result.get("info", [])

    # Check for real problems
    if any("💀" in i for i in issues):
        return "dead"
    if any("🚩" in i for i in issues):
        return "suspicious"
    if any("⚠️" in i for i in issues):
        return "warning"
    # If we have info with ✅, it's ok
    if any("✅" in i for i in info):
        return "ok"
    # Gambling 403 with no other issues
    if not issues and info:
        return "ok"
    if not issues:
        return "ok"
    return "warning"


def _detect_changes(link: RefLink, result: dict) -> list[str]:
    alerts = []
    if link.last_redirect_url and result["final_url"]:
        if link.last_redirect_url != result["final_url"]:
            alerts.append(f"🚨 Финальный URL изменился!\n   Было: {link.last_redirect_url[:60]}\n   Стало: {result['final_url'][:60]}")
    if link.last_redirect_chain and result["redirect_chain"]:
        old_len = len(link.last_redirect_chain)
        new_len = len(result["redirect_chain"])
        if old_len != new_len:
            alerts.append(f"⚠️ Редиректов было {old_len-1}, стало {new_len-1}")
        # Check if domains in chain changed
        old_domains = [urlparse(u).netloc for u in link.last_redirect_chain]
        new_domains = [urlparse(u).netloc for u in result["redirect_chain"]]
        if old_domains != new_domains:
            alerts.append(f"🚨 Цепочка доменов изменилась!")
    return alerts


def format_check_result(link: RefLink, check: RefLinkCheck) -> str:
    status_emoji = {"ok": "✅", "dead": "💀", "suspicious": "🚩", "warning": "⚠️", "unknown": "❓"}
    emoji = status_emoji.get(link.last_status, "❓")

    lines = [f"{emoji} <b>Проверка реф.ссылки</b>\n"]
    lines.append(f"🔗 <code>{link.url[:80]}</code>")
    if link.program_name:
        lines.append(f"📋 ПП: {link.program_name}")

    # Redirect chain - full visualization with HTTP codes
    chain = check.redirect_chain or []
    codes = check.redirect_codes if hasattr(check, 'redirect_codes') and check.redirect_codes else []
    num_redirects = max(0, len(chain) - 1)
    lines.append(f"↪️ Редиректов: {num_redirects}")

    if chain:
        lines.append("")
        lines.append("📍 <b>Цепочка:</b>")
        for i, url in enumerate(chain):
            try:
                domain = urlparse(url).netloc
            except Exception:
                domain = url

            # Get HTTP code for this step
            code = codes[i] if i < len(codes) else ""
            code_str = f" ({code})" if code else ""

            if i == 0:
                prefix = f"🟢 START"
            elif i == len(chain) - 1:
                sc = check.status_code or 200
                prefix = f"🔴 {sc}" if sc >= 400 else f"🟢 {sc}"
            else:
                prefix = f"🟡 {code}" if code else "🟡 30x"

            display_url = url if len(url) <= 70 else url[:67] + "..."
            lines.append(f"{prefix}")
            lines.append(f"<code>{display_url}</code>")

            if i < len(chain) - 1:
                try:
                    next_domain = urlparse(chain[i + 1]).netloc
                    if domain != next_domain:
                        lines.append(f"  ↓ <i>{domain} → {next_domain}</i>")
                    else:
                        lines.append("  ↓")
                except Exception:
                    lines.append("  ↓")

    # Landing page analysis
    landing = check.landing if hasattr(check, 'landing') and check.landing else None
    if landing:
        lines.append("")
        lines.append("🌐 <b>Лендинг:</b>")
        if landing.get("title"):
            lines.append(f"📄 {landing['title'][:80]}")
        if landing.get("language"):
            lines.append(f"🗣 Язык: {landing['language']}")
        if landing.get("has_reg_form"):
            lines.append("📝 Форма регистрации: ✅")
        if landing.get("is_gambling"):
            lines.append("🎰 Гемблинг-сайт: ✅")
        size_kb = (landing.get("content_length") or 0) / 1024
        if size_kb > 0:
            lines.append(f"📦 Размер: {size_kb:.0f} KB")

    # Issues (problems)
    issues = check.issues or []
    if issues:
        lines.append("\n<b>Проблемы:</b>")
        for issue in issues:
            lines.append(issue)

    # Show basic info from status
    if not issues:
        if link.last_status == "ok":
            lines.append("\n✅ Всё в порядке — ссылка работает, параметры на месте")

    # Alerts from history
    if link.alerts:
        lines.append("\n<b>🚨 История изменений:</b>")
        for alert in link.alerts[-3:]:
            lines.append(alert)

    lines.append(f"\n📊 Проверок: {link.check_count}")
    if link.last_checked_at:
        lines.append(f"🕐 Последняя: {link.last_checked_at.strftime('%d.%m.%Y %H:%M')}")

    return "\n".join(lines)


async def get_all_active_links(db: AsyncSession) -> list[RefLink]:
    """Get all active links across all users for scheduled checking."""
    result = await db.execute(
        select(RefLink).where(RefLink.is_active.is_(True)).order_by(RefLink.user_id)
    )
    return list(result.scalars().all())


async def set_user_mute(db: AsyncSession, user_id: int, muted: bool) -> int:
    """Mute or unmute alerts for all user's links. Returns count of links affected."""
    result = await db.execute(
        select(RefLink).where(RefLink.user_id == user_id, RefLink.is_active.is_(True))
    )
    links = list(result.scalars().all())
    for link in links:
        link.alerts_muted = muted
    await db.commit()
    return len(links)
