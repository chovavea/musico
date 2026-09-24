"""On-demand synced lyrics from each platform's public lyric endpoint.

Line-timed LRC (and Kuwo's equivalent timestamp list) is the format every
supported platform returns in the clear. Proprietary word-timed blobs are
left alone. Results stay in memory for the process; they are not written
into the chart snapshot.
"""

from __future__ import annotations

import base64
import json
import re
import time
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)

_TIME_TAG = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
_META_TAG = re.compile(r"^\[(?P<key>[a-z]+):(?P<value>[^\]]*)\]\s*$", re.IGNORECASE)
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_INSTRUMENTAL = re.compile(r"纯音乐|instrumental", re.IGNORECASE)
_POSITIVE_TTL_SEC = 6 * 60 * 60
_NEGATIVE_TTL_SEC = 5 * 60
_TRANSLATION_WINDOW_MS = 800


def parse_lrc(text: str) -> list[dict[str, Any]]:
    """Turn an LRC document into sorted ``{time_ms, text}`` lines."""
    offset = 0
    found: list[tuple[int, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        meta = _META_TAG.match(line)
        if meta and not _TIME_TAG.search(line):
            if meta.group("key").lower() == "offset":
                offset = _safe_int(meta.group("value"))
            continue
        stamps = list(_TIME_TAG.finditer(line))
        if not stamps:
            continue
        lyric = _TIME_TAG.sub("", line).strip()
        if not lyric:
            continue
        for stamp in stamps:
            minutes = int(stamp.group(1))
            seconds = float(stamp.group(2))
            time_ms = int(round((minutes * 60 + seconds) * 1000)) + offset
            found.append((max(time_ms, 0), lyric))
    found.sort(key=lambda item: item[0])
    return [{"time_ms": time_ms, "text": lyric} for time_ms, lyric in found]


def attach_translations(
    lines: list[dict[str, Any]], translations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not translations:
        return [{**line, "translation": None} for line in lines]
    merged: list[dict[str, Any]] = []
    for line in lines:
        translation = _closest_text(int(line["time_ms"]), translations, str(line["text"]))
        merged.append({**line, "translation": translation})
    return merged


def lyrics_payload(
    platform: str,
    external_id: str,
    lines: list[dict[str, Any]],
) -> dict[str, Any]:
    cleaned: list[dict[str, Any]] = [
        {
            "time_ms": line.get("time_ms"),
            "text": str(line.get("text") or "").strip(),
            "translation": line.get("translation") or None,
        }
        for line in lines
        if str(line.get("text") or "").strip()
    ]
    synced = any(isinstance(line["time_ms"], int) for line in cleaned)
    if cleaned and all(_INSTRUMENTAL.search(line["text"]) for line in cleaned):
        synced = False
        cleaned = [{**cleaned[0], "time_ms": None, "translation": None}]
    return {
        "platform": platform,
        "external_id": external_id,
        "synced": synced and len(cleaned) > 1,
        "lines": cleaned,
    }


class LyricsService:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    async def lookup(
        self,
        platform: str,
        external_id: str,
        *,
        title: str = "",
        artist: str = "",
        duration_ms: int | None = None,
    ) -> dict[str, Any]:
        key = f"{platform}:{external_id}"
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached is not None and cached[0] > now:
            return cached[1]
        if not _ID.match(external_id):
            payload = lyrics_payload(platform, external_id, [])
            self._remember(key, payload, empty=True)
            return payload
        try:
            lines = await self._fetch(platform, external_id, title, artist, duration_ms)
        except Exception:
            log.warning("lyric_fetch_failed", platform=platform, external_id=external_id)
            lines = []
        payload = lyrics_payload(platform, external_id, lines)
        self._remember(key, payload, empty=not payload["lines"])
        return payload

    def _remember(self, key: str, payload: dict[str, Any], *, empty: bool) -> None:
        ttl = _NEGATIVE_TTL_SEC if empty else _POSITIVE_TTL_SEC
        self._cache[key] = (time.monotonic() + ttl, payload)

    async def _fetch(
        self,
        platform: str,
        external_id: str,
        title: str,
        artist: str,
        duration_ms: int | None,
    ) -> list[dict[str, Any]]:
        if platform == "qqmusic":
            return await self._qq(external_id)
        if platform == "netease":
            return await self._netease(external_id)
        if platform == "kugou":
            return await self._kugou(external_id, title, artist, duration_ms)
        if platform == "kuwo":
            return await self._kuwo(external_id)
        if platform == "bilibili":
            return await self._bilibili(external_id)
        return []

    async def _qq(self, songmid: str) -> list[dict[str, Any]]:
        response = await self._client.get(
            "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg",
            params={
                "songmid": songmid,
                "format": "json",
                "nobase64": 1,
                "g_tk": 5381,
            },
            headers={"Referer": "https://y.qq.com/"},
        )
        response.raise_for_status()
        body = _json_body(response.text)
        lyric = _text_field(body, "lyric")
        trans = _text_field(body, "trans")
        return attach_translations(parse_lrc(lyric), parse_lrc(trans))

    async def _netease(self, song_id: str) -> list[dict[str, Any]]:
        response = await self._client.get(
            "https://music.163.com/api/song/lyric",
            params={"id": song_id, "lv": -1, "tv": -1},
            headers={"Referer": "https://music.163.com/"},
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            return []
        lyric = _nested_text(body.get("lrc"))
        trans = _nested_text(body.get("tlyric"))
        return attach_translations(parse_lrc(lyric), parse_lrc(trans))

    async def _kugou(
        self,
        song_hash: str,
        title: str,
        artist: str,
        duration_ms: int | None,
    ) -> list[dict[str, Any]]:
        keyword = f"{artist} - {title}".strip(" -") or title or song_hash
        response = await self._client.get(
            "https://lyrics.kugou.com/search",
            params={
                "ver": 1,
                "man": "yes",
                "client": "pc",
                "keyword": keyword,
                "duration": duration_ms or "",
                "hash": song_hash,
            },
            headers={"Referer": "https://www.kugou.com/"},
        )
        response.raise_for_status()
        body = response.json()
        candidates = body.get("candidates") if isinstance(body, dict) else None
        if not isinstance(candidates, list) or not candidates:
            return []
        chosen = max(candidates, key=_kugou_score)
        if not isinstance(chosen, dict):
            return []
        lyric_id = chosen.get("id")
        accesskey = chosen.get("accesskey")
        if lyric_id is None or not accesskey:
            return []
        download = await self._client.get(
            "https://lyrics.kugou.com/download",
            params={
                "ver": 1,
                "client": "pc",
                "id": lyric_id,
                "accesskey": accesskey,
                "fmt": "lrc",
                "charset": "utf8",
            },
            headers={"Referer": "https://www.kugou.com/"},
        )
        download.raise_for_status()
        downloaded = download.json()
        content = downloaded.get("content") if isinstance(downloaded, dict) else None
        if not isinstance(content, str) or not content:
            return []
        try:
            text = base64.b64decode(content).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return []
        return attach_translations(parse_lrc(text), [])

    async def _kuwo(self, music_id: str) -> list[dict[str, Any]]:
        response = await self._client.get(
            "https://m.kuwo.cn/newh5/singles/songinfoandlrc",
            params={"musicId": music_id},
            headers={"Referer": "https://www.kuwo.cn/"},
        )
        response.raise_for_status()
        body = response.json()
        data = body.get("data") if isinstance(body, dict) else None
        rows = data.get("lrclist") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        lines: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            text = str(row.get("lineLyric") or "").strip()
            if not text:
                continue
            try:
                time_ms = int(round(float(row.get("time") or 0) * 1000))
            except (TypeError, ValueError):
                continue
            lines.append({"time_ms": max(time_ms, 0), "text": text, "translation": None})
        lines.sort(key=lambda item: int(item["time_ms"]))
        return lines

    async def _bilibili(self, music_id: str) -> list[dict[str, Any]]:
        response = await self._client.get(
            "https://api.bilibili.com/x/copyright-music-publicity/bgm/detail",
            params={"music_id": music_id},
            headers={"Referer": "https://music.bilibili.com/"},
        )
        response.raise_for_status()
        body = response.json()
        data = body.get("data") if isinstance(body, dict) else None
        lyric = data.get("mv_lyric") if isinstance(data, dict) else None
        if not isinstance(lyric, str) or not lyric.strip():
            return []
        timed = parse_lrc(lyric)
        if timed:
            return attach_translations(timed, [])
        return [
            {"time_ms": None, "text": line.strip(), "translation": None}
            for line in lyric.splitlines()
            if line.strip()
        ]


def _json_body(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("MusicJsonCallback(") and raw.endswith(")"):
        raw = raw[len("MusicJsonCallback(") : -1]
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


def _text_field(body: dict[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str):
        return ""
    if "[" in value:
        return value
    try:
        decoded = base64.b64decode(value).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return value
    return decoded


def _nested_text(value: Any) -> str:
    if isinstance(value, dict):
        lyric = value.get("lyric")
        return lyric if isinstance(lyric, str) else ""
    return ""


def _closest_text(time_ms: int, lines: list[dict[str, Any]], original: str) -> str | None:
    best: str | None = None
    best_gap = _TRANSLATION_WINDOW_MS + 1
    for line in lines:
        stamp = line.get("time_ms")
        text = str(line.get("text") or "").strip()
        if not isinstance(stamp, int) or not text or text == original:
            continue
        gap = abs(stamp - time_ms)
        if gap < best_gap:
            best = text
            best_gap = gap
    return best


def _kugou_score(candidate: Any) -> int:
    if not isinstance(candidate, dict):
        return -1
    try:
        return int(candidate.get("score") or 0)
    except (TypeError, ValueError):
        return 0


def _safe_int(value: str) -> int:
    try:
        return int(float(value))
    except ValueError:
        return 0
