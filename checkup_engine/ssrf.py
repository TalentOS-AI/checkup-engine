"""SSRF protection: URL validation and IP filtering.

Every outbound request made by the engine goes through ``validate_url`` (scheme,
port, hostname) and every socket connection goes through ``resolve_public`` so
that the address we actually connect to is a public unicast IP. Connecting to
the vetted IP (not re-resolving the hostname) closes the DNS-rebinding gap.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {None, 80, 443}
BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".intranet")

# Ranges that ipaddress does not flag (or flags inconsistently across versions).
_EXTRA_BLOCKED = [
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "100.64.0.0/10",  # CGNAT
        "192.0.0.0/24",
        "192.0.2.0/24",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "255.255.255.255/32",
        "64:ff9b::/96",  # NAT64 can embed private v4
        "100::/64",
        "2001:db8::/32",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
]


class BlockedURLError(ValueError):
    """Raised when a URL or resolved address is not allowed."""


def is_blocked_ip(ip: str) -> bool:
    """True if ``ip`` is not a public unicast address."""
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return True
    if isinstance(addr, ipaddress.IPv6Address):
        mapped = addr.ipv4_mapped or addr.sixtofour
        if mapped is not None:
            return is_blocked_ip(str(mapped))
        if addr.teredo:
            return True
    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        or not addr.is_global
    ):
        return True
    return any(addr in net for net in _EXTRA_BLOCKED if net.version == addr.version)


def normalize_url(raw: str) -> str:
    """Trim, add https:// if no scheme, and validate. Returns the normalized URL."""
    raw = (raw or "").strip()
    if not raw:
        raise BlockedURLError("empty URL")
    if len(raw) > 2048:
        raise BlockedURLError("URL too long")
    if "://" not in raw:
        raw = "https://" + raw
    validate_url(raw)
    return raw


def validate_url(url: str) -> None:
    """Static checks that need no DNS: scheme, credentials, port, hostname."""
    parts = urlsplit(url)
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise BlockedURLError(f"scheme not allowed: {parts.scheme!r}")
    if parts.username or parts.password:
        raise BlockedURLError("credentials in URL not allowed")
    try:
        port = parts.port
    except ValueError as exc:
        raise BlockedURLError("invalid port") from exc
    if port not in ALLOWED_PORTS:
        raise BlockedURLError(f"port not allowed: {port}")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise BlockedURLError("missing hostname")
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES):
        raise BlockedURLError(f"hostname not allowed: {host}")
    try:
        ipaddress.ip_address(host)
        literal = True
    except ValueError:
        literal = False
    if literal:
        if is_blocked_ip(host):
            raise BlockedURLError(f"address not allowed: {host}")
    elif "." not in host:
        raise BlockedURLError(f"hostname must be a public domain: {host}")
    elif host.startswith(".") or host.endswith(".") or ".." in host or any(not lbl for lbl in host.split(".")):
        raise BlockedURLError(f"malformed hostname: {host}")
    elif _looks_numeric(host):
        # e.g. "2130706433" style or octal/hex dotted forms such as 0177.0.0.1
        raise BlockedURLError(f"numeric hostname not allowed: {host}")


def _looks_numeric(host: str) -> bool:
    labels = host.split(".")
    return all(lbl.isdigit() or lbl.lower().startswith("0x") for lbl in labels if lbl)


def resolve_public(host: str, port: int, resolver=socket.getaddrinfo) -> list[tuple]:
    """Resolve ``host`` and return addrinfo entries. Raise if ANY address is blocked.

    Rejecting the whole host when any record is private prevents mixed-record tricks.
    """
    try:
        infos = resolver(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise BlockedURLError(f"cannot resolve {host}") from exc
    if not infos:
        raise BlockedURLError(f"no addresses for {host}")
    fake_ok = _dev_fake_ip_allowed()
    for info in infos:
        ip = info[4][0]
        if fake_ok and _in_fake_ip_range(ip):
            continue
        if is_blocked_ip(ip):
            raise BlockedURLError(f"{host} resolves to a non-public address")
    return infos


_FAKE_IP_NET = ipaddress.ip_network("198.18.0.0/15")


def _dev_fake_ip_allowed() -> bool:
    """DEV ONLY. Some sandboxes route egress through a fake-IP DNS proxy that answers every
    lookup with 198.18.x.x. Setting CHECKUP_DEV_ALLOW_FAKE_IP=1 accepts *DNS answers* in that
    range (literal IPs in URLs are still rejected). Never set this in production."""
    return os.environ.get("CHECKUP_DEV_ALLOW_FAKE_IP") == "1"


def _in_fake_ip_range(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in _FAKE_IP_NET
    except ValueError:
        return False
