import logging
import time
import re
from datetime import datetime
from urllib.parse import urlparse, parse_qs
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.features import RefLink, RefLinkCheck

logger = logging.getLogger(__name__)
GAMBLING_OK_STATUSES = {401, 403, 406, 503}
KNOWN_TRACKER_DOMAINS = {"trk.", "track.", "click.", "go.", "rdr.", "redirect.", "aff.", "partner.", "promo.", "offer.", "ref."}
TRACKER_PARAMS = {"sub_id", "subid", "sub1", "sub2", "sub3", "sub4", "sub5", "clickid", "click_id", "clid", "aff_id", "affiliate_id", "partner_id", "pid", "aid", "ref", "ref_id", "refid", "btag", "stag", "mtag", "tag", "tracker", "tracker_id", "mid", "serial", "creative_id", "anid", "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "tsrc"}
MACRO_PATTERN = re.compile(r'\{[^}]+\}|\[.*?\]|\{\{.*?\}\}')
GAMBLING_KEYWORDS = {"casino", "slot", "bet", "poker", "game", "play", "spin", "jackpot", "bonus", "win", "lucky", "fortune", "777", "bingo", "roulette", "blackjack", "vegas"}
BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}

def _is_macro(value):
    return bool(MACRO_PATTERN.fullmatch(value.strip()))

def _is_gambling_domain(domain):
    return any(kw in domain.lower() for kw in GAMBLING_KEYWORDS)

def _extract_tracking_params(url):
    params = parse_qs(urlparse(url).query, keep_blank_values=True)
    tracking = {}
    for key, values in params.items():
        if key.lower() in TRACKER_PARAMS:
            val = values[0] if values else ""
            tracking[key] = {"value": val, "is_macro": _is_macro(val)}
    return tracking

async def check_link(url, timeout=15):
    result = {"original_url": url, "status_code": None, "final_url": None, "redirect_chain": [], "response_time_ms": 0, "issues": [], "info": []}
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout, headers=BROWSER_HEADERS, verify=False) as client:
            current_url = url
            chain = [current_url]
            for _ in range(15):
                try:
                    resp = await client.get(current_url, follow_redirects=False)
                except httpx.TooManyRedirects:
                    result["issues"].append("🔄 Бесконечный редирект"); break
                except httpx.ConnectError:
                    result["issues"].append(f"❌ Не удалось подключиться к {urlparse(current_url).netloc}"); break
                result["status_code"] = resp.status_code
                if resp.status_code in (301, 302, 303, 307, 308):
                    next_url = resp.headers.get("location", "")
                    if not next_url: break
                    if next_url.startswith("/"): next_url = f"{urlparse(current_url).scheme}://{urlparse(current_url).netloc}{next_url}"
                    elif not next_url.startswith("http"): next_url = f"{urlparse(current_url).scheme}://{urlparse(current_url).netloc}/{next_url}"
                    chain.append(next_url); current_url = next_url
                else: break
            result["final_url"] = current_url; result["redirect_chain"] = chain; result["response_time_ms"] = int((time.monotonic() - start) * 1000)
    except httpx.TimeoutException:
        result["issues"].append("⏰ Таймаут — сайт не отвечает"); result["status_code"] = 0; result["response_time_ms"] = int((time.monotonic() - start) * 1000); return result
    except httpx.ConnectError:
        result["issues"].append("💀 Домен не существует или заблокирован"); result["status_code"] = 0; return result
    except Exception as e:
        result["issues"].append(f"❌ Ошибка: {str(e)[:100]}"); result["status_code"] = 0; return result
    result["issues"], result["info"] = analyze_link_issues(url, result)
    return result

def analyze_link_issues(original_url, check_result):
    issues, info = [], []
    final_url = check_result.get("final_url", "")
    chain = check_result.get("redirect_chain", [])
    status = check_result.get("status_code", 0)
    if status == 0: return issues, info
    final_domain = urlparse(final_url).netloc if final_url else ""
    is_gambling = _is_gambling_domain(final_domain)
    if status >= 500: issues.append(f"💀 Сервер упал (HTTP {status})")
    elif status in GAMBLING_OK_STATUSES:
        if is_gambling or len(chain) > 1: info.append(f"✅ Ссылка работает (казино отдаёт {status} без браузера — норма)")
        else: issues.append(f"⚠️ Сайт отдаёт {status}")
    elif status == 404: issues.append("💀 Страница не найдена (404) — оффер удалён?")
    elif status >= 400: issues.append(f"⚠️ Ошибка HTTP {status}")
    elif status == 200: info.append("✅ Ссылка работает (HTTP 200)")
    num_redirects = len(chain) - 1
    if num_redirects == 0: info.append("↪️ Прямая ссылка, без редиректов")
    elif num_redirects <= 3: info.append(f"↪️ {num_redirects} редирект(а) — нормально")
    elif num_redirects <= 6: issues.append(f"⚠️ Много редиректов ({num_redirects})")
    else: issues.append(f"🚩 Слишком много редиректов ({num_redirects})")
    orig_tracking = _extract_tracking_params(original_url)
    final_tracking = _extract_tracking_params(final_url) if final_url else {}
    params_ok, params_lost, params_changed, params_macro = 0, 0, 0, 0
    for key, orig_data in orig_tracking.items():
        if orig_data["is_macro"]:
            params_macro += 1
            if key in final_tracking: info.append(f"🏷 <b>{key}</b> = макрос ({orig_data['value']}) — передаётся ✓")
            else: info.append(f"🏷 <b>{key}</b> = макрос — обработан трекером")
        else:
            if key not in final_tracking:
                found = any(fk.lower() == key.lower() for fk in final_tracking)
                if not found: params_lost += 1; issues.append(f"🚩 Параметр <b>{key}</b> ({orig_data['value']}) ПРОПАЛ из финального URL")
                else: params_ok += 1
            elif final_tracking[key]["value"] != orig_data["value"]:
                if final_tracking[key]["is_macro"]: issues.append(f"🚩 <b>{key}</b> заменён на макрос: {orig_data['value']} → {final_tracking[key]['value']}"); params_changed += 1
                else: issues.append(f"🚩 <b>{key}</b> изменён: {orig_data['value'][:30]} → {final_tracking[key]['value'][:30]}"); params_changed += 1
            else: params_ok += 1
    if orig_tracking:
        if params_lost > 0 or params_changed > 0: issues.append(f"\n📊 Параметры: {params_ok} ок, {params_lost} потеряно, {params_changed} изменено, {params_macro} макросов")
        else: info.append(f"📊 Все {len(orig_tracking)} параметров на месте ✓")
    if len(chain) > 1:
        domains = list(dict.fromkeys(urlparse(u).netloc for u in chain if urlparse(u).netloc))
        if len(domains) > 1: info.append(f"🔀 Цепочка: {' → '.join(domains)}")
    rt = check_result.get("response_time_ms", 0)
    if rt > 5000: issues.append(f"🐌 Очень медленно: {rt}ms")
    elif rt > 3000: issues.append(f"⚠️ Медленно: {rt}ms")
    elif rt > 0: info.append(f"⚡ Скорость: {rt}ms")
    return issues, info

