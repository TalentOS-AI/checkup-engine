"""Prompt templates (stored as .md files next to this module)."""

from __future__ import annotations

import json
from pathlib import Path

_DIR = Path(__file__).parent / "prompts"
LANG_NAMES = {"zh": "Simplified Chinese", "en": "English"}


def load(name: str) -> str:
    return (_DIR / f"{name}.md").read_text(encoding="utf-8")


def page_digest(collection: dict, max_chars_per_page: int = 1500, max_total: int = 9000) -> str:
    chunks, total = [], 0
    for p in collection.get("pages", []):
        head = f"[{p.get('role', 'page')}] {p['url']}\nTITLE: {p.get('title', '')}\nDESC: {p.get('meta_description', '')}\n"
        body = p.get("text_excerpt", "")[:max_chars_per_page]
        chunk = head + body
        if total + len(chunk) > max_total:
            break
        chunks.append(chunk)
        total += len(chunk)
    return "\n---\n".join(chunks).replace("</untrusted_page_content>", "")


def failed_digest(failed: list[dict], limit: int = 12) -> str:
    return "\n".join(
        f"- {f['id']} (dimension={f['dimension']}, weight={f['weight']}): {f['detail']} | evidence: {f['evidence_url']}"
        for f in failed[:limit]
    ) or "(none)"


def analyst_prompt(collection, scored, failed, evidence_urls, lang) -> str:
    scores = {d["id"]: d["score"] for d in scored["dimensions"]}
    scores["overall"] = scored["overall"]
    return load("analyst").format(
        lang_name=LANG_NAMES.get(lang, "English"),
        url=collection.get("final_url", collection.get("url")),
        scores=json.dumps(scores),
        failed=failed_digest(failed),
        evidence_urls="\n".join(sorted(evidence_urls)),
        pages=page_digest(collection),
    )


def qa_prompt(collection, failed, recommendations) -> str:
    return load("qa").format(
        failed=failed_digest(failed),
        pages=page_digest(collection, max_chars_per_page=800, max_total=5000),
        recommendations=json.dumps(recommendations, ensure_ascii=False, indent=1),
    )
