from __future__ import annotations

import asyncio
import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx

from app.domain.models import AudioQuality, DownloadCandidate, DownloadResponse, TrackRef


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


class AriesSource:
    def __init__(self, client: httpx.AsyncClient, config: dict[str, object] | None = None) -> None:
        self._client = client
        options = config or {}
        self._search_template = str(
            options.get("search_url_template", "https://www.example.invalid/search?q={query}")
        )
        self._max_results = max(1, min(int(options.get("max_results", 8)), 20))

    async def search(self, track: TrackRef) -> list[DownloadCandidate]:
        query = quote(f"{track.title} {track.artist}")
        response: httpx.Response | None = None
        for template in (
            self._search_template,
            "https://www.example.invalid/search/{query}",
            "https://www.example.invalid/?q={query}",
        ):
            url = template.format(query=query)
            try:
                response = await self._client.get(
                    url,
                    headers={"Referer": "https://www.example.invalid/"},
                )
                response.raise_for_status()
                break
            except httpx.HTTPError:
                response = None
        if response is None:
            return []
        parser = _LinkParser()
        parser.feed(response.text)
        detail_urls: list[tuple[str, str]] = []
        seen: set[str] = set()
        for href, label in parser.links:
            absolute = urljoin(str(response.url), href)
            parsed = urlparse(absolute)
            if parsed.hostname not in {"example.invalid", "www.example.invalid"}:
                continue
            if not any(marker in parsed.path.lower() for marker in ("song", "music", "detail", "download")):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            detail_urls.append((absolute, label))
            if len(detail_urls) >= self._max_results:
                break
        if not detail_urls:
            return []
        pages = await asyncio.gather(
            *(self._load_candidate(url_item, label, track) for url_item, label in detail_urls),
            return_exceptions=True,
        )
        return [item for item in pages if isinstance(item, DownloadCandidate)]

    async def _load_candidate(
        self,
        detail_url: str,
        label: str,
        track: TrackRef,
    ) -> DownloadCandidate | None:
        try:
            response = await self._client.get(
                detail_url,
                headers={"Referer": "https://www.example.invalid/"},
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return None
        html = response.text
        download_url = _find_download_url(html, detail_url)
        title, artist, album, duration_ms = _metadata(html, label, track)
        quality = _quality_from_text(f"{html} {download_url or ''}")
        return DownloadCandidate(
            source_id="aries",
            source_track_id=detail_url,
            title=title,
            artist=artist,
            album=album,
            duration_ms=duration_ms,
            isrc=track.isrc,
            version=track.version,
            quality=quality,
            source_page_url=detail_url,
            locator={"detail_url": detail_url, "download_url": download_url},
        )

    async def resolve(
        self,
        candidate: DownloadCandidate,
        *,
        offset: int = 0,
    ) -> DownloadResponse:
        locator = candidate.locator
        download_url = locator.get("download_url")
        if not isinstance(download_url, str) or not download_url:
            detail_url = locator.get("detail_url")
            if not isinstance(detail_url, str) or not detail_url:
                raise ValueError("aries candidate has no resolvable URL")
            response = await self._client.get(
                detail_url,
                headers={"Referer": "https://www.example.invalid/"},
            )
            response.raise_for_status()
            download_url = _find_download_url(response.text, detail_url)
        if not download_url:
            raise ValueError("aries page has no direct download link")
        headers = {"Referer": "https://www.example.invalid/"}
        if offset > 0:
            headers["Range"] = f"bytes={offset}-"
        return DownloadResponse(url=download_url, headers=headers)


def _find_download_url(html: str, base_url: str) -> str | None:
    parser = _LinkParser()
    parser.feed(html)
    for href, _label in parser.links:
        absolute = urljoin(base_url, href)
        if re.search(r"\.(?:flac|wav|dsf|dff)(?:\?|$)", absolute, re.I):
            return absolute
        if "/download" in urlparse(absolute).path.lower() and absolute != base_url:
            return absolute
    matches = re.findall(r"https?://[^\"'<> ]+\.(?:flac|wav|dsf|dff)(?:\?[^\"'<> ]*)?", html, re.I)
    return matches[0] if matches else None


def _metadata(html: str, label: str, fallback: TrackRef) -> tuple[str, str, str | None, int | None]:
    for block in re.findall(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", html, re.I | re.S):
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
                return str(title), str(artist or fallback.artist), str(item.get("inAlbum") or "") or None, fallback.duration_ms
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = label.strip() if label.strip() else (
        re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else fallback.title
    )
    return title or fallback.title, fallback.artist, fallback.album, fallback.duration_ms


def _quality_from_text(text: str) -> AudioQuality:
    lowered = text.lower()
    if ".dsf" in lowered:
        fmt = "dsf"
    elif ".dff" in lowered:
        fmt = "dff"
    elif ".wav" in lowered:
        fmt = "wav"
    else:
        fmt = "flac"
    rate_match = re.search(r"(\d{2,3})\s*k(?:hz)?", lowered)
    bit_match = re.search(r"(16|24|32)\s*bit", lowered)
    return AudioQuality(
        format=fmt,
        sample_rate_hz=int(rate_match.group(1)) * 1000 if rate_match else None,
        bit_depth=int(bit_match.group(1)) if bit_match else 24,
    )


def create_source(client: httpx.AsyncClient, config: dict[str, object] | None = None) -> AriesSource:
    return AriesSource(client, config)
