#!/usr/bin/env python3
"""Produce one day of the sample monitoring daily report.

Usage:  python3 scripts/daily_sample.py [--site https://www.agentbay.asia/] [--out samples] [--no-llm]
Writes  samples/YYYY-MM-DD/{snapshot.json, daily.md, daily.html}; diffs against the latest earlier day.
Uses the LLM for 3 highlights only if GATEWAY_CHECKUP_KEY is set (and --no-llm is not given).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from checkup_engine import llm as llm_mod  # noqa: E402
from checkup_engine import monitor  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="https://www.agentbay.asia/")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "samples"))
    ap.add_argument("--date", help="override date (YYYY-MM-DD), mainly for tests")
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args()

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    out = Path(args.out)
    day_dir = out / today.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)

    prev = None
    earlier = sorted(p for p in out.glob("????-??-??") if p.name < today.isoformat() and (p / "snapshot.json").exists())
    if earlier:
        prev = json.loads((earlier[-1] / "snapshot.json").read_text(encoding="utf-8"))

    cur = monitor.take_snapshot(args.site, today=today)
    d = monitor.diff(prev, cur)

    highlights = None
    if not args.no_llm:
        try:
            highlights = monitor.llm_highlights(llm_mod.OpenAICompatClient(), cur, d)
        except llm_mod.LLMError as exc:
            print(f"[daily] no LLM highlights: {exc}", file=sys.stderr)

    md = monitor.render_markdown(cur, d, highlights)
    (day_dir / "snapshot.json").write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
    (day_dir / "daily.md").write_text(md, encoding="utf-8")
    (day_dir / "daily.html").write_text(monitor.render_html(md, f"TalentOS 监测日报 {today}"), encoding="utf-8")
    print(f"[daily] wrote {day_dir} (errors: {len(cur['errors'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
