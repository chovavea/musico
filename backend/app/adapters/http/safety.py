from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from urllib.parse import urlparse

MAX_HOPS = 6
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_SENSITIVE_HEADER_MARKERS = (
    "key",
    "token",
    "secret",
    "password",
    "credential",
    "authorization",
    "cookie",
    "private",
    "certificate",
    "signing",
)


class OutboundUrlError(ValueError):
    """Raised when an outbound URL fails the host allowlist or IP checks."""


HostResolver = Callable[[str], Awaitable[list[str]]]


def host_matches(hostname: str, allowed_hosts: Iterable[str]) -> bool:
    """Suffix allowlist check used by downloads and previews."""
    cleaned = (hostname or "").lower().rstrip(".")
    return any(
        cleaned == host or cleaned.endswith(f".{host}")
        for host in allowed_hosts
    )


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower().rstrip(".")
    port = parsed.port
    if port is None:
        port = {"http": 80, "https": 443}.get(scheme)
    return scheme, hostname, port


def headers_for_redirect(
    headers: dict[str, str], previous_url: str, next_url: str
) -> dict[str, str]:
    """Never forward source credentials to a different origin."""
    if _origin(previous_url) == _origin(next_url):
        return headers
    return {
        name: value
        for name, value in headers.items()
        if name.lower() not in {"host", "proxy-authorization"}
        and not any(marker in name.lower() for marker in _SENSITIVE_HEADER_MARKERS)
    }


def _reject_unsafe_address(address: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise OutboundUrlError(f"invalid outbound address: {address}") from exc
    if (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_reserved
        or parsed.is_unspecified
    ):
        raise OutboundUrlError(f"outbound address is not public: {parsed}")


async def _default_resolver(hostname: str) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise OutboundUrlError(f"cannot resolve outbound host: {hostname}") from exc
    addresses = [str(info[4][0]) for info in infos if len(info) >= 5 and info[4]]
    if not addresses:
        raise OutboundUrlError(f"cannot resolve outbound host: {hostname}")
    return addresses


async def assert_outbound_url_allowed(
    url: str,
    allowed_hosts: Iterable[str] = (),
    *,
    resolver: HostResolver | None = None,
) -> None:
    """Validate that a URL is http(s), host-allowlisted, and not private.

    Literal IP hosts are checked directly; hostnames are resolved and every
    candidate address must be public to avoid DNS-rebinding style SSRF.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise OutboundUrlError("outbound URL must be http or https")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        raise OutboundUrlError("outbound URL has no host")
    allowed = tuple(item.lower().rstrip(".") for item in allowed_hosts)
    if allowed and not host_matches(hostname, allowed):
        raise OutboundUrlError("outbound URL host is not allowed")
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        _reject_unsafe_address(literal)
        return
    resolve = resolver or _default_resolver
    for address in await resolve(hostname):
        _reject_unsafe_address(address)

