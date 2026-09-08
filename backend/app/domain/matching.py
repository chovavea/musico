from __future__ import annotations

import re
import unicodedata
from hashlib import sha256

from app.domain.models import TrackRef


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = re.sub(r"\([^)]*?(?:live|remix|instrumental|伴奏|现场)[^)]*\)", "", text)
    text = re.sub(r"\[[^]]*?(?:live|remix|instrumental|伴奏|现场)[^]]*\]", "", text)
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text, flags=re.UNICODE)


def artist_key(value: str | None) -> str:
    artists = re.split(r"\s*(?:/|,|&|和|、|feat\.?|ft\.?)\s*", value or "", flags=re.I)
    return normalize_text(artists[0] if artists else value)


def track_match_score(left: TrackRef, right: TrackRef) -> float:
    if left.isrc and right.isrc and left.isrc.casefold() == right.isrc.casefold():
        return 1.0
    if normalize_text(left.title) != normalize_text(right.title):
        return 0.0
    if artist_key(left.artist) != artist_key(right.artist):
        return 0.0
    if left.duration_ms and right.duration_ms:
        delta = abs(left.duration_ms - right.duration_ms)
        if delta > 5000:
            return 0.0
        return 0.98 if delta <= 2000 else 0.94
    return 0.9


def is_auto_match(left: TrackRef, right: TrackRef) -> bool:
    return track_match_score(left, right) >= 0.9


def track_identity(track: TrackRef) -> str:
    return "|".join(
        (
            track.isrc.casefold() if track.isrc else "",
            normalize_text(track.title),
            artist_key(track.artist),
            str(track.duration_ms or ""),
        )
    )


def track_key(track: TrackRef) -> str:
    return sha256(track_identity(track).encode("utf-8")).hexdigest()


def track_identity_key(track: TrackRef) -> str:
    """Return a bounded, deterministic key suitable for a database unique index."""
    return track_key(track)
