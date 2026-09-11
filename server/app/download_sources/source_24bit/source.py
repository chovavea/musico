from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Sequence
from html.parser import HTMLParser
from typing import Any, NamedTuple
from urllib.parse import quote, urljoin, urlparse

import httpx
import structlog

from app.adapters.http.safety import MAX_HOPS, REDIRECT_STATUSES, assert_outbound_url_allowed
from app.domain.matching import is_auto_match
from app.domain.models import (
    AudioQuality,
    DownloadCandidate,
    DownloadResponse,
    TrackRef,
    is_allowed_download_format,
    normalize_audio_format,
)

log = structlog.get_logger(__name__)

UrlGuard = Callable[[str, Sequence[str]], Awaitable[None]]
_DEFAULT_BASE_URL = "https://www.example.invalid"
_SEARCH_API_PATHS = (
    "/api/player/searchOnlineMusicTwo",
    "/api/player/searchOnlineMusicOne",
)
_QUALITY_ROUTES = (
    ("a", 192_000, 24),
    ("c", 96_000, 24),
    ("b", 44_100, 16),
)
_MAX_DETAIL_RESULTS = 2
_DETAIL_CONCURRENCY = 3
_AUDIO_URL_RE = re.compile(
    r"https?://[^\"'<>\\\s]+\.(?:flac|wav|dsf)(?:\?[^\"'<>\\\s]*)?",
    re.IGNORECASE,
)
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
# The detail pages answer with this notice once the anonymous daily quota is
# used up; registered visitors can continue after logging in.
_ACCESS_LIMITED_MARKERS = ("今日访问已达限额", "登录后访问")


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        values = dict(attrs)
        self._href = values.get("href") or ""
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href:
            self.links.append((self._href, " ".join(self._text).strip()))
            self._href = ""
            self._text = []


class _PageData(NamedTuple):
    download_url: str | None
    title: str | None
    artist: str | None
    album: str | None
    format: str
    quality: str | None
    size_bytes: int | None


