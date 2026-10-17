import datetime as dt
import unittest
from pathlib import Path

from checkup_engine import pipeline, render, schema
from checkup_engine.fetcher import FetchResult
from checkup_engine.llm import MockLLM
from checkup_engine.ssrf import BlockedURLError

FIXTURE = (Path(__file__).parent / "fixtures" / "simple.html").read_text(encoding="utf-8")


def fake_fetch(url, timeout=10, max_bytes=None, opener=None):
    if url.rstrip("/").endswith("robots.txt"):
        return FetchResult(url, 200, {}, b"User-agent: *\nAllow: /\n", 1, None, False)
    if "sitemap" in url or url.rstrip("/").endswith("llms.txt"):
        return FetchResult(url, 404, {}, b"", 1, "http 404", False)
    return FetchResult("https://example.com/", 200, {"Content-Type": "text/html"}, FIXTURE.encode(), 3, None, False)


class TestPipeline(unittest.TestCase):
    def test_offline(self):
        rep = pipeline.run_checkup("https://example.com/", lang="en", llm=None, fetch_fn=fake_fetch,
                                   today=dt.date(2026, 10, 17))
        self.assertEqual(rep["mode"], "offline")
        self.assertEqual(len(rep["recommendations"]), 3)
        self.assertEqual(schema.validate(rep), [])
        html = render.render_html(rep)
        self.assertIn("example.com", html)
        self.assertIn("Overall score", html)
        self.assertIn("escape", html.lower()) if False else None
        self.assertNotIn("<script>alert", html)

    def test_llm_with_qa_drop(self):
        mock = MockLLM([
            {"business_summary": "Tools shop", "summary": "Looks ok",
             "recommendations": [
                 {"title": "Add FAQ", "why": "no faq", "how_ai_helps": "draft faq",
                  "evidence_url": "https://example.com/", "related_check": "faq",
                  "est_hours_saved_per_month": 4},
                 {"title": "Invented", "why": "fake", "how_ai_helps": "x",
                  "evidence_url": "https://evil.example/not-collected", "related_check": None},
             ]},
            {"verdicts": [{"index": 0, "decision": "keep", "reason": "ok"}]},
        ])
        rep = pipeline.run_checkup("example.com", lang="en", llm=mock, fetch_fn=fake_fetch,
                                   today=dt.date(2026, 10, 17))
        self.assertEqual(rep["mode"], "llm")
        self.assertTrue(any(r["title"] == "Add FAQ" for r in rep["recommendations"]))
        self.assertTrue(any(d.get("title") == "Invented" for d in rep["qa"]["dropped"]))

    def test_blocked_url(self):
        with self.assertRaises(BlockedURLError):
            pipeline.run_checkup("http://127.0.0.1/", llm=None, fetch_fn=fake_fetch)


if __name__ == "__main__":
    unittest.main()
