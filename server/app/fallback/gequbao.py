from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from html import unescape
from urllib.parse import quote, urljoin, urlparse, urlunparse

import httpx
import structlog

from app.adapters.http.safety import (
    MAX_HOPS,
    REDIRECT_STATUSES,
    assert_outbound_url_allowed,
    host_matches,
)
from app.domain.matching import fuzzy_preview_rank, is_auto_match, is_listen_match
from app.domain.models import TrackRef
from app.fallback.sonoma import PreviewClip

log = structlog.get_logger(__name__)

UrlGuard = Callable[[str, Sequence[str]], Awaitable[None]]
MatchFn = Callable[[TrackRef, TrackRef], bool]

_PLAY_PATH = "/member/common-play-url"
_SONG_ITEM_RE = re.compile(
    r'<a href="(?P<href>/music/(?P<id>\d+))"\s+class="[^"]*hover-zoom[^"]*"'
    r'[\s\S]{0,240}?title="(?P<label>[^"]+)"',
    re.IGNORECASE,
)
_APP_DATA_RE = re.compile(
    r"window\.appData\s*=\s*JSON\.parse\('(?P<payload>.*?)'\);",
    re.DOTALL,
)
_UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")
_SONG_ID_RE = re.compile(r"^\d+$")
_PLAYBACK_HOST_SUFFIXES = (
    "kuwo.cn",
    "kugou.com",
    "music.126.net",
    "music.163.com",
    "qqmusic.qq.com",
    "tc.qq.com",
)
# kw-er is what the in-page player uses; Lego CDN 403s non-browser TLS on that
# node. The same path answers 206 on kw-lv, which is the host the official Kuwo
# preview plugin already fetches.
_PLAYBACK_HOST_REWRITE = {
    "kw-er.kuwo.cn": "kw-lv.kuwo.cn",
}
_AUDIO_SUFFIX_TYPES = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
}


@dataclass(frozen=True)
class SongHit:
    song_id: str
    path: str
    title: str
    artist: str


