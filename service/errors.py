"""Map internal exceptions to visitor-facing bilingual messages. Never leak raw gateway text."""

from __future__ import annotations

FRIENDLY = {
    "blocked": {
        "zh": "仅支持公网 http/https 网址，内网与私有地址会被拒绝。",
        "en": "Only public http/https URLs are allowed. Private and reserved addresses are rejected.",
    },
    "unreachable": {
        "zh": "网站暂时无法访问，请稍后再试或换一个网址。",
        "en": "The website could not be reached. Try again later or use a different URL.",
    },
    "http": {
        "zh": "网站返回了异常状态码，暂时无法体检。",
        "en": "The website returned an unexpected status code.",
    },
    "timeout": {
        "zh": "抓取超时。Demo 单次最长约 75 秒，请换一个更快的网站。",
        "en": "Fetch timed out. The Demo allows about 75 seconds per run.",
    },
    "js_shell": {
        "zh": "该网站需要浏览器渲染（JavaScript），Demo 暂不支持。",
        "en": "This site needs a browser to render JavaScript. The Demo does not support that yet.",
    },
    "not_html": {
        "zh": "目标不是可读网页（可能是图片、JSON 或空页面）。",
        "en": "The target is not a readable web page (image, JSON, or empty).",
    },
    "budget": {
        "zh": "今日 Demo 额度已用完，请明天再来（每天 08:00 北京时间重置）。",
        "en": "Today's Demo quota is used up. It resets at 08:00 Beijing time.",
    },
    "rate_ip": {
        "zh": "同一 IP 每天最多 3 次体检，请明天再来。",
        "en": "Each IP can run 3 checkups per day. Please come back tomorrow.",
    },
    "rate_global": {
        "zh": "今日公开 Demo 名额已满（全站 12 次/天），请明天再来。",
        "en": "The public Demo is full for today (12 runs site-wide). Please come back tomorrow.",
    },
    "llm": {
        "zh": "分析服务暂时繁忙，请稍后再试。",
        "en": "The analysis service is busy. Please try again shortly.",
    },
    "backend": {
        "zh": "后端服务暂不可用，请稍后再试。",
        "en": "The backend is temporarily unavailable. Please try again shortly.",
    },
    "invalid": {
        "zh": "请输入一个有效的公网网址（例如 https://example.com）。",
        "en": "Please enter a valid public URL (for example https://example.com).",
    },
    "generic": {
        "zh": "体检未能完成，请稍后再试。",
        "en": "The checkup could not be completed. Please try again later.",
    },
}


def classify(err: str | BaseException) -> str:
    msg = str(err).lower()
    if "js_shell" in msg:
        return "js_shell"
    if "blocked" in msg or "not allowed" in msg or "non-public" in msg or "private" in msg:
        return "blocked"
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    if "budget" in msg or "quota" in msg or "daily cap" in msg:
        return "budget"
    if "rate" in msg and "ip" in msg:
        return "rate_ip"
    if "rate" in msg and ("global" in msg or "day" in msg):
        return "rate_global"
    if "not html" in msg or "not a readable" in msg or "empty page" in msg:
        return "not_html"
    if "llm" in msg or "gateway" in msg or "429" in msg or "rate limit" in msg:
        return "llm"
    if "http " in msg or "status" in msg:
        return "http"
    if "could not read" in msg or "network" in msg or "unreachable" in msg:
        return "unreachable"
    if "invalid" in msg or "scheme" in msg or "url" in msg:
        return "invalid"
    return "generic"


def friendly(err: str | BaseException, lang: str = "zh") -> dict:
    code = classify(err)
    lang = "en" if lang == "en" else "zh"
    return {"code": code, "message": FRIENDLY[code][lang], "message_zh": FRIENDLY[code]["zh"],
            "message_en": FRIENDLY[code]["en"]}
