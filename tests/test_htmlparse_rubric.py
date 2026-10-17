import datetime as dt
import unittest
from pathlib import Path

from checkup_engine import collectors, htmlparse, rubric
from checkup_engine.fetcher import FetchResult

FIXTURE = (Path(__file__).parent / "fixtures" / "simple.html").read_text(encoding="utf-8")


def fake_fetch(url, timeout=10, max_bytes=None, opener=None):
    u = url.rstrip("/")
    if u.endswith("robots.txt"):
        body = b"User-agent: *\nAllow: /\nSitemap: https://example.com/sitemap.xml\n"
        return FetchResult(url, 200, {"Content-Type": "text/plain"}, body, 1, None, False)
    if u.endswith("sitemap.xml"):
        body = b"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>https://example.com/</loc><lastmod>2026-10-01</lastmod></url>
        <url><loc>https://example.com/about</loc></url>
        <url><loc>https://example.com/blog</loc><lastmod>2026-10-10</lastmod></url>
        </urlset>"""
        return FetchResult(url, 200, {"Content-Type": "application/xml"}, body, 1, None, False)
    if u.endswith("llms.txt"):
        return FetchResult(url, 404, {}, b"", 1, "http 404", False)
    # any page
    return FetchResult(url if "://" in url else "https://example.com/", 200,
                       {"Content-Type": "text/html; charset=utf-8", "Strict-Transport-Security": "max-age=1"},
                       FIXTURE.encode(), 5, None, False)


class TestParseAndScore(unittest.TestCase):
    def test_parse(self):
        p = htmlparse.parse_page(FIXTURE, "https://example.com/")
        self.assertEqual(p["title"][:4], "Acme")
        self.assertTrue(p["has_viewport"])
        self.assertIn("Organization", p["jsonld_types"])
        self.assertGreaterEqual(p["word_count"], 10)
        self.assertTrue(any(link["url"].endswith("/pricing") for link in p["internal_links"]))

    def test_collect_and_score(self):
        col = collectors.collect("https://example.com/", fetch_fn=fake_fetch, max_pages=4)
        self.assertTrue(col["ok"])
        self.assertTrue(col["sitemap"]["present"])
        scored = rubric.score(col, today=dt.date(2026, 10, 17))
        self.assertEqual(len(scored["dimensions"]), 5)
        self.assertGreaterEqual(scored["overall"], 50)
        ids = {c["id"] for d in scored["dimensions"] for c in d["checks"] if c["passed"]}
        self.assertIn("jsonld", ids)
        self.assertIn("https", ids)


if __name__ == "__main__":
    unittest.main()
