"""Multi-agent checkup pipeline: intake -> collect -> score -> analyze -> QA -> report."""

from __future__ import annotations

import datetime as dt
import time

from . import __version__, collectors, prompts, rubric, ssrf
from .llm import LLMError

SCHEMA_VERSION = "0.1"
# DeepSeek V4.1-Flash peak list price (USD / 1M tokens), used only when the gateway returns no cost.
PRICE_IN, PRICE_OUT = 0.30, 1.20

DISCLAIMER = {
    "zh": "本报告由 AI 根据公开网页自动生成，评分规则公开、可复现；建议和节省工时均为估算，仅供参考。",
    "en": "Generated automatically by AI from public web pages. Scores follow a public, reproducible rubric; "
          "recommendations and hours saved are estimates for reference only.",
}


def _rubric_recommendations(failed: list[dict], lang: str, limit: int = 3) -> list[dict]:
    recs, used_dims = [], set()
    for pass_no in (0, 1):
        for f in failed:
            if len(recs) >= limit:
                break
            if f["id"] in [r["related_check"] for r in recs]:
                continue
            if pass_no == 0 and f["dimension"] in used_dims:
                continue
            used_dims.add(f["dimension"])
            recs.append({
                "title": f["label_zh"] if lang == "zh" else f["label_en"],
                "why": f["detail"],
                "how_ai_helps": f["fix_zh"] if lang == "zh" else f["fix_en"],
                "evidence_url": f["evidence_url"],
                "related_check": f["id"],
                "est_hours_saved_per_month": None,
                "source": "rubric",
            })
    return recs


def _clean_llm_recs(raw, evidence: set[str], failed_ids: set[str]) -> tuple[list[dict], list[dict]]:
    kept, dropped = [], []
    for r in (raw or [])[:3]:
        if not isinstance(r, dict):
            continue
        url = str(r.get("evidence_url", "")).strip()
        title = str(r.get("title", "")).strip()[:120]
        if not title or not any(collectors.same_page(url, e) for e in evidence):
            dropped.append({"title": title or "(untitled)", "reason": "evidence_url not in collected pages"})
            continue
        hours = r.get("est_hours_saved_per_month")
        if not isinstance(hours, (int, float)) or isinstance(hours, bool) or not 0 <= hours <= 200:
            hours = None
        rel = r.get("related_check")
        kept.append({
            "title": title,
            "why": str(r.get("why", ""))[:600],
            "how_ai_helps": str(r.get("how_ai_helps", ""))[:600],
            "evidence_url": url,
            "related_check": rel if rel in failed_ids else None,
            "est_hours_saved_per_month": hours,
            "source": "llm",
        })
    return kept, dropped


