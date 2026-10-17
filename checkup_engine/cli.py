"""Command line: python -m checkup_engine https://example.com --lang en --out report.html"""

from __future__ import annotations

import argparse
import json
import sys

from . import llm as llm_mod
from .pipeline import CheckupError, run_checkup
from .render import render_html
from .schema import validate
from .ssrf import BlockedURLError


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="checkup-engine", description="Run an AI-readiness checkup on a public website.")
    ap.add_argument("url")
    ap.add_argument("--lang", choices=["zh", "en"], default="zh")
    ap.add_argument("--out", help="write HTML report to this path")
    ap.add_argument("--json", dest="json_out", help="write JSON report to this path ('-' for stdout)")
    ap.add_argument("--offline", action="store_true", help="skip LLM calls (rubric-only recommendations)")
    ap.add_argument("--max-pages", type=int, default=8)
    args = ap.parse_args(argv)

    client = None
    if not args.offline:
        try:
            client = llm_mod.OpenAICompatClient()
        except llm_mod.LLMError as exc:
            print(f"[checkup] {exc}; running offline", file=sys.stderr)

    def progress(stage, msg):
        print(f"[{stage}] {msg}", file=sys.stderr)

    try:
        report = run_checkup(args.url, lang=args.lang, llm=client, progress=progress, max_pages=args.max_pages)
    except (BlockedURLError, CheckupError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    errors = validate(report)
    if errors:
        print("schema errors: " + "; ".join(errors), file=sys.stderr)
        return 3
    if args.json_out == "-":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(render_html(report))
    print(f"overall {report['scores']['overall']}/100 · mode={report['mode']} · "
          f"{report['timing']['total_ms']} ms", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
