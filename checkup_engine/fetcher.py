"""Safe HTTP fetcher (stdlib only).

* Every hop (including redirects) is validated with ``ssrf.validate_url``.
* Sockets connect to the vetted IP returned by ``ssrf.resolve_public``; TLS still
  verifies the certificate against the original hostname (SNI).
* Proxies from the environment are ignored, bodies are capped, total time is capped.
"""

from __future__ import annotations

import http.client
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from . import ssrf

USER_AGENT = "TalentOS-Checkup-Bot/0.1 (+https://www.agentbay.asia; talentos@agentbay.asia)"
MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5


@dataclass
class FetchResult:
    url: str  # final URL after redirects
    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    elapsed_ms: int = 0
    error: str | None = None
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status < 300

    def text(self) -> str:
        ctype = self.headers.get("content-type", "")
        charset = "utf-8"
        if "charset=" in ctype:
            charset = ctype.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def _safe_connect(host: str, port: int, timeout: float | None, resolver=socket.getaddrinfo):
    infos = ssrf.resolve_public(host, port, resolver=resolver)
    last: Exception | None = None
    for family, socktype, proto, _canon, sockaddr in infos:
        sock = socket.socket(family, socktype, proto)
        if timeout is not None:
            sock.settimeout(timeout)
        try:
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last = exc
            sock.close()
    raise OSError(f"could not connect to {host}:{port}: {last}")


class SafeHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = _safe_connect(self.host, self.port, self.timeout)


class SafeHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        sock = _safe_connect(self.host, self.port, self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _SafeHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(SafeHTTPConnection, req)


class _SafeHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self):
        super().__init__(context=ssl.create_default_context())

    def https_open(self, req):
        return self.do_open(SafeHTTPSConnection, req, context=self._context)


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        ssrf.validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def build_opener():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _SafeHTTPHandler(),
        _SafeHTTPSHandler(),
        _SafeRedirectHandler(),
    )


def fetch(url: str, timeout: float = 10.0, max_bytes: int = MAX_BYTES, opener=None) -> FetchResult:
    """GET ``url`` safely. Never raises for network errors; returns FetchResult.error."""
    start = time.monotonic()
    try:
        ssrf.validate_url(url)
    except ssrf.BlockedURLError as exc:
        return FetchResult(url=url, status=0, error=f"blocked: {exc}")
    opener = opener or build_opener()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain,application/xml;q=0.9,*/*;q=0.5",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read(max_bytes + 1)
            truncated = len(body) > max_bytes
            return FetchResult(
                url=resp.geturl(),
                status=resp.status,
                headers={k.lower(): v for k, v in resp.headers.items()},
                body=body[:max_bytes],
                elapsed_ms=int((time.monotonic() - start) * 1000),
                truncated=truncated,
            )
    except urllib.error.HTTPError as exc:
        return FetchResult(
            url=exc.geturl() or url,
            status=exc.code,
            headers={k.lower(): v for k, v in (exc.headers or {}).items()},
            elapsed_ms=int((time.monotonic() - start) * 1000),
            error=f"http {exc.code}",
        )
    except ssrf.BlockedURLError as exc:
        return FetchResult(url=url, status=0, error=f"blocked: {exc}")
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, ssrf.BlockedURLError):
            return FetchResult(url=url, status=0, error=f"blocked: {reason}")
        return FetchResult(
            url=url, status=0, elapsed_ms=int((time.monotonic() - start) * 1000), error=f"network: {reason}"
        )
