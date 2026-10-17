"""Collect a site's public footprint: home page, key pages, robots.txt, sitemap, llms.txt.

``fetch_fn`` is injectable so tests (and the service) can control networking.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from . import fetcher
from .htmlparse import parse_page

AI_BOTS = ["GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "anthropic-ai", "Google-Extended",
           "PerplexityBot", "CCBot", "Bytespider", "Applebot-Extended"]

# Key-page keywords (EN + ZH) -> page role. Order = priority.
PAGE_ROLES = [
    ("about", r"about|company|who-we-are|关于|公司简介|我们"),
    ("contact", r"contact|联系"),
    ("pricing", r"pricing|price|plans|价格|报价|套餐"),
    ("products", r"product|service|solution|产品|服务|方案"),
    ("blog", r"blog|news|insight|article|journal|博客|新闻|资讯|动态"),
    ("faq", r"faq|help|support|常见问题|帮助"),
    ("careers", r"career|jobs|join|hiring|招聘|加入"),
    ("cases", r"case|customer|portfolio|案例|客户"),
]

MAX_EXTRA_PAGES = 8


def origin_of(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, "", "", ""))


def parse_robots(text: str, origin: str) -> dict:
    rp = RobotFileParser()
    rp.parse(text.splitlines())
    ai_blocked = [bot for bot in AI_BOTS if not rp.can_fetch(bot, origin + "/")]
    sitemaps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", text)
    return {"present": True, "ai_bots_blocked": ai_blocked, "sitemaps": sitemaps[:5],
            "mentions_ai_bots": [b for b in AI_BOTS if re.search(re.escape(b), text, re.I)], "_parser": rp}


def parse_sitemap(xml_text: str) -> dict:
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError:
        return {"present": False, "error": "unparseable"}
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"
    locs = [el.text.strip() for el in root.iter(f"{ns}loc") if el.text]
    lastmods = sorted(el.text.strip()[:10] for el in root.iter(f"{ns}lastmod") if el.text)
    return {"present": True, "is_index": root.tag.endswith("sitemapindex"), "url_count": len(locs),
            "latest_lastmod": lastmods[-1] if lastmods else None, "sample_urls": locs[:50]}


def pick_key_pages(home: dict, limit: int = MAX_EXTRA_PAGES) -> list[dict]:
    chosen: dict[str, dict] = {}
    home_url = home["url"].rstrip("/")
    for role, rx in PAGE_ROLES:
        for link in home["internal_links"]:
            u = link["url"]
            if u.rstrip("/") == home_url or u in [c["url"] for c in chosen.values()]:
                continue
            path = urlsplit(u).path.lower()
            if re.search(r"\.(pdf|jpg|jpeg|png|gif|zip|mp4|svg)$", path):
                continue
            if re.search(rx, path) or re.search(rx, link["text"], re.I):
                chosen[role] = {"role": role, "url": u}
                break
        if len(chosen) >= limit:
            break
    return list(chosen.values())


def collect(url: str, fetch_fn=None, max_pages: int = MAX_EXTRA_PAGES, deadline_s: float = 60.0,
            progress=None) -> dict:
    """Collect evidence for ``url``. Returns a JSON-serializable dict."""
    fetch_fn = fetch_fn or fetcher.fetch
    started = time.monotonic()
    notes: list[str] = []

    def say(msg):
        if progress:
            progress(msg)

    say("fetching home page")
    home_res = fetch_fn(url)
    if not home_res.ok:
        return {"ok": False, "url": url, "error": home_res.error or f"http {home_res.status}", "pages": []}
    final_url = home_res.url
    origin = origin_of(final_url)
    home = parse_page(home_res.text(), final_url)
    home["role"] = "home"
    home["status"] = home_res.status
    home["elapsed_ms"] = home_res.elapsed_ms
    home["https"] = final_url.startswith("https://")
    home["security_headers"] = {h: (h in home_res.headers) for h in (
        "strict-transport-security", "content-security-policy", "x-content-type-options")}

    say("reading robots.txt")
    robots = {"present": False, "ai_bots_blocked": [], "sitemaps": [], "mentions_ai_bots": []}
    rp = None
    r = fetch_fn(origin + "/robots.txt")
    if r.ok and "html" not in r.headers.get("content-type", ""):
        robots = parse_robots(r.text(), origin)
        rp = robots.pop("_parser")

    say("reading sitemap")
    sitemap = {"present": False}
    for sm_url in (robots.get("sitemaps") or [])[:1] + [origin + "/sitemap.xml"]:
        if not sm_url.startswith(origin):
            continue
        s = fetch_fn(sm_url)
        if s.ok:
            sitemap = parse_sitemap(s.text())
            sitemap["url"] = sm_url
            if sitemap.get("present"):
                break

    llms = fetch_fn(origin + "/llms.txt")
    llms_txt = {"present": bool(llms.ok and "html" not in llms.headers.get("content-type", "") and llms.body.strip())}

    pages = [home]
    for item in pick_key_pages(home, max_pages):
        if time.monotonic() - started > deadline_s:
            notes.append("deadline reached; skipped remaining pages")
            break
        if rp is not None and not rp.can_fetch(fetcher.USER_AGENT, item["url"]):
            notes.append(f"robots.txt disallows {item['url']}")
            continue
        say(f"reading {urlsplit(item['url']).path or '/'}")
        res = fetch_fn(item["url"])
        if not res.ok:
            notes.append(f"could not fetch {item['url']}: {res.error or res.status}")
            continue
        page = parse_page(res.text(), res.url)
        page["role"] = item["role"]
        page["status"] = res.status
        page["elapsed_ms"] = res.elapsed_ms
        page.pop("internal_links", None)
        pages.append(page)

    js_shell = home["word_count"] < 40 and home["html_bytes"] > 2000
    if js_shell:
        notes.append("home page has very little server-rendered text (likely a JS app); results may be incomplete")
    return {
        "ok": True,
        "url": url,
        "final_url": final_url,
        "origin": origin,
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "robots": robots,
        "sitemap": sitemap,
        "llms_txt": llms_txt,
        "pages": pages,
        "js_shell_suspected": js_shell,
        "notes": notes,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


def evidence_urls(collection: dict) -> set[str]:
    urls = {p["url"] for p in collection.get("pages", [])}
    origin = collection.get("origin")
    if origin:
        if collection.get("robots", {}).get("present"):
            urls.add(origin + "/robots.txt")
        if collection.get("sitemap", {}).get("present") and collection["sitemap"].get("url"):
            urls.add(collection["sitemap"]["url"])
        if collection.get("llms_txt", {}).get("present"):
            urls.add(origin + "/llms.txt")
    return urls


def same_page(a: str, b: str) -> bool:
    return urljoin(a, "").rstrip("/") == urljoin(b, "").rstrip("/")
