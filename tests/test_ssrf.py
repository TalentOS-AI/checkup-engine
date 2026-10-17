import unittest

from checkup_engine import ssrf


class TestSSRF(unittest.TestCase):
    def test_blocks_schemes(self):
        for u in ("file:///etc/passwd", "ftp://x", "gopher://x", "javascript:alert(1)"):
            with self.assertRaises(ssrf.BlockedURLError):
                ssrf.validate_url(u)

    def test_blocks_credentials_and_ports(self):
        with self.assertRaises(ssrf.BlockedURLError):
            ssrf.validate_url("https://user:pass@example.com/")
        with self.assertRaises(ssrf.BlockedURLError):
            ssrf.validate_url("https://example.com:8080/")

    def test_blocks_localhost_names(self):
        for h in ("http://localhost/", "http://localhost.localdomain/", "http://foo.local/",
                  "http://x.internal/", "http://y.lan/"):
            with self.assertRaises(ssrf.BlockedURLError):
                ssrf.validate_url(h)

    def test_blocks_literal_private_ips(self):
        for ip in ("127.0.0.1", "10.0.0.1", "192.168.1.1", "172.16.0.1", "169.254.1.1",
                   "0.0.0.0", "100.64.0.1", "198.18.0.1", "::1", "fc00::1"):
            with self.assertRaises(ssrf.BlockedURLError):
                ssrf.validate_url(f"http://{ip}/")

    def test_blocks_numeric_host(self):
        with self.assertRaises(ssrf.BlockedURLError):
            ssrf.validate_url("http://2130706433/")  # 127.0.0.1

    def test_normalize_adds_https(self):
        self.assertTrue(ssrf.normalize_url("example.com").startswith("https://"))

    def test_resolve_rejects_any_private(self):
        def fake(host, port, type=None):
            return [(2, 1, 6, "", ("8.8.8.8", port)), (2, 1, 6, "", ("127.0.0.1", port))]
        with self.assertRaises(ssrf.BlockedURLError):
            ssrf.resolve_public("example.com", 443, resolver=fake)

    def test_resolve_accepts_public(self):
        def fake(host, port, type=None):
            return [(2, 1, 6, "", ("1.1.1.1", port))]
        infos = ssrf.resolve_public("example.com", 443, resolver=fake)
        self.assertEqual(infos[0][4][0], "1.1.1.1")


if __name__ == "__main__":
    unittest.main()
