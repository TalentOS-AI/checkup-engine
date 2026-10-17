"""Tess REJ-* cases from strategy/ccmf/tech/test-sites.md §3 (URL validation only)."""
import unittest
from checkup_engine import ssrf


class TestTessRejects(unittest.TestCase):
    CASES = [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://127.1/",
        "http://2130706433/",
        "http://0x7f000001/",
        "http://0.0.0.0/",
        "http://10.0.0.1/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[fd00::1]/",
        "file:///etc/passwd",
        "ftp://ftp.example.com/",
        "gopher://x/",
        "data:text/html,hi",
        "javascript:alert(1)",
        "http://user:pass@example.com/",
        "http://example.com:8080/",
        "https://example.com:22/",
        "http://100.64.0.1/",
        "http://198.18.0.1/",
        "http://224.0.0.1/",
        "http://255.255.255.255/",
        "asdfghjkl",
        "http://",
        "https://.com",
        "",
        "   ",
    ]

    def test_all_rejected(self):
        for raw in self.CASES:
            with self.subTest(raw=raw):
                with self.assertRaises(ssrf.BlockedURLError):
                    ssrf.normalize_url(raw)

    def test_overlong(self):
        with self.assertRaises(ssrf.BlockedURLError):
            ssrf.normalize_url("https://example.com/" + ("a" * 5000))

    def test_public_ok(self):
        self.assertTrue(ssrf.normalize_url("https://example.com/").startswith("https://"))


if __name__ == "__main__":
    unittest.main()