def run_checkup(url: str, lang: str = "zh", llm=None, fetch_fn=None, progress=None,
                today: dt.date | None = None, max_pages: int = collectors.MAX_EXTRA_PAGES) -> dict:
    """Run a full checkup. ``llm`` may be None (offline mode: rubric-only recommendations)."""
    t0 = time.monotonic()
    lang = "en" if lang == "en" else "zh"

    def say(stage, msg):
        if progress:
            progress(stage, msg)

    say("intake", "validating URL")
    url = ssrf.normalize_url(url)

    say("collect", "collecting public pages")
    col = collectors.collect(url, fetch_fn=fetch_fn, max_pages=max_pages,
                             progress=lambda m: say("collect", m))
    if not col.get("ok"):
        raise CheckupError(f"could not read the website: {col.get('error')}")
    if col.get("js_shell_suspected"):
        words = sum(p.get("word_count") or 0 for p in col.get("pages", []))
        if words < 40:
            raise CheckupError("js_shell: site appears to need a browser; Demo does not render JavaScript")

    say("score", "scoring against rubric")
    scored = rubric.score(col, today=today)
    failed = rubric.failed_checks(scored)
    evidence = collectors.evidence_urls(col)

    mode, business_summary, summary = "offline", "", ""
    qa = {"checked": False, "dropped": []}
    recs: list[dict] = []
    if llm is not None:
        try:
            say("analyze", "analyst agent writing recommendations")
            out = llm.chat_json(prompts.analyst_prompt(col, scored, failed, evidence, lang))
            recs, dropped = _clean_llm_recs(out.get("recommendations"), evidence, {f["id"] for f in failed})
            business_summary = str(out.get("business_summary", ""))[:300]
            summary = str(out.get("summary", ""))[:800]
            qa["dropped"].extend(dropped)
            if recs:
                say("qa", "QA agent checking evidence")
                verdicts = llm.chat_json(prompts.qa_prompt(col, failed, recs), max_tokens=800).get("verdicts", [])
                drop_idx = {v.get("index"): v.get("reason", "") for v in verdicts
                            if isinstance(v, dict) and v.get("decision") == "drop"}
                qa["dropped"].extend({"title": r["title"], "reason": drop_idx[i] or "QA: unsupported"}
                                     for i, r in enumerate(recs) if i in drop_idx)
                recs = [r for i, r in enumerate(recs) if i not in drop_idx]
                qa["checked"] = True
            mode = "llm"
        except LLMError as exc:
            col["notes"].append(f"LLM unavailable, used rubric-only recommendations ({exc})")
            recs = []
    if len(recs) < 3:
        have = {r.get("related_check") for r in recs}
        recs += [r for r in _rubric_recommendations(failed, lang) if r["related_check"] not in have][: 3 - len(recs)]
    if not summary:
        summary = _offline_summary(scored, lang)

    usage = getattr(llm, "usage", None) or {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "cost_usd": 0.0}
    est = usage.get("cost_usd") or (usage["prompt_tokens"] * PRICE_IN + usage["completion_tokens"] * PRICE_OUT) / 1e6
    say("report", "assembling report")
    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": __version__,
        "rubric_version": rubric.RUBRIC_VERSION,
        "url": url,
        "final_url": col["final_url"],
        "lang": lang,
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": mode,
        "business_summary": business_summary,
        "summary": summary,
        "scores": scored,
        "recommendations": recs[:3],
        "collection": {
            "pages": [{"url": p["url"], "role": p.get("role"), "title": p.get("title", ""), "status": p.get("status")}
                      for p in col["pages"]],
            "robots": {k: col["robots"].get(k) for k in ("present", "ai_bots_blocked", "sitemaps")},
            "sitemap": {k: col["sitemap"].get(k) for k in ("present", "url", "url_count", "latest_lastmod")},
            "llms_txt": col["llms_txt"],
            "tech": sorted({t for p in col["pages"] for t in p.get("tech", [])}),
            "notes": col["notes"],
            "elapsed_ms": col["elapsed_ms"],
        },
        "qa": qa,
        "cost": {"llm_calls": usage.get("calls", 0), "prompt_tokens": usage["prompt_tokens"],
                 "completion_tokens": usage["completion_tokens"], "est_cost_usd": round(est, 5),
                 "model": getattr(llm, "model", None)},
        "timing": {"total_ms": int((time.monotonic() - t0) * 1000)},
        "disclaimer": DISCLAIMER[lang],
    }


class CheckupError(RuntimeError):
    pass


def _offline_summary(scored: dict, lang: str) -> str:
    dims = sorted(scored["dimensions"], key=lambda d: d["score"])
    weak, strong = dims[0], dims[-1]
    if lang == "zh":
        return (f"综合得分 {scored['overall']}/100。最强的是「{strong['label_zh']}」（{strong['score']} 分），"
                f"最需要补的是「{weak['label_zh']}」（{weak['score']} 分）。下面三条建议按影响排序。")
    return (f"Overall score {scored['overall']}/100. Strongest: {strong['label_en']} ({strong['score']}); "
            f"weakest: {weak['label_en']} ({weak['score']}). The three recommendations below are ranked by impact.")