class GequbaoPreview:
    """Resolve a track to the site's in-page listen URL.

    Search is ``GET /s/{keyword}``. Clicking 播放 posts
    ``POST /member/common-play-url`` with the encrypted ``play_id`` from
    ``window.appData``; the JSON ``data.url`` is assigned to ``audio.src``.
    Captcha, quota and VIP gates are treated as a miss. Quark share links on
    the same page are a download path and are not used here.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        *,
        extra_hosts: Sequence[str] = (),
        url_guard: UrlGuard | None = None,
        max_candidates: int = 3,
    ) -> None:
        self._client = client
        self._url_guard = url_guard or assert_outbound_url_allowed
        self._base_url = _normalize_base_url(base_url)
        self._hosts = _hosts_for_base_url(self._base_url, extra_hosts)
        self._max_candidates = max(1, max_candidates)
        self._referer = f"{self._base_url}/"
        self._playback_hosts = tuple(dict.fromkeys((*_PLAYBACK_HOST_SUFFIXES, *self._hosts)))

    async def iter_preview_clips(
        self, track: TrackRef, *, match: MatchFn | None = None
    ) -> AsyncIterator[PreviewClip]:
        try:
            hits = await self._matched_hits(track, match=match or is_listen_match)
        except (httpx.HTTPError, ValueError) as exc:
            log.info("gequbao_preview_search_unavailable", error_type=type(exc).__name__)
            return
        for hit in hits[: self._max_candidates]:
            page_url = urljoin(f"{self._base_url}/", hit.path.lstrip("/"))
            try:
                audio_url = await self._play_url(page_url)
            except (httpx.HTTPError, ValueError) as exc:
                log.info("gequbao_playurl_unavailable", error_type=type(exc).__name__)
                continue
            validated_url = _validated_playback_url(audio_url, self._playback_hosts)
            if validated_url is None:
                continue
            yield PreviewClip(
                url=validated_url,
                page_url=page_url,
                media_type=_media_type_for(validated_url),
                allowed_hosts=self._playback_hosts,
                referer=page_url,
                source_track_id=hit.path,
            )

    async def _matched_hits(
        self, track: TrackRef, *, match: MatchFn = is_auto_match
    ) -> list[SongHit]:
        for keyword in _search_keywords(track):
            try:
                html = await self._fetch(
                    f"{self._base_url}/s/{quote(keyword, safe='')}"
                )
            except (httpx.HTTPError, ValueError):
                continue
            hits = [
                hit for hit in _song_hits(html) if match(track, _hit_ref(hit))
            ]
            hits.sort(key=lambda hit: fuzzy_preview_rank(track, _hit_ref(hit)), reverse=True)
            if hits:
                return hits
        return []

    async def _play_url(self, page_url: str) -> str:
        html = await self._fetch(page_url)
        play_id = _play_id_from_page(html)
        payload = await self._post_json(
            f"{self._base_url}{_PLAY_PATH}",
            {"id": play_id, "purpose": "play"},
            referer=page_url,
        )
        if payload.get("code") != 1:
            raise ValueError(f"gequbao play returned {payload.get('code')}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("gequbao play missing data")
        url = data.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ValueError("gequbao play missing url")
        return await self._kuwo_convert(_rewrite_playback_url(url.strip()), page_url)

    async def _kuwo_convert(self, audio_url: str, referer: str) -> str:
        parsed = urlparse(audio_url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if host != "antiserver.kuwo.cn" and not host.endswith(".antiserver.kuwo.cn"):
            return audio_url
        separator = "&" if parsed.query else "?"
        convert_url = f"{audio_url}{separator}type=convert_url3"
        try:
            body = await self._fetch(convert_url, referer=referer, accept="application/json,*/*")
            payload = _json_object(body)
        except (httpx.HTTPError, ValueError):
            return audio_url
        if payload.get("code") != 200:
            return audio_url
        converted = payload.get("url")
        if isinstance(converted, str) and converted.strip():
            return _rewrite_playback_url(converted.strip())
        return audio_url

    async def _fetch(self, url: str, *, referer: str | None = None, accept: str = "text/html,*/*") -> str:
        current = url
        headers = {"Accept": accept, "Referer": referer or self._referer}
        for _hop in range(MAX_HOPS):
            await self._url_guard(current, self._hosts if _is_site_url(current, self._hosts) else self._playback_hosts)
            response = await self._client.get(
                current,
                headers=headers,
                follow_redirects=False,
            )
            if response.status_code in REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("gequbao redirect without location")
                current = urljoin(str(response.url), location)
                continue
            if response.status_code != 200:
                raise ValueError(f"gequbao page returned {response.status_code}")
            return response.text
        raise ValueError("gequbao page exceeded redirect limit")

    async def _post_json(self, url: str, data: dict[str, str], *, referer: str) -> dict[str, object]:
        await self._url_guard(url, self._hosts)
        response = await self._client.post(
            url,
            data=data,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": self._base_url,
                "Referer": referer,
                "X-Requested-With": "XMLHttpRequest",
            },
            follow_redirects=False,
        )
        if response.status_code != 200:
            raise ValueError(f"gequbao play returned {response.status_code}")
        return _json_object(response.text)


def _search_keywords(track: TrackRef) -> list[str]:
    title = _keyword_text(track.title or "")
    artist = _keyword_text(track.artist or "")
    keywords: list[str] = []
    if title and artist:
        keywords.append(f"{title} {artist}")
    primary = title or artist
    if primary:
        keywords.append(primary)
    return list(dict.fromkeys(keywords))


def _keyword_text(value: str) -> str:
    # The search route is `/s/{keyword}`. Slashes would become extra path
    # segments, and gequbao 404s on `%2F`, so featured-artist credits are
    # flattened to spaces before the URL is built.
    text = re.sub(r"\s*[/|,]+\s*", " ", value)
    return " ".join(text.split())


def _song_hits(html: str) -> list[SongHit]:
    hits: list[SongHit] = []
    seen: set[str] = set()
    for match in _SONG_ITEM_RE.finditer(html):
        path = match.group("href")
        song_id = match.group("id")
        if path in seen or not _SONG_ID_RE.fullmatch(song_id):
            continue
        seen.add(path)
        title, artist = _split_label(unescape(match.group("label")))
        if not title:
            continue
        hits.append(SongHit(song_id=song_id, path=path, title=title, artist=artist))
    return hits


def _split_label(label: str) -> tuple[str, str]:
    text = " ".join(label.split())
    if " - " in text:
        title, artist = text.split(" - ", 1)
        return title.strip(), artist.strip()
    return text.strip(), ""


def _hit_ref(hit: SongHit) -> TrackRef:
    return TrackRef(
        platform="gequbao",
        external_id=hit.song_id,
        title=hit.title,
        artist=hit.artist,
    )


def _play_id_from_page(html: str) -> str:
    match = _APP_DATA_RE.search(html)
    if not match:
        raise ValueError("gequbao page missing appData")
    payload = match.group("payload").replace("\\u0022", '"')
    data = _json_object(payload)
    play_id = _unescape_app_text(str(data.get("play_id") or ""))
    if not play_id:
        raise ValueError("gequbao page missing play_id")
    return play_id


def _json_object(text: str) -> dict[str, object]:
    body = text.strip()
    if body.startswith(("callback(", "jQuery")):
        start = body.find("{")
        end = body.rfind("}")
        if start < 0 or end < start:
            raise ValueError("gequbao JSONP missing object")
        body = body[start : end + 1]
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("gequbao payload is not JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("gequbao payload is not an object")
    return payload


def _unescape_app_text(value: str) -> str:
    text = value.replace(r"\/", "/")
    return _UNICODE_ESCAPE_RE.sub(lambda match: chr(int(match.group(1), 16)), text)


def _rewrite_playback_url(url: str) -> str:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return url
    host = (parsed.hostname or "").lower().rstrip(".")
    replacement = _PLAYBACK_HOST_REWRITE.get(host)
    if not replacement:
        return url.strip()
    return urlunparse((parsed.scheme, replacement, parsed.path, parsed.params, parsed.query, parsed.fragment))


def _validated_playback_url(url: str, allowed_hosts: Sequence[str]) -> str | None:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if parsed.scheme != "https":
        return None
    if parsed.username or parsed.password:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or parsed.port not in {None, 443}:
        return None
    if not host_matches(host, allowed_hosts):
        return None
    if not parsed.path:
        return None
    return urlunparse((parsed.scheme, host, parsed.path, "", parsed.query, ""))


def _media_type_for(url: str) -> str:
    path = urlparse(url).path.lower()
    for suffix, media_type in _AUDIO_SUFFIX_TYPES.items():
        if path.endswith(suffix):
            return media_type
    return "audio/mpeg"


def _normalize_base_url(value: str) -> str:
    parsed = urlparse(str(value).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("gequbao base_url must be an http(s) URL with a host")
    return f"{parsed.scheme}://{parsed.netloc}"


def _hosts_for_base_url(base_url: str, extra_hosts: Sequence[str]) -> tuple[str, ...]:
    host = (urlparse(base_url).hostname or "").lower().rstrip(".")
    hosts = [host] if host else []
    if host.startswith("www."):
        hosts.append(host.removeprefix("www."))
    elif host:
        hosts.append(f"www.{host}")
    hosts.extend(str(item).strip().lower().rstrip(".") for item in extra_hosts if str(item).strip())
    return tuple(dict.fromkeys(item for item in hosts if item))


def _is_site_url(url: str, site_hosts: Sequence[str]) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return bool(host) and host_matches(host, site_hosts)
