from __future__ import annotations

import ast
import html
import json
import re
from typing import Any

import httpx

from app.domain.models import TrackQuery, TrackRef

# Kuwo's search endpoint. Its body is a JavaScript literal (single quotes,
# `&nbsp;` entities, escaped unicode) rather than JSON, so it is read as JSON
# first and as a Python literal when that fails.
_SEARCH_URL = "https://search.kuwo.cn/r.s"
_HEADERS = {"Referer": "https://www.kuwo.cn/"}
_PARAMS: dict[str, Any] = {
    "ft": "music",
    "itemset": "web_2013",
    "client": "kt",
    "pn": 0,
    "rformat": "json",
    # Without this Kuwo answers GBK, which would corrupt every title.
    "encoding": "utf8",
}
_RID_PREFIX = "MUSIC_"
_COVER_BASE = "https://img1.kuwo.cn/star/albumcover/"
# Same shape the cover proxy allows after prefixing `_COVER_BASE`: a 1-4 digit
# size segment, then the rest of the album-cover path.
_COVER_SHORT = re.compile(r"^\d{1,4}/.+$")
# Kuwo doubles its JSON escapes: an ampersand arrives as `\\u0026` once the
# payload is read, so every `\uXXXX` run is decoded back to the character.
_ESCAPED_UNICODE = re.compile(r"\\+u(?P<code>[0-9a-fA-F]{4})")


class KuwoSearch:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: TrackQuery) -> list[TrackRef]:
        keyword = f"{query.title} {query.artist}".strip()
        if not keyword:
            return []
        response = await self._client.get(
            _SEARCH_URL,
            params={**_PARAMS, "all": keyword, "rn": query.limit},
            headers=_HEADERS,
        )
        response.raise_for_status()
        # `encoding=utf8` above makes the answer UTF-8; decoding strictly keeps a
        # changed encoding loud instead of quietly mangling titles.
        return parse_search_payload(response.content.decode("utf-8"), limit=query.limit)


def parse_search_payload(payload: Any, *, limit: int) -> list[TrackRef]:
    rows = _payload(payload).get("abslist")
    if not isinstance(rows, list):
        return []
    tracks: list[TrackRef] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        song_id = _song_id(raw.get("MUSICRID"))
        title = _text(raw.get("NAME") or raw.get("SONGNAME"))
        if not song_id or not title:
            continue
        tracks.append(
            TrackRef(
                platform="kuwo",
                external_id=song_id,
                title=title,
                artist=_text(raw.get("ARTIST")) or "未知",
                album=_text(raw.get("ALBUM")),
                duration_ms=_duration_ms(raw.get("DURATION")),
                cover_url=_cover_url(raw.get("web_albumpic_short")),
                official_url=_official_url(song_id),
            )
        )
        if len(tracks) >= limit:
            break
    return tracks


def _payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if not isinstance(payload, str):
        return {}
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        try:
            value = ast.literal_eval(payload)
        except (SyntaxError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


def _song_id(value: object) -> str:
    if not isinstance(value, str):
        return ""
    song_id = value[len(_RID_PREFIX) :] if value.startswith(_RID_PREFIX) else value
    return song_id if song_id.isdigit() else ""


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    # Kuwo escapes titles for HTML too: "晴天&nbsp;(KTV版伴奏)".
    decoded = _ESCAPED_UNICODE.sub(_unicode_char, value)
    return " ".join(html.unescape(decoded).replace("\xa0", " ").split()) or None


def _unicode_char(match: re.Match[str]) -> str:
    return chr(int(match.group("code"), 16))


def _duration_ms(value: object) -> int | None:
    seconds = int(value) if isinstance(value, str) and value.isdigit() else value
    if isinstance(seconds, int) and not isinstance(seconds, bool) and seconds > 0:
        return seconds * 1000
    return None


def _cover_url(short: object) -> str | None:
    if not isinstance(short, str):
        return None
    path = short.strip().lstrip("/")
    if (
        not path
        or "\\" in path
        or "#" in path
        or "?" in path
        or any(part in {".", "..", ""} for part in path.split("/"))
        or _COVER_SHORT.match(path) is None
    ):
        return None
    # Kuwo answers a relative path ("120/54/93/1964735275.jpg"); the cover proxy
    # rewrites its size segment to the size the browser asked for.
    return f"{_COVER_BASE}{path}"


def _official_url(song_id: str) -> str:
    return f"https://www.kuwo.cn/play_detail/{song_id}"


def create_search(client: httpx.AsyncClient) -> KuwoSearch:
    return KuwoSearch(client)