class AriesSource:
    def __init__(
        self,
        client: httpx.AsyncClient,
        config: dict[str, object] | None = None,
        *,
        url_guard: UrlGuard | None = None,
    ) -> None:
        self._client = client
        self._url_guard = url_guard or assert_outbound_url_allowed
        options = config or {}
        self._max_results = max(1, min(int(str(options.get("max_results", 8))), 20))
        self._base_url = _normalize_base_url(options.get("base_url"))
        self._referer = f"{self._base_url}/"
        self._page_hosts = _hosts_for_base_url(self._base_url)

    async def search(self, track: TrackRef) -> list[DownloadCandidate]:
        query = quote(track.title or track.artist, safe="")
        payload = {"keyword": query, "page": 1}
        results: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for path in _SEARCH_API_PATHS:
            try:
                response = await self._post_json(path, payload)
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, ValueError):
                continue
            if not isinstance(data, dict) or not isinstance(data.get("result"), list):
                continue
            for item in data["result"]:
                if not isinstance(item, dict):
                    continue
                source_track_id = str(item.get("id") or "")
                if (
                    not source_track_id
                    or not _ID_RE.fullmatch(source_track_id)
                    or source_track_id in seen_ids
                ):
                    continue
                seen_ids.add(source_track_id)
                results.append(item)
            if any(
                is_auto_match(
                    track,
                    TrackRef(
                        platform="aries",
                        external_id=str(item.get("id")),
                        title=str(item.get("name") or ""),
                        artist=str(item.get("player") or ""),
                    ),
                )
                for item in results
            ):
                break
        exact_results = [
            item
            for item in results
            if is_auto_match(
                track,
                TrackRef(
                    platform="aries",
                    external_id=str(item.get("id")),
                    title=str(item.get("name") or ""),
                    artist=str(item.get("player") or ""),
                ),
            )
        ]
        preferred_ids = {str(item.get("id")) for item in exact_results}
        results = exact_results + [
            item for item in results if str(item.get("id")) not in preferred_ids
        ]
        results = results[: min(self._max_results, _MAX_DETAIL_RESULTS)]
        if not results:
            return []
        semaphore = asyncio.Semaphore(_DETAIL_CONCURRENCY)

        async def load_candidate(
            item: dict[str, Any], route: str
        ) -> DownloadCandidate | None:
            async with semaphore:
                return await self._load_candidate(item, route, track)

        pages = await asyncio.gather(
            *(
                load_candidate(item, route)
                for item in results
                for route, _sample_rate, _bit_depth in _QUALITY_ROUTES
            ),
            return_exceptions=True,
        )
        return [item for item in pages if isinstance(item, DownloadCandidate)]

    async def _load_candidate(
        self,
        item: dict[str, Any],
        route: str,
        track: TrackRef,
    ) -> DownloadCandidate | None:
        source_track_id = str(item.get("id") or "")
        detail_url = f"{self._base_url}/music/{route}/{quote(source_track_id, safe='')}"
        try:
            response = await self._get(
                detail_url,
                headers={"Referer": self._referer},
            )
            response.raise_for_status()
        except (httpx.HTTPError, ValueError):
            return None
        html = response.text
        page_data = _extract_page_data(html, detail_url)
        if not page_data.download_url:
            _log_access_limited(html, detail_url)
            return None
        title = page_data.title or str(item.get("name") or track.title)
        artist = page_data.artist or str(item.get("player") or track.artist)
        album = page_data.album or (str(item.get("album") or "") or None)
        quality = _quality_from_text(
            " ".join(
                value
                for value in (page_data.quality, page_data.format)
                if value
            )
        )
        format_name = normalize_audio_format(page_data.format or "flac")
        if not is_allowed_download_format(format_name):
            return None
        quality = quality.model_copy(
            update={"format": format_name}
        )
        return DownloadCandidate(
            source_id="aries",
            source_track_id=detail_url,
            title=title,
            artist=artist,
            album=album,
            duration_ms=track.duration_ms,
            isrc=track.isrc,
            version=track.version,
            quality=quality,
            source_page_url=detail_url,
            locator={
                "detail_url": detail_url,
                "quality_route": route,
                "expected_size_bytes": page_data.size_bytes,
            },
        )

    async def resolve(
        self,
        candidate: DownloadCandidate,
        *,
        offset: int = 0,
    ) -> DownloadResponse:
        locator = candidate.locator
        detail_url = locator.get("detail_url")
        if not isinstance(detail_url, str) or not detail_url:
            raise ValueError("aries candidate has no resolvable URL")
        response = await self._get(
            detail_url,
            headers={"Referer": self._referer},
        )
        response.raise_for_status()
        download_url = _find_download_url(response.text, detail_url)
        if not download_url:
            _log_access_limited(response.text, detail_url)
            raise ValueError("aries page has no direct download link")
        headers = {"Referer": self._referer}
        if offset > 0:
            headers["Range"] = f"bytes={offset}-"
        return DownloadResponse(url=download_url, headers=headers)

    async def _post_json(self, path: str, payload: dict[str, object]) -> httpx.Response:
        url = urljoin(f"{self._base_url}/", path.lstrip("/"))
        await self._url_guard(url, self._page_hosts)
        return await self._client.post(
            url,
            json=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Referer": self._referer,
            },
            follow_redirects=False,
        )

    async def _get(self, url: str, *, headers: dict[str, str]) -> httpx.Response:
        current_url = url
        for _hop in range(MAX_HOPS):
            await self._url_guard(current_url, self._page_hosts)
            response = await self._client.get(
                current_url,
                headers=headers,
                follow_redirects=False,
            )
            if response.status_code not in REDIRECT_STATUSES:
                return response
            location = response.headers.get("location")
            if not location:
                raise ValueError("aries redirect missing location")
            current_url = urljoin(str(response.url), location)
        raise ValueError("aries page exceeded redirect limit")


def _normalize_base_url(value: object) -> str:
    raw = str(value).strip() if value is not None else ""
    parsed = urlparse(raw or _DEFAULT_BASE_URL)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("download source base_url must be an http(s) URL with a host")
    return f"{parsed.scheme}://{parsed.netloc}"


def _hosts_for_base_url(base_url: str) -> tuple[str, ...]:
    host = (urlparse(base_url).hostname or "").lower().rstrip(".")
    if not host:
        return ("example.invalid", "www.example.invalid")
    hosts = [host]
    if host.startswith("www."):
        hosts.append(host.removeprefix("www."))
    else:
        hosts.append(f"www.{host}")
    return tuple(dict.fromkeys(hosts))