async def add_ref_link(db, user_id, url, program_name="", geo=""):
    link = RefLink(user_id=user_id, url=url, program_name=program_name, geo=geo)
    db.add(link); await db.commit(); await db.refresh(link); return link

async def get_user_links(db, user_id):
    result = await db.execute(select(RefLink).where(RefLink.user_id == user_id, RefLink.is_active.is_(True)).order_by(RefLink.created_at.desc()))
    return list(result.scalars().all())

async def delete_user_link(db, user_id, link_id):
    result = await db.execute(select(RefLink).where(RefLink.id == link_id, RefLink.user_id == user_id))
    link = result.scalar_one_or_none()
    if not link: return False
    link.is_active = False; await db.commit(); return True

async def check_and_save(db, link):
    result = await check_link(link.url)
    check = RefLinkCheck(link_id=link.id, status_code=result["status_code"], final_url=result["final_url"], redirect_chain=result["redirect_chain"], response_time_ms=result["response_time_ms"], issues=result["issues"])
    db.add(check)
    link.last_status = _determine_status(result)
    link.last_redirect_url = result["final_url"]
    link.last_redirect_chain = result["redirect_chain"]
    link.last_checked_at = datetime.utcnow()
    link.check_count = (link.check_count or 0) + 1
    new_alerts = _detect_changes(link, result)
    if new_alerts: link.alerts = (link.alerts or []) + new_alerts
    await db.commit(); await db.refresh(check); return check

def _determine_status(result):
    issues = result.get("issues", [])
    info = result.get("info", [])
    if any("💀" in i for i in issues): return "dead"
    if any("🚩" in i for i in issues): return "suspicious"
    if any("⚠️" in i for i in issues): return "warning"
    if any("✅" in i for i in info): return "ok"
    if not issues: return "ok"
    return "warning"

def _detect_changes(link, result):
    alerts = []
    if link.last_redirect_url and result["final_url"]:
        if link.last_redirect_url != result["final_url"]:
            alerts.append(f"🚨 Финальный URL изменился!\n   Было: {link.last_redirect_url[:60]}\n   Стало: {result['final_url'][:60]}")
    if link.last_redirect_chain and result["redirect_chain"]:
        if len(link.last_redirect_chain) != len(result["redirect_chain"]):
            alerts.append(f"⚠️ Редиректов было {len(link.last_redirect_chain)-1}, стало {len(result['redirect_chain'])-1}")
        old_domains = [urlparse(u).netloc for u in link.last_redirect_chain]
        new_domains = [urlparse(u).netloc for u in result["redirect_chain"]]
        if old_domains != new_domains: alerts.append("🚨 Цепочка доменов изменилась!")
    return alerts

def format_check_result(link, check):
    status_emoji = {"ok": "✅", "dead": "💀", "suspicious": "🚩", "warning": "⚠️", "unknown": "❓"}
    emoji = status_emoji.get(link.last_status, "❓")
    lines = [f"{emoji} <b>Проверка реф.ссылки</b>\n", f"🔗 <code>{link.url[:80]}</code>"]
    if link.program_name: lines.append(f"📋 ПП: {link.program_name}")
    num_redirects = len(check.redirect_chain or []) - 1
    lines.append(f"↪️ Редиректов: {num_redirects}")
    if check.final_url and check.final_url != link.url: lines.append(f"🎯 Финальный: <code>{check.final_url[:80]}</code>")
    issues = check.issues or []
    if issues:
        lines.append("\n<b>⚠️ Проблемы:</b>")
        for issue in issues: lines.append(issue)
    if not issues and link.last_status == "ok": lines.append("\n✅ Всё в порядке — ссылка работает, параметры на месте")
    if link.alerts:
        lines.append("\n<b>🚨 История изменений:</b>")
        for alert in link.alerts[-3:]: lines.append(alert)
    lines.append(f"\n📊 Проверок: {link.check_count}")
    return "\n".join(lines)
