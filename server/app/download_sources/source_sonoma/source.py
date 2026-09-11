from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import structlog

from app.adapters.http.safety import REDIRECT_STATUSES, assert_outbound_url_allowed
from app.domain.matching import is_auto_match, track_match_score
from app.domain.models import (
    AudioQuality,
    DownloadCandidate,
    DownloadResponse,
    TrackRef,
    normalize_audio_format,
)

log = structlog.get_logger(__name__)

UrlGuard = Callable[[str, Sequence[str]], Awaitable[None]]

_SOURCE_ID = "sonoma"
_SEARCH_PATH = "/ajax.php?act=search"
_RESOLVE_PATH = "/ajax.php?act=getUrl"
_DEFAULT_MAX_RESULTS = 8
_SEARCH_SIZE = 30
_FLAC_BITRATE = "2000"
_QUALITY_VARIANTS = (("flac", _FLAC_BITRATE),)


class SourceSessionError(ValueError):
    """Raised when the upstream anti-bot/session gate rejects a request."""


class SonomaSource:
    """Adapter for the public search and URL-resolve endpoints of the site.

    The site may require a short-lived browser session.  A session can be
    supplied through an environment variable named by ``cookie_env``; the
    adapter never logs or persists the cookie.  It intentionally does not
    implement or reproduce the site's anti-bot challenge.
    """

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
        self._max_results = max(
            1,
            min(int(str(options.get("max_results", _DEFAULT_MAX_RESULTS))), 20),
        )
        self._base_url = _normalize_base_url(options.get("base_url"))
        self._referer = f"{self._base_url}/"
        self._page_hosts = _hosts_for_base_url(self._base_url)
        self._cookie_env = _normalize_cookie_env(options.get("cookie_env", ""))

    async def search(self, track: TrackRef) -> list[DownloadCandidate]:
        keyword = " ".join(
            value.strip() for value in (track.title, track.artist) if value and value.strip()
        )
        if not keyword:
            return []
        try:
            payload = await self._post_form(
                _SEARCH_PATH,
                {
                    "keyword": keyword,
                    "page": "1",
                    "size": str(_SEARCH_SIZE),
                },
            )
        except (SourceSessionError, httpx.HTTPError, ValueError) as exc:
            _log_upstream_failure("search", exc)
            return []

        items = _result_list(payload)
        ranked: list[tuple[float, int, dict[str, Any]]] = []
        seen_ids: set[str] = set()
        for index, item in enumerate(items):
            source_track_id = _item_id(item)
            if not source_track_id or source_track_id in seen_ids:
                continue
            title = _item_text(item, "name", "title")
            artist = _item_text(item, "artist", "singer", "artist_name", "player")
            if not title or not artist:
                continue
            seen_ids.add(source_track_id)
            ref = TrackRef(
                platform=_SOURCE_ID,
                external_id=source_track_id,
                title=title,
                artist=artist,
                album=_item_text(item, "album_name", "album") or None,
                duration_ms=_duration_ms(item),
            )
            score = track_match_score(track, ref)
            if not is_auto_match(track, ref):
                continue
            ranked.append((score, index, item))

        ranked.sort(key=lambda value: (-value[0], value[1]))
        candidates: list[DownloadCandidate] = []
        for score, _index, item in ranked[: self._max_results]:
            for format_name, bitrate in _QUALITY_VARIANTS:
                candidate = _candidate_from_item(
                    item,
                    track,
                    self._base_url,
                    format_name=format_name,
                    bitrate=bitrate,
                )
                if candidate is None:
                    continue
                candidate.locator["match_score"] = score
                candidates.append(candidate)
        return candidates

    async def resolve(
        self,
        candidate: DownloadCandidate,
        *,
        offset: int = 0,
    ) -> DownloadResponse:
        if candidate.source_id != _SOURCE_ID:
            raise ValueError("sonoma candidate belongs to another source")

        locator = candidate.locator
        song_id = str(locator.get("songid") or candidate.source_track_id).strip()
        if not song_id:
            raise ValueError("sonoma candidate has no song id")

        format_name = normalize_audio_format(str(locator.get("format") or "flac"))
        if format_name != "flac":
            raise ValueError("sonoma only supports FLAC downloads")
        payload = {
            "songid": song_id,
            "format": format_name,
            "time": str(locator.get("time") or ""),
            "bitrate": str(locator.get("bitrate") or _FLAC_BITRATE),
            "sign": str(locator.get("sign") or ""),
        }
        try:
            response = await self._post_form(_RESOLVE_PATH, payload)
        except (SourceSessionError, httpx.HTTPError, ValueError) as exc:
            _log_upstream_failure("resolve", exc)
            raise ValueError("sonoma resolve request failed") from exc

        download_url = _download_url(response)
        if not download_url:
            raise ValueError("sonoma response has no download URL")
        parsed = urlparse(download_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("sonoma returned an invalid download URL")

        headers = {"Referer": self._referer}
        if offset > 0:
            headers["Range"] = f"bytes={offset}-"
        return DownloadResponse(url=download_url, headers=headers)

    async def _post_form(
        self,
        path: str,
        payload: dict[str, str],
    ) -> dict[str, Any]:
        url = urljoin(f"{self._base_url}/", path.lstrip("/"))
        await self._url_guard(url, self._page_hosts)
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": self._base_url,
            "Referer": self._referer,
            "X-Requested-With": "XMLHttpRequest",
        }
        cookie = os.environ.get(self._cookie_env, "").strip()
        if cookie:
            headers["Cookie"] = cookie

        response = await self._client.post(
            url,
            data=payload,
            headers=headers,
            follow_redirects=False,
        )
        if response.status_code == 468:
            raise SourceSessionError("sonoma session rejected")
        if response.status_code in REDIRECT_STATUSES:
            raise ValueError("sonoma API redirected unexpectedly")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("sonoma API returned a non-object response")
        return data