def _log_access_limited(html: str, url: str) -> None:
    if any(marker in html for marker in _ACCESS_LIMITED_MARKERS):
        log.warning("download_source_access_limited", source_id="aries", url=url)


def _find_download_url(html: str, base_url: str) -> str | None:
    parser = _LinkParser()
    normalized = html.replace(r"\/", "/").replace(r"\"", '"')
    parser.feed(normalized)
    for href, _label in parser.links:
        absolute = urljoin(base_url, href.rstrip("\\"))
        if re.search(r"\.(?:flac|wav|dsf)(?:\?|$)", absolute, re.I):
            return absolute
        if "/download" in urlparse(absolute).path.lower() and absolute != base_url:
            return absolute
    matches = _AUDIO_URL_RE.findall(normalized)
    return matches[0] if matches else None


def _extract_page_data(html: str, base_url: str) -> _PageData:
    normalized = html.replace(r"\/", "/").replace(r"\"", '"')
    for match in _AUDIO_URL_RE.finditer(normalized):
        download_url = match.group(0).rstrip("\\")
        start = normalized.rfind("{", 0, match.start())
        end = normalized.find("}", match.end())
        if start < 0 or end < 0:
            continue
        block = normalized[start : end + 1]
        return _PageData(
            download_url=urljoin(base_url, download_url),
            title=_field_from_block(block, "name"),
            artist=_field_from_block(block, "player"),
            album=_field_from_block(block, "album"),
            format=_field_from_block(block, "format") or "flac",
            quality=_field_from_block(block, "quality"),
            size_bytes=_size_from_block(block),
        )
    return _PageData(
        download_url=_find_download_url(html, base_url),
        title=None,
        artist=None,
        album=None,
        format="flac",
        quality=None,
        size_bytes=None,
    )


def _field_from_block(block: str, field_name: str) -> str | None:
    match = re.search(rf'"{re.escape(field_name)}"\s*:\s*"([^"]*)"', block)
    value = match.group(1).strip() if match else ""
    return value or None


def _size_from_block(block: str) -> int | None:
    match = re.search(
        r'"(?:size|filesize|fileSize)"\s*:\s*"?([\d.]+)\s*(MB|GB|B)?"?',
        block,
        re.I,
    )
    if not match:
        return None
    amount = float(match.group(1))
    unit = (match.group(2) or "B").upper()
    multiplier = {"B": 1, "MB": 1024**2, "GB": 1024**3}[unit]
    return int(amount * multiplier)


def _metadata(
    html: str, label: str, fallback: TrackRef
) -> tuple[str, str, str | None, int | None]:
    for block in re.findall(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html,
        re.I | re.S,
    ):
        try:
            data: Any = json.loads(block)
        except json.JSONDecodeError:
            continue
        entries = data if isinstance(data, list) else [data]
        for item in entries:
            if not isinstance(item, dict):
                continue
            title = item.get("name")
            author = item.get("byArtist") or item.get("author")
            artist = author.get("name") if isinstance(author, dict) else author
            if title:
                return (
                    str(title),
                    str(artist or fallback.artist),
                    str(item.get("inAlbum") or "") or None,
                    fallback.duration_ms,
                )
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = label.strip() if label.strip() else (
        re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else fallback.title
    )
    return title or fallback.title, fallback.artist, fallback.album, fallback.duration_ms


def _quality_from_text(text: str) -> AudioQuality:
    lowered = text.lower()
    if ".dsf" in lowered:
        fmt = "dsf"
    elif ".wav" in lowered:
        fmt = "wav"
    else:
        fmt = "flac"
    rate_match = re.search(
        r"(?P<rate>\d+(?:\.\d+)?)\s*(?P<unit>k(?:hz)?|hz)\b", lowered
    )
    bit_match = re.search(r"(16|24|32)\s*bit", lowered)
    sample_rate_hz: int | None = None
    if rate_match:
        rate = float(rate_match.group("rate"))
        sample_rate_hz = (
            int(rate * 1000)
            if rate_match.group("unit").startswith("k")
            else int(rate)
        )
    return AudioQuality(
        format=fmt,
        sample_rate_hz=sample_rate_hz,
        bit_depth=int(bit_match.group(1)) if bit_match else None,
    )


def create_source(
    client: httpx.AsyncClient, config: dict[str, object] | None = None
) -> AriesSource:
    return AriesSource(client, config)
