import time
import unittest
from pathlib import Path

from checkup_engine import monitor
from service import errors


class TestMonitor(unittest.TestCase):
    def test_parsers(self):
        gt = Path("/tmp/gt.html")
        hn = Path("/tmp/hn.html")
        if gt.exists():
            repos = monitor.parse_github_trending(gt.read_text(encoding="utf-8", errors="ignore"))
            self.assertGreaterEqual(len(repos), 5)
            self.assertIn("/", repos[0]["repo"])
        if hn.exists():
            items = monitor.parse_hn(hn.read_text(encoding="utf-8", errors="ignore"))
            self.assertGreaterEqual(len(items), 5)
            self.assertTrue(items[0]["url"].startswith("http"))

    def test_diff(self):
        prev = {"site": {"overall": 40, "checks": {"a.b": False}, "pages": {"https://x/": "aaa"}},
                "github_trending": [{"repo": "old/x", "stars_today": 1}],
                "hn": [{"id": "1", "title": "t", "url": "https://a", "points": 1, "discussion": "https://n"}]}
        cur = {"date": "2026-10-17", "site": {"overall": 50, "dimensions": {}, "url": "https://x/",
                "checks": {"a.b": True}, "pages": {"https://x/": "bbb", "https://x/new": "ccc"}},
               "github_trending": [{"repo": "new/y", "stars_today": 9, "url": "https://github.com/new/y",
                                    "description": "", "language": ""}],
               "hn": [{"id": "2", "title": "n", "url": "https://b", "points": 2, "discussion": "https://n"}],
               "errors": []}
        d = monitor.diff(prev, cur)
        self.assertEqual(d["site"]["checks_fixed"], ["a.b"])
        self.assertEqual(d["github_new"][0]["repo"], "new/y")
        self.assertEqual(d["hn_new"][0]["id"], "2")


class TestFriendlyErrors(unittest.TestCase):
    def test_never_leaks_gateway(self):
        f = errors.friendly("LLM call failed: http 429 rate limit from deepseek upstream xyz", "zh")
        self.assertEqual(f["code"], "llm")
        self.assertNotIn("429", f["message"])
        self.assertNotIn("deepseek", f["message"].lower())


class TestServiceTokens(unittest.TestCase):
    def test_hmac_roundtrip(self):
        import hashlib
        import hmac
        secret = b"hmac-secret"
        def sign(job_id, exp):
            return hmac.new(secret, f"{job_id}|{exp}".encode(), hashlib.sha256).hexdigest()
        exp = int(time.time()) + 60
        sig = sign("abc", exp)
        self.assertTrue(hmac.compare_digest(sign("abc", exp), sig))
        self.assertFalse(hmac.compare_digest(sign("abc", exp - 120), sig))


if __name__ == "__main__":
    unittest.main()
