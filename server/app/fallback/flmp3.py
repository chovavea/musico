from __future__ import annotations

import re
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from urllib.parse import quote, urljoin, urlparse, urlunparse

import httpx
import structlog

from app.adapters.http.safety import (
    MAX_HOPS,
    REDIRECT_STATUSES,
    assert_outbound_url_allowed,
    host_matches,
)
from app.domain.matching import fuzzy_preview_rank, is_auto_match
from app.domain.models import TrackRef
from app.fallback.sonoma import PreviewClip

log = structlog.get_logger(__name__)

UrlGuard = Callable[[str, Sequence[str]], Awaitable[None]]
MatchFn = Callable[[TrackRef, TrackRef], bool]

_SEARCH_PATH = "/search.html"
_PLAYURL_PATH = "/api/playurl.php"
_SONG_ITEM_RE = re.compile(
    r'<a href="(?P<href>/song/(?P<id>\d+)\.html)">[\s\S]*?'
    r"<h3>(?P<title>.*?)</h3>\s*<p>(?P<artist>.*?)</p>",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")
_SONG_ID_RE = re.compile(r"^\d+$")
# playurl.php currently hands back a Kuwo media URL. Extra hosts can widen this
# without turning the preview proxy into an open relay.
_PLAYBACK_HOST_SUFFIXES = (
    "kuwo.cn",
    "kugou.com",
    "music.126.net",
    "music.163.com",
    "qqmusic.qq.com",
    "tc.qq.com",
)
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


class Flmp3Preview:
    """Resolve a track to the site's in-page listen URL.

    Search is ``GET /search.html?keyword=``. Clicking 试听 then calls
    ``GET /api/playurl.php?id=`` which returns a Kuwo HTTPS mp3; the page
    assigns that string to ``audio.src``. Downloads stay on a captcha/netdisk
    path and are not used here.
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
            hits = await self._matched_hits(track, match=match or is_auto_match)
        except (httpx.HTTPError, ValueError) as exc:
            log.info("flmp3_preview_search_unavailable", error_type=type(exc).__name__)
            return
        for hit in hits[: self._max_candidates]:
            page_url = urljoin(f"{self._base_url}/", hit.path.lstrip("/"))
            try:
                body = await self._fetch(
                    f"{self._base_url}{_PLAYURL_PATH}?id={quote(hit.song_id, safe='')}",
                    referer=page_url,
                    accept="text/plain,*/*",
                )
            except (httpx.HTTPError, ValueError) as exc:
                log.info("flmp3_playurl_unavailable", error_type=type(exc).__name__)
                continue
            audio_url = _validated_playback_url(body, self._playback_hosts)
            if audio_url is None:
                continue
            yield PreviewClip(
                url=audio_url,
                page_url=page_url,
                media_type=_media_type_for(audio_url),
                allowed_hosts=self._playback_hosts,
                referer=page_url,
                source_track_id=hit.path,
            )

    async def _matched_hits(
        self, track: TrackRef, *, match: MatchFn = is_auto_match
    ) -> list[SongHit]:
        for keyword in _search_keywords(track):
            html = await self._fetch(
                f"{self._base_url}{_SEARCH_PATH}?keyword={quote(keyword, safe='')}"
            )
            hits = [
                hit for hit in _song_hits(html) if match(track, _hit_ref(hit))
            ]
            hits.sort(key=lambda hit: fuzzy_preview_rank(track, _hit_ref(hit)), reverse=True)
            if hits:
                return hits
        return []

    async def _fetch(self, url: str, *, referer: str | None = None, accept: str = "text/html,*/*") -> str:
        current = url
        headers = {"Accept": accept, "Referer": referer or self._referer}
        for _hop in range(MAX_HOPS):
            await self._url_guard(current, self._hosts)
            response = await self._client.get(
                current,
                headers=headers,
                follow_redirects=False,
            )
            if response.status_code in REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("flmp3 redirect without location")
                current = urljoin(str(response.url), location)
                continue
            if response.status_code != 200:
                raise ValueError(f"flmp3 page returned {response.status_code}")
            return response.text
        raise ValueError("flmp3 page exceeded redirect limit")


def _search_keywords(track: TrackRef) -> list[str]:
    title = (track.title or "").strip()
    artist = (track.artist or "").strip()
    keywords: list[str] = []
    if title and artist:
        keywords.append(f"{title} {artist}")
    primary = title or artist
    if primary:
        keywords.append(primary)
    return list(dict.fromkeys(keywords))


def _song_hits(html: str) -> list[SongHit]:
    hits: list[SongHit] = []
    seen: set[str] = set()
    for match in _SONG_ITEM_RE.finditer(html):
        path = match.group("href")
        song_id = match.group("id")
        if path in seen or not _SONG_ID_RE.fullmatch(song_id):
            continue
        seen.add(path)
        title = _TAG_RE.sub("", match.group("title")).strip()
        artist = _TAG_RE.sub("", match.group("artist")).strip()
        if not title:
            continue
        hits.append(SongHit(song_id=song_id, path=path, title=title, artist=artist))
    return hits


def _hit_ref(hit: SongHit) -> TrackRef:
    return TrackRef(
        platform="flmp3",
        external_id=hit.song_id,
        title=hit.title,
        artist=hit.artist,
    )


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
        raise ValueError("flmp3 base_url must be an http(s) URL with a host")
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
