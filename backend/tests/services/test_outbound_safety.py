from __future__ import annotations

import pytest
from app.adapters.http.safety import (
    OutboundUrlError,
    assert_outbound_url_allowed,
    host_matches,
)


@pytest.mark.asyncio
async def test_host_matches_is_suffix_based() -> None:
    allowed = ("example.invalid", "music.126.net")
    assert host_matches("example.invalid", allowed)
    assert host_matches("www.example.invalid", allowed)
    assert host_matches("m801.music.126.net", allowed)
    assert not host_matches("example.invalid.evil.com", allowed)
    assert not host_matches("qq.com", allowed)
    assert not host_matches("", allowed)


@pytest.mark.asyncio
async def test_rejects_non_http_scheme_and_missing_host() -> None:
    with pytest.raises(OutboundUrlError, match="http or https"):
        await assert_outbound_url_allowed("file:///etc/passwd", ("example.invalid",))
    with pytest.raises(OutboundUrlError, match="no host"):
        await assert_outbound_url_allowed("https://", ("example.invalid",))


@pytest.mark.asyncio
async def test_rejects_host_outside_allowlist() -> None:
    with pytest.raises(OutboundUrlError, match="not allowed"):
        await assert_outbound_url_allowed("https://evil.example.com/x.flac", ("example.invalid",))


@pytest.mark.asyncio
async def test_rejects_private_and_loopback_literal_ips() -> None:
    for host in ("127.0.0.1", "169.254.169.254", "10.0.0.5", "192.168.1.1", "[::1]"):
        with pytest.raises(OutboundUrlError, match="not public"):
            await assert_outbound_url_allowed(f"http://{host}/x.flac", (host.strip("[]"),))


@pytest.mark.asyncio
async def test_accepts_public_literal_ip() -> None:
    await assert_outbound_url_allowed("http://1.1.1.1/x.flac", ("1.1.1.1",))
    await assert_outbound_url_allowed("http://8.8.8.8/x.flac", ())


@pytest.mark.asyncio
async def test_rejects_hostname_resolving_to_private_ip() -> None:
    async def resolver(_hostname: str) -> list[str]:
        return ["169.254.169.254"]

    with pytest.raises(OutboundUrlError, match="not public"):
        await assert_outbound_url_allowed(
            "https://metadata.internal/x.flac",
            ("metadata.internal",),
            resolver=resolver,
        )


@pytest.mark.asyncio
async def test_accepts_hostname_resolving_to_public_ip() -> None:
    async def resolver(hostname: str) -> list[str]:
        assert hostname == "cdn.example.invalid"
        return ["93.184.216.34"]

    await assert_outbound_url_allowed(
        "https://cdn.example.invalid/x.flac",
        ("example.invalid",),
        resolver=resolver,
    )


@pytest.mark.asyncio
async def test_allowlist_applies_before_resolution() -> None:
    async def resolver(_hostname: str) -> list[str]:
        raise AssertionError("resolver should not run for non-allowlisted host")

    with pytest.raises(OutboundUrlError, match="not allowed"):
        await assert_outbound_url_allowed(
            "https://evil.example.com/x.flac",
            ("example.invalid",),
            resolver=resolver,
        )
