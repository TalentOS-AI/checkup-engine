"""Lightweight HTML page parser (stdlib html.parser) producing structured page facts."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

SOCIAL_HOSTS = {
    "linkedin.com": "linkedin",
    "twitter.com": "x",
    "x.com": "x",
    "facebook.com": "facebook",
    "instagram.com": "instagram",
    "youtube.com": "youtube",
    "tiktok.com": "tiktok",
    "weibo.com": "weibo",
    "xiaohongshu.com": "xiaohongshu",
    "bilibili.com": "bilibili",
    "zhihu.com": "zhihu",
    "douyin.com": "douyin",
    "github.com": "github",
}

# (signal name, regex over raw HTML) for technology / widget detection.
TECH_PATTERNS = [
    ("wordpress", r"wp-content/|wp-includes/"),
    ("shopify", r"cdn\.shopify\.com|Shopify\.theme"),
    ("wix", r"static\.wixstatic\.com|wix\.com"),
    ("squarespace", r"squarespace\.com"),
    ("webflow", r"webflow\.(js|com)"),
    ("nextjs", r"__NEXT_DATA__|/_next/static/"),
    ("nuxt", r"__NUXT__|/_nuxt/"),
    ("astro", r"astro-island|/_astro/"),
    ("react", r"data-reactroot|react-dom"),
    ("google_analytics", r"googletagmanager\.com/gtag|google-analytics\.com"),
    ("google_tag_manager", r"googletagmanager\.com/gtm\.js"),
    ("baidu_tongji", r"hm\.baidu\.com"),
    ("cloudflare_analytics", r"static\.cloudflareinsights\.com"),
    ("meta_pixel", r"connect\.facebook\.net/.*/fbevents\.js"),
]

CHAT_PATTERNS = [
    ("intercom", r"widget\.intercom\.io|intercomSettings"),
    ("crisp", r"client\.crisp\.chat"),
    ("tawk", r"embed\.tawk\.to"),
    ("drift", r"js\.driftt\.com"),
    ("zendesk", r"static\.zdassets\.com"),
    ("hubspot", r"js\.hs-scripts\.com|hubspot"),
    ("tidio", r"code\.tidio\.co"),
    ("livechat", r"cdn\.livechatinc\.com"),
    ("meiqia", r"meiqia\.com"),
    ("53kf", r"53kf\.com"),
    ("udesk", r"udesk\.cn"),
]

BOOKING_PATTERNS = [("calendly", r"calendly\.com"), ("cal_com", r"cal\.com/"), ("hubspot_meetings", r"meetings\.hubspot")]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
YEAR_RE = re.compile(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?((?:19|20)\d{2})", re.I)
DATE_RE = re.compile(r"\b((?:19|20)\d{2})[-/.年](0?[1-9]|1[0-2])[-/.月](0?[1-9]|[12]\d|3[01])")


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self.meta: dict[str, str] = {}
        self.links: list[tuple[str, str]] = []  # (href, anchor text)
        self._a_href: str | None = None
        self._a_text: list[str] = []
        self.canonical = ""
        self.lang = ""
        self.headings: list[tuple[str, str]] = []
        self._heading: str | None = None
        self._heading_text: list[str] = []
        self.images = 0
        self.images_with_alt = 0
        self.forms = 0
        self.form_fields = 0
        self.jsonld: list[str] = []
        self._in_jsonld = False
        self._jsonld_buf: list[str] = []
        self._skip = 0
        self.text_parts: list[str] = []
        self.time_datetimes: list[str] = []
        self.has_viewport = False
        self.hreflangs: list[str] = []
        self.iframes: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "")
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or a.get("http-equiv") or "").lower()
            if key:
                self.meta[key] = a.get("content", "")
            if key == "viewport":
                self.has_viewport = True
        elif tag == "link":
            rel = a.get("rel", "").lower()
            if "canonical" in rel:
                self.canonical = a.get("href", "")
            if "alternate" in rel and a.get("hreflang"):
                self.hreflangs.append(a["hreflang"])
        elif tag == "a":
            self._a_href = a.get("href", "")
            self._a_text = []
        elif tag in ("h1", "h2", "h3"):
            self._heading = tag
            self._heading_text = []
        elif tag == "img":
            self.images += 1
            if a.get("alt", "").strip():
                self.images_with_alt += 1
        elif tag == "form":
            self.forms += 1
        elif tag in ("input", "textarea", "select"):
            if a.get("type", "").lower() not in ("hidden", "submit", "button"):
                self.form_fields += 1
        elif tag == "script":
            if a.get("type", "").lower() == "application/ld+json":
                self._in_jsonld = True
                self._jsonld_buf = []
            else:
                self._skip += 1
        elif tag in ("style", "noscript", "svg"):
            self._skip += 1
        elif tag == "time" and a.get("datetime"):
            self.time_datetimes.append(a["datetime"])
        elif tag == "iframe" and a.get("src"):
            self.iframes.append(a["src"])

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "a" and self._a_href is not None:
            self.links.append((self._a_href, " ".join("".join(self._a_text).split())))
            self._a_href = None
        elif tag in ("h1", "h2", "h3") and self._heading == tag:
            self.headings.append((tag, " ".join("".join(self._heading_text).split())))
            self._heading = None
        elif tag == "script":
            if self._in_jsonld:
                self.jsonld.append("".join(self._jsonld_buf))
                self._in_jsonld = False
            elif self._skip:
                self._skip -= 1
        elif tag in ("style", "noscript", "svg") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._in_jsonld:
            self._jsonld_buf.append(data)
            return
        if self._skip:
            return
        if self._in_title:
            self.title += data
        if self._a_href is not None:
            self._a_text.append(data)
        if self._heading:
            self._heading_text.append(data)
        self.text_parts.append(data)


def _jsonld_types(blobs: list[str]) -> list[str]:
    types: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            t = node.get("@type")
            if isinstance(t, str):
                types.append(t)
            elif isinstance(t, list):
                types.extend(x for x in t if isinstance(x, str))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for blob in blobs:
        try:
            walk(json.loads(blob))
        except (ValueError, TypeError):
            continue
    return sorted(set(types))


def parse_page(html: str, base_url: str) -> dict:
    """Return a dict of page facts. Pure function, safe on malformed HTML."""
    p = _Parser()
    try:
        p.feed(html)
        p.close()
    except Exception:  # noqa: BLE001 - html.parser can raise on pathological input
        pass
    base_host = (urlsplit(base_url).hostname or "").lower().removeprefix("www.")
    internal, external, social, emails, phones = [], [], {}, set(), set()
    for href, text in p.links:
        href = href.strip()
        low = href.lower()
        if low.startswith("mailto:"):
            emails.add(href[7:].split("?")[0])
            continue
        if low.startswith("tel:"):
            phones.add(href[4:])
            continue
        if low.startswith(("javascript:", "#", "data:")) or not href:
            continue
        absu = urljoin(base_url, href).split("#")[0]
        host = (urlsplit(absu).hostname or "").lower().removeprefix("www.")
        if not host:
            continue
        if host == base_host or host.endswith("." + base_host):
            internal.append({"url": absu, "text": text[:120]})
        else:
            external.append(absu)
            for sh, name in SOCIAL_HOSTS.items():
                if host == sh or host.endswith("." + sh):
                    social.setdefault(name, absu)
    text = " ".join(" ".join(p.text_parts).split())
    emails.update(e for e in EMAIL_RE.findall(text) if not e.lower().endswith((".png", ".jpg", ".svg", ".webp")))
    years = [int(y) for y in YEAR_RE.findall(html)]
    dates = [f"{y}-{int(m):02d}-{int(d):02d}" for y, m, d in DATE_RE.findall(text)]
    dates += [d[:10] for d in p.time_datetimes if re.match(r"\d{4}-\d{2}-\d{2}", d)]
    tech = [name for name, rx in TECH_PATTERNS if re.search(rx, html, re.I)]
    gen = p.meta.get("generator", "")
    if gen:
        tech.append("generator:" + gen[:60])
    chat = [name for name, rx in CHAT_PATTERNS if re.search(rx, html, re.I)]
    booking = [name for name, rx in BOOKING_PATTERNS if re.search(rx, html, re.I)]
    if re.search(r"微信|wechat|weixin", text, re.I):
        social.setdefault("wechat", "")
    seen, uniq_internal = set(), []
    for item in internal:
        if item["url"] not in seen:
            seen.add(item["url"])
            uniq_internal.append(item)
    return {
        "url": base_url,
        "title": " ".join(p.title.split())[:300],
        "lang": p.lang,
        "meta_description": p.meta.get("description", "")[:500],
        "og_title": p.meta.get("og:title", ""),
        "og_image": p.meta.get("og:image", ""),
        "twitter_card": p.meta.get("twitter:card", ""),
        "robots_meta": p.meta.get("robots", ""),
        "canonical": p.canonical,
        "has_viewport": p.has_viewport,
        "hreflangs": sorted(set(p.hreflangs)),
        "h1": [t for tag, t in p.headings if tag == "h1"][:5],
        "headings": [t for _tag, t in p.headings][:40],
        "internal_links": uniq_internal[:300],
        "external_link_count": len(set(external)),
        "social": social,
        "emails": sorted(emails)[:10],
        "phones": sorted(phones)[:10],
        "forms": p.forms,
        "form_fields": p.form_fields,
        "images": p.images,
        "images_with_alt": p.images_with_alt,
        "jsonld_types": _jsonld_types(p.jsonld),
        "tech": tech,
        "chat_widgets": chat,
        "booking_widgets": booking,
        "copyright_years": sorted(set(years)),
        "dates": sorted(set(dates))[-20:],
        "word_count": len(text.split()) if not re.search(r"[\u4e00-\u9fff]", text) else len(re.findall(r"[\u4e00-\u9fff]", text)) + len(re.findall(r"[A-Za-z]+", text)),
        "text_excerpt": text[:3000],
        "html_bytes": len(html.encode("utf-8", errors="ignore")),
    }
