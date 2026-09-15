from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote, urljoin, urlparse, urlunparse

import httpx
import structlog

from app.adapters.http.safety import MAX_HOPS, REDIRECT_STATUSES, assert_outbound_url_allowed
from app.domain.matching import is_auto_match
from app.domain.models import TrackRef

log = structlog.get_logger(__name__)

UrlGuard = Callable[[str, Sequence[str]], Awaitable[None]]

FallbackOutcome = Literal["jumped", "no_wav", "not_found", "unreachable", "no_share_link"]

_SEARCH_PATH = "/index/search/"
_SONG_ITEM_RE = re.compile(
    r'<a href="(?P<href>/song/[^"]+)"(?P<attrs>[^>]*)>'
    r"\s*<h3>(?P<name>.*?)</h3>(?P<tail>.*?)</small>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_ANCHOR_TITLE_RE = re.compile(r'title="(?P<title>[^"]*)"')
_NAME_SPLIT_RE = re.compile(r"^(?P<artist>.+?)_《(?P<title>.+?)》")
_LABEL_RE = re.compile(r'<span class="tagstyle2[^>]*>(?P<label>[^<]*)</span>', re.IGNORECASE)
_SIZE_RE = re.compile(r"大小：\s*(?P<size>[0-9.]+\s*[KMG]?B)")
_WAV_HREF_RE = re.compile(r"(?P<href>/dls/rwk\d+\.html)", re.IGNORECASE)
# Host is anchored so a page cannot smuggle pan.quark.cn inside another origin.
_SHARE_URL_RE = re.compile(r"https?://pan\.quark\.cn/s/[A-Za-z0-9]+", re.IGNORECASE)
_SHARE_HOST = "pan.quark.cn"
_SHARE_PATH_RE = re.compile(r"^/s/[A-Za-z0-9]+$")


@dataclass(frozen=True)
class SongHit:
    path: str
    title: str
    artist: str
    label: str


@dataclass(frozen=True)
class FallbackLink:
    outcome: FallbackOutcome
    share_url: str | None = None
    page_url: str | None = None
    detail: str | None = None
    error: str | None = None


class SonomaFallback:
    """Resolve a track to the Quark share page of the site's WAV upload.

    The site never serves audio itself: every download button is a ~76 byte page
    that redirects the browser to a Quark share.  This adapter therefore only
    reads pages, follows the WAV route, and hands the share URL back to the
    caller -- the transfer happens in the user's browser.
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

    async def resolve(self, track: TrackRef) -> FallbackLink:
        keyword = quote(track.title or track.artist, safe="")
        try:
            search_html = await self._fetch(f"{self._base_url}{_SEARCH_PATH}?keyword={keyword}")
        except (httpx.HTTPError, ValueError) as exc:
            return FallbackLink(outcome="unreachable", error=_reason(exc))
        hits = [hit for hit in _song_hits(search_html) if is_auto_match(track, _hit_ref(hit))]
        if not hits:
            return FallbackLink(outcome="not_found", error="站点没有匹配的条目")
        last_unreachable: FallbackLink | None = None
        last_no_share: FallbackLink | None = None
        fetched_page = False
        saw_wav = False
        for hit in hits[: self._max_candidates]:
            page_url = urljoin(f"{self._base_url}/", hit.path.lstrip("/"))
            try:
                page_html = await self._fetch(page_url)
            except (httpx.HTTPError, ValueError) as exc:
                last_unreachable = FallbackLink(
                    outcome="unreachable", page_url=page_url, error=_reason(exc)
                )
                continue
            fetched_page = True
            wav = _WAV_HREF_RE.search(page_html)
            if wav is None:
                continue
            saw_wav = True
            download_url = urljoin(f"{self._base_url}/", wav.group("href").lstrip("/"))
            try:
                handoff_html = await self._fetch(download_url)
            except (httpx.HTTPError, ValueError) as exc:
                last_unreachable = FallbackLink(
                    outcome="unreachable", page_url=page_url, error=_reason(exc)
                )
                continue
            share = _quark_share_url(handoff_html)
            if share is None:
                last_no_share = FallbackLink(
                    outcome="no_share_link",
                    page_url=page_url,
                    detail=f"{hit.title}-{hit.artist}",
                )
                continue
            return FallbackLink(
                outcome="jumped",
                share_url=share,
                page_url=page_url,
                detail=_wav_detail(page_html) or "WAV",
            )
        if last_no_share is not None:
            return last_no_share
        if last_unreachable is not None and (not fetched_page or saw_wav):
            return last_unreachable
        return FallbackLink(outcome="no_wav", detail="站点只有 MP3 版本")

    async def _fetch(self, url: str) -> str:
        current = url
        headers = {"Accept": "text/html,*/*", "Referer": self._referer}
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
                    raise ValueError("fallback redirect without location")
                current = urljoin(str(response.url), location)
                continue
            if response.status_code != 200:
                raise ValueError(f"fallback page returned {response.status_code}")
            return response.text
        raise ValueError("fallback page exceeded redirect limit")


def _song_hits(html: str) -> list[SongHit]:
    hits: list[SongHit] = []
    seen: set[str] = set()
    for match in _SONG_ITEM_RE.finditer(html):
        path = match.group("href")
        if path in seen:
            continue
        seen.add(path)
        name = _TAG_RE.sub("", match.group("name")).strip()
        title, artist = _split_name(name, match.group("attrs"))
        if not title:
            continue
        label = _LABEL_RE.search(match.group("tail"))
        hits.append(
            SongHit(
                path=path,
                title=title,
                artist=artist,
                label=label.group("label").strip() if label else "",
            )
        )
    return hits


def _split_name(name: str, attrs: str) -> tuple[str, str]:
    """Prefer the anchor's ``artist_《title》`` attribute over the ``title-artist`` text."""
    anchor = _ANCHOR_TITLE_RE.search(attrs)
    if anchor:
        parsed = _NAME_SPLIT_RE.match(anchor.group("title").strip())
        if parsed:
            return parsed.group("title").strip(), parsed.group("artist").strip()
    if "-" in name:
        title, _, artist = name.rpartition("-")
        if title.strip() and artist.strip():
            return title.strip(), artist.strip()
    return name.strip(), ""


def _hit_ref(hit: SongHit) -> TrackRef:
    return TrackRef(
        platform="fallback",
        external_id=hit.path,
        title=hit.title,
        artist=hit.artist,
    )


def _quark_share_url(html: str) -> str | None:
    for match in _SHARE_URL_RE.finditer(html):
        parsed = _validated_quark_share(match.group(0))
        if parsed is not None:
            return parsed
    return None


def _validated_quark_share(url: str) -> str | None:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.username or parsed.password:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    if host != _SHARE_HOST or parsed.port not in {None, 80, 443}:
        return None
    if not _SHARE_PATH_RE.match(parsed.path):
        return None
    return urlunparse((parsed.scheme.lower(), host, parsed.path, "", parsed.query, ""))


def _wav_detail(html: str) -> str | None:
    size = _SIZE_RE.search(html)
    return f"WAV · {size.group('size').strip()}" if size else None


def _reason(exc: BaseException) -> str:
    return str(exc).strip()[:200] or exc.__class__.__name__


def _normalize_base_url(value: str) -> str:
    parsed = urlparse(str(value).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("fallback base_url must be an http(s) URL with a host")
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