def _candidate_from_item(
    item: dict[str, Any],
    track: TrackRef,
    base_url: str,
    *,
    format_name: str,
    bitrate: str,
) -> DownloadCandidate | None:
    source_track_id = _item_id(item)
    title = _item_text(item, "name", "title")
    artist = _item_text(item, "artist", "singer", "artist_name", "player")
    if not source_track_id or not title or not artist:
        return None
    locator: dict[str, Any] = {
        "songid": source_track_id,
        "format": format_name,
        "bitrate": bitrate,
    }
    for key in ("time", "sign"):
        value = _item_text(item, key)
        if value:
            locator[key] = value
    return DownloadCandidate(
        source_id=_SOURCE_ID,
        source_track_id=f"{source_track_id}:{format_name}:{bitrate}",
        title=title,
        artist=artist,
        album=_item_text(item, "album_name", "album") or None,
        duration_ms=_duration_ms(item) or track.duration_ms,
        quality=AudioQuality(format=format_name),
        source_page_url=f"{base_url}/",
        locator=locator,
    )


def _result_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("code") != 0:
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    items = data.get("list")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _download_url(payload: dict[str, Any]) -> str | None:
    if payload.get("code") != 0:
        return None
    data = payload.get("data")
    if isinstance(data, dict):
        value = data.get("url")
    else:
        value = None
    return str(value).strip() if value else None


def _item_id(item: dict[str, Any]) -> str:
    value = item.get("id") or item.get("songid") or item.get("song_id")
    return str(value).strip() if value is not None else ""


def _item_text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _duration_ms(item: dict[str, Any]) -> int | None:
    # `time` is a getUrl signing parameter, not a duration field.
    for key in ("duration", "interval"):
        value = item.get(key)
        parsed = _parse_duration(value)
        if parsed is not None:
            return parsed
    return None


def _parse_duration(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if ":" in text:
        parts = text.split(":")
        if len(parts) not in {2, 3}:
            return None
        try:
            seconds = 0.0
            for part in parts:
                seconds = seconds * 60 + float(part)
        except ValueError:
            return None
        return int(seconds * 1000)
    try:
        number = float(text)
    except ValueError:
        return None
    if number <= 0:
        return None
    # The upstream has been seen using both seconds and milliseconds.  Values
    # above 100,000 are unambiguously millisecond-scale for a music track.
    return int(number if number > 100_000 else number * 1000)


def _normalize_base_url(value: object) -> str:
    raw = str(value).strip() if value is not None else ""
    if not raw:
        raise ValueError("sonoma base_url is required")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("sonoma base_url must be an http(s) URL with a host")
    return f"{parsed.scheme}://{parsed.netloc}"


def _normalize_cookie_env(value: object) -> str:
    name = str(value).strip() if value is not None else ""
    if not name:
        return ""
    if not all(char.isalnum() or char == "_" for char in name):
        raise ValueError("sonoma cookie_env must be an environment variable name")
    return name


def _hosts_for_base_url(base_url: str) -> tuple[str, ...]:
    host = (urlparse(base_url).hostname or "").lower().rstrip(".")
    if not host:
        return ()
    hosts = [host]
    if host.startswith("www."):
        hosts.append(host.removeprefix("www."))
    else:
        hosts.append(f"www.{host}")
    return tuple(dict.fromkeys(hosts))


def _log_upstream_failure(operation: str, error: Exception) -> None:
    if isinstance(error, SourceSessionError):
        log.warning(
            "download_source_session_rejected",
            source_id=_SOURCE_ID,
            operation=operation,
        )
    else:
        log.warning(
            "download_source_request_failed",
            source_id=_SOURCE_ID,
            operation=operation,
            error=type(error).__name__,
        )


def create_source(
    client: httpx.AsyncClient,
    config: dict[str, object] | None = None,
) -> SonomaSource:
    return SonomaSource(client, config)
