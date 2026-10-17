"""AI-readiness rubric: 5 dimensions, deterministic checks, reproducible scores.

Scores come only from collected public evidence (no LLM), so anyone can reproduce
them. The LLM is used later to write recommendations, never to set the score.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass

RUBRIC_VERSION = "0.1"


@dataclass(frozen=True)
class Check:
    id: str
    weight: int
    en: str
    zh: str
    fix_en: str
    fix_zh: str
    fn: Callable[[dict, dt.date], tuple[bool, str, str]]  # -> (passed, evidence_url, detail)


def _home(c):
    return c["pages"][0]


def _page(c, role):
    return next((p for p in c["pages"] if p.get("role") == role), None)


def _any(c, key):
    for p in c["pages"]:
        if p.get(key):
            return p
    return None


def _days_since(date_str: str, today: dt.date) -> int | None:
    try:
        return (today - dt.date.fromisoformat(date_str[:10])).days
    except ValueError:
        return None


def _recent_dates(c, today):
    best = None
    for p in c["pages"]:
        for d in p.get("dates", []):
            n = _days_since(d, today)
            if n is not None and 0 <= n and (best is None or n < best[0]):
                best = (n, p["url"], d)
    return best


# ---- check functions -------------------------------------------------------

def _display_len(text: str) -> int:
    """Approximate SERP width: CJK characters count double."""
    return sum(2 if "\u2e80" <= ch <= "\u9fff" or "\uac00" <= ch <= "\ud7af" or "\uff00" <= ch <= "\uffef" else 1
               for ch in text)


def c_title(c, t):
    h = _home(c)
    n = len(h["title"])
    return 10 <= n <= 70, h["url"], f"title length {n}"


def c_meta_desc(c, t):
    h = _home(c)
    n = _display_len(h["meta_description"])
    return 50 <= n <= 170, h["url"], f"meta description width {n} (CJK counts as 2)"


def c_h1(c, t):
    h = _home(c)
    return len(h["h1"]) == 1, h["url"], f"{len(h['h1'])} <h1> on home page"


def c_lang(c, t):
    h = _home(c)
    return bool(h["lang"]), h["url"], f"lang='{h['lang']}'"


def c_canonical(c, t):
    h = _home(c)
    return bool(h["canonical"]), h["url"], "canonical link present" if h["canonical"] else "no canonical link"


def c_sitemap(c, t):
    s = c["sitemap"]
    if not s.get("present"):
        return False, c["origin"] + "/sitemap.xml", "no sitemap found (robots.txt or /sitemap.xml)"
    return True, s.get("url") or c["origin"] + "/sitemap.xml", f"sitemap with {s.get('url_count') or 0} URLs"


def c_robots(c, t):
    return bool(c["robots"].get("present")), c["origin"] + "/robots.txt", "robots.txt found" if c["robots"].get("present") else "no robots.txt"


def c_og(c, t):
    h = _home(c)
    ok = bool(h["og_title"] and h["og_image"])
    return ok, h["url"], "og:title + og:image" if ok else "missing Open Graph title/image"


def c_mobile(c, t):
    h = _home(c)
    return h["has_viewport"], h["url"], "viewport meta" if h["has_viewport"] else "no viewport meta"


def c_https(c, t):
    h = _home(c)
    return h.get("https", False), h["url"], "served over HTTPS" if h.get("https") else "not HTTPS"


def c_copyright(c, t):
    for p in c["pages"]:
        if p.get("copyright_years"):
            y = max(p["copyright_years"])
            return y >= t.year - 1, p["url"], f"copyright year {y}"
    return False, _home(c)["url"], "no copyright year found"


def c_recent_content(c, t):
    best = _recent_dates(c, t)
    if not best:
        return False, _home(c)["url"], "no dated content found"
    return best[0] <= 90, best[1], f"latest date on site {best[2]} ({best[0]} days ago)"


def c_sitemap_fresh(c, t):
    s = c["sitemap"]
    lm = s.get("latest_lastmod")
    if not lm:
        return False, s.get("url") or c["origin"] + "/sitemap.xml", "no <lastmod> in sitemap"
    n = _days_since(lm, t)
    return n is not None and 0 <= n <= 90, s.get("url"), f"sitemap lastmod {lm}"


def c_blog(c, t):
    p = _page(c, "blog")
    return p is not None, (p or _home(c))["url"], "blog/news page found" if p else "no blog/news page linked from home"


def c_contact_page(c, t):
    p = _page(c, "contact")
    return p is not None, (p or _home(c))["url"], "contact page found" if p else "no contact page linked from home"


def c_email(c, t):
    p = _any(c, "emails")
    return p is not None, (p or _home(c))["url"], ", ".join(p["emails"][:2]) if p else "no public email"


def c_phone(c, t):
    p = _any(c, "phones")
    return p is not None, (p or _home(c))["url"], "tel: link found" if p else "no click-to-call phone"


def c_form(c, t):
    p = next((x for x in c["pages"] if x.get("forms", 0) > 0 and x.get("form_fields", 0) >= 2), None)
    return p is not None, (p or _home(c))["url"], "lead/contact form found" if p else "no online form"


def c_chat(c, t):
    p = _any(c, "chat_widgets")
    return p is not None, (p or _home(c))["url"], ", ".join(p["chat_widgets"]) if p else "no chat widget"


def c_booking(c, t):
    p = _any(c, "booking_widgets")
    return p is not None, (p or _home(c))["url"], ", ".join(p["booking_widgets"]) if p else "no online booking"


def c_social(c, t):
    names = set()
    url = _home(c)["url"]
    for p in c["pages"]:
        names.update(k for k in p.get("social", {}))
    return len(names) >= 2, url, ", ".join(sorted(names)) or "no social profiles linked"


def c_analytics(c, t):
    keys = {"google_analytics", "google_tag_manager", "baidu_tongji", "cloudflare_analytics", "meta_pixel"}
    p = next((x for x in c["pages"] if keys & set(x.get("tech", []))), None)
    return p is not None, (p or _home(c))["url"], "analytics detected" if p else "no analytics detected"


def c_jsonld(c, t):
    p = _any(c, "jsonld_types")
    return p is not None, (p or _home(c))["url"], ", ".join(p["jsonld_types"][:5]) if p else "no JSON-LD structured data"


def c_org_schema(c, t):
    want = {"Organization", "LocalBusiness", "Corporation", "ProfessionalService", "Store", "Restaurant"}
    p = next((x for x in c["pages"] if want & set(x.get("jsonld_types", []))), None)
    return p is not None, (p or _home(c))["url"], "Organization/LocalBusiness schema" if p else "no Organization schema"


def c_llms(c, t):
    return c["llms_txt"]["present"], c["origin"] + "/llms.txt", "llms.txt found" if c["llms_txt"]["present"] else "no llms.txt"


def c_ai_policy(c, t):
    r = c["robots"]
    blocked = r.get("ai_bots_blocked", [])
    ok = r.get("present") and (len(blocked) < 5 or bool(r.get("mentions_ai_bots")))
    detail = f"AI crawlers blocked: {', '.join(blocked) or 'none'}"
    return bool(ok), c["origin"] + "/robots.txt", detail


def c_alt(c, t):
    imgs = sum(p.get("images", 0) for p in c["pages"])
    alts = sum(p.get("images_with_alt", 0) for p in c["pages"])
    if imgs == 0:
        return True, _home(c)["url"], "no images"
    return alts / imgs >= 0.8, _home(c)["url"], f"{alts}/{imgs} images have alt text"


def c_ssr(c, t):
    h = _home(c)
    return not c.get("js_shell_suspected"), h["url"], f"~{h['word_count']} words server-rendered"


def c_faq(c, t):
    p = _page(c, "faq")
    if not p:
        p = next((x for x in c["pages"] if "FAQPage" in x.get("jsonld_types", [])), None)
    return p is not None, (p or _home(c))["url"], "FAQ content found" if p else "no FAQ page"


def c_pricing(c, t):
    p = _page(c, "pricing")
    return p is not None, (p or _home(c))["url"], "pricing page found" if p else "no pricing page"


def c_products(c, t):
    p = _page(c, "products")
    return p is not None, (p or _home(c))["url"], "products/services page found" if p else "no products/services page"


def c_cases(c, t):
    p = _page(c, "cases")
    return p is not None, (p or _home(c))["url"], "case studies found" if p else "no case studies"


def c_multilang(c, t):
    h = _home(c)
    ok = len(h.get("hreflangs", [])) >= 2
    return ok, h["url"], ", ".join(h.get("hreflangs", [])) or "single language"


DIMENSIONS = [
    {
        "id": "discoverability",
        "en": "Site completeness & discoverability",
        "zh": "网站信息完整度与可发现性",
        "checks": [
            Check("title", 2, "Clear page title", "页面标题清楚", "Write a 10–70 character title naming what you sell and where.", "写一个 10–70 字符、说清卖什么和服务哪里的标题。", c_title),
            Check("meta_description", 2, "Meta description", "页面描述", "Add a 50–170 character meta description.", "补一段 50–170 字符的页面描述。", c_meta_desc),
            Check("h1", 1, "One main heading", "一个主标题", "Use exactly one <h1> on the home page.", "首页只保留一个 <h1> 主标题。", c_h1),
            Check("lang", 1, "Language declared", "声明页面语言", "Set <html lang> so search engines and AI know the language.", "在 <html> 上声明 lang 属性。", c_lang),
            Check("canonical", 1, "Canonical URL", "规范网址", "Add a canonical link to avoid duplicate pages.", "加 canonical 链接，避免重复页面。", c_canonical),
            Check("sitemap", 2, "XML sitemap", "XML 站点地图", "Publish /sitemap.xml and reference it in robots.txt.", "发布 /sitemap.xml 并写进 robots.txt。", c_sitemap),
            Check("robots", 1, "robots.txt", "robots.txt", "Publish a robots.txt that states your crawl policy.", "发布 robots.txt 说明抓取规则。", c_robots),
            Check("open_graph", 1, "Share preview (Open Graph)", "分享预览（Open Graph）", "Add og:title and og:image so links look good when shared.", "加 og:title 和 og:image，分享链接更好看。", c_og),
            Check("mobile", 2, "Mobile-ready", "适配手机", "Add a responsive viewport meta tag.", "加响应式 viewport 设置。", c_mobile),
            Check("https", 2, "HTTPS", "HTTPS", "Serve the site over HTTPS.", "全站使用 HTTPS。", c_https),
        ],
    },
    {
        "id": "freshness",
        "en": "Content freshness",
        "zh": "内容更新频率",
        "checks": [
            Check("copyright", 1, "Current copyright year", "版权年份是最新的", "Update the footer year; stale years signal an abandoned site.", "更新页脚年份，旧年份让人觉得网站没人管。", c_copyright),
            Check("recent_content", 3, "Content dated in last 90 days", "近 90 天有新内容", "Publish at least one dated update per month; an agent can draft it.", "每月至少发一条带日期的更新，可以让 Agent 起草。", c_recent_content),
            Check("sitemap_fresh", 1, "Sitemap updated recently", "站点地图最近更新过", "Generate lastmod automatically when pages change.", "页面更新时自动生成 lastmod。", c_sitemap_fresh),
            Check("blog", 2, "News / blog section", "新闻或博客栏目", "Add a news/blog section linked from the home page.", "首页加新闻或博客入口。", c_blog),
        ],
    },
    {
        "id": "touchpoints",
        "en": "Customer touchpoints",
        "zh": "客户触达方式",
        "checks": [
            Check("contact_page", 2, "Contact page", "联系页面", "Link a contact page from the home page.", "首页链接到联系页面。", c_contact_page),
            Check("email", 1, "Public email", "公开邮箱", "Show a business email address.", "公开一个业务邮箱。", c_email),
            Check("phone", 1, "Click-to-call phone", "可点击拨号", "Add a tel: link for mobile visitors.", "加 tel: 链接，手机上点一下就能拨。", c_phone),
            Check("form", 2, "Online enquiry form", "在线咨询表单", "Add an enquiry form so leads arrive structured.", "加在线咨询表单，线索自动结构化。", c_form),
            Check("chat", 2, "Live chat / chatbot", "在线客服或聊天机器人", "Add a chat widget; an AI agent can answer common questions 24/7.", "加在线客服，AI 可以 24 小时回答常见问题。", c_chat),
            Check("booking", 1, "Online booking", "在线预约", "Offer self-service booking for calls or visits.", "提供自助预约。", c_booking),
            Check("social", 1, "Social profiles linked", "链接社交账号", "Link at least two active social profiles.", "至少链接两个活跃的社交账号。", c_social),
            Check("analytics", 1, "Visitor analytics", "访客统计", "Install privacy-friendly analytics to measure leads.", "装一个访客统计工具，衡量线索来源。", c_analytics),
        ],
    },
    {
        "id": "ai_readiness",
        "en": "AI & machine readability",
        "zh": "AI 与机器可读性",
        "checks": [
            Check("jsonld", 2, "Structured data (JSON-LD)", "结构化数据（JSON-LD）", "Add JSON-LD so search engines and AI assistants understand your business.", "加 JSON-LD 结构化数据，让搜索引擎和 AI 助手读懂你的业务。", c_jsonld),
            Check("org_schema", 2, "Organization / LocalBusiness schema", "机构或本地商家结构化数据", "Describe name, address, contact and services in Organization schema.", "用 Organization schema 写清名称、地址、联系方式和服务。", c_org_schema),
            Check("llms_txt", 1, "llms.txt", "llms.txt", "Publish /llms.txt summarising your offer for AI assistants.", "发布 /llms.txt，给 AI 助手一份业务摘要。", c_llms),
            Check("ai_policy", 1, "AI crawler policy", "AI 爬虫策略", "Decide which AI crawlers may read your site and state it in robots.txt.", "决定允许哪些 AI 爬虫，并写进 robots.txt。", c_ai_policy),
            Check("alt_text", 1, "Image alt text", "图片替代文字", "Describe images with alt text (≥80%).", "给 80% 以上的图片写替代文字。", c_alt),
            Check("server_rendered", 2, "Readable without JavaScript", "不依赖 JavaScript 也能读到内容", "Server-render key text so crawlers and AI can read it.", "关键文字用服务端渲染，爬虫和 AI 才读得到。", c_ssr),
            Check("faq", 2, "FAQ content", "常见问题内容", "Publish an FAQ; it doubles as training data for a support agent.", "发布常见问题页，同时可以作为客服 Agent 的知识库。", c_faq),
        ],
    },
    {
        "id": "automation",
        "en": "Automation foundations",
        "zh": "可自动化基础",
        "checks": [
            Check("pricing", 2, "Published pricing / packages", "公开价格或套餐", "Publish packages so an agent can answer quote requests instantly.", "公开套餐，Agent 可以即时回复询价。", c_pricing),
            Check("products", 2, "Products / services pages", "产品或服务页面", "Give each service its own page; it becomes the agent's knowledge base.", "每项服务一个页面，也就是 Agent 的知识库。", c_products),
            Check("cases", 1, "Case studies", "客户案例", "Add case studies; an agent can turn delivery notes into cases.", "加客户案例，Agent 可以把交付记录整理成案例。", c_cases),
            Check("form_capture", 2, "Structured lead capture", "结构化线索收集", "Route form leads into a CRM or sheet automatically.", "表单线索自动进 CRM 或表格。", c_form),
            Check("multilingual", 1, "Multilingual pages", "多语言页面", "Offer a second language; AI translation makes this cheap.", "加第二语言，AI 翻译成本很低。", c_multilang),
        ],
    },
]


def score(collection: dict, today: dt.date | None = None) -> dict:
    """Run all checks. Returns {overall, dimensions:[{id,score,checks:[...]}]}."""
    today = today or dt.date.today()
    dims = []
    for d in DIMENSIONS:
        results, got, total = [], 0, 0
        for ch in d["checks"]:
            try:
                passed, url, detail = ch.fn(collection, today)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                passed, url, detail = False, collection.get("final_url", collection.get("url")), f"check error: {exc}"
            total += ch.weight
            got += ch.weight if passed else 0
            results.append({"id": ch.id, "weight": ch.weight, "passed": bool(passed), "label_en": ch.en,
                            "label_zh": ch.zh, "evidence_url": url, "detail": detail,
                            "fix_en": ch.fix_en, "fix_zh": ch.fix_zh})
        dims.append({"id": d["id"], "label_en": d["en"], "label_zh": d["zh"],
                     "score": round(100 * got / total) if total else 0, "checks": results})
    overall = round(sum(x["score"] for x in dims) / len(dims))
    return {"rubric_version": RUBRIC_VERSION, "overall": overall, "dimensions": dims}


def failed_checks(scored: dict) -> list[dict]:
    """Failed checks sorted by weight (desc), each tagged with its dimension."""
    out = []
    for d in scored["dimensions"]:
        for ch in d["checks"]:
            if not ch["passed"]:
                out.append({**ch, "dimension": d["id"]})
    return sorted(out, key=lambda x: (-x["weight"], x["dimension"]))
