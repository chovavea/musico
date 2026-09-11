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


_ASCII_VERSION_MARKERS = ("live", "remix", "instrumental", "acoustic", "unplugged")
_CJK_VERSION_MARKERS = (
    "伴奏",
    "现场",
    "翻唱",
    "不插电",
    "片段",
    "铃声",
    "纯音乐",
    "加速版",
    "慢速版",
)


def version_markers(value: str | None) -> frozenset[str]:
    """Return the version words that mark a recording as a different edit."""
    text = unicodedata.normalize("NFKC", value or "").casefold()
    found = {marker for marker in _CJK_VERSION_MARKERS if marker in text}
    found.update(
        marker
        for marker in _ASCII_VERSION_MARKERS
        if re.search(rf"(?<![a-z]){marker}(?![a-z])", text)
    )
    return frozenset(found)


def version_variant_conflict(origin: TrackRef, candidate: TrackRef) -> bool:
    """Reject a live/instrumental/clip edit when the original is the studio take.

    ``normalize_text`` erases bracketed version words, so title equality alone
    cannot tell a studio recording from its live or karaoke twin.
    """
    if version_markers(f"{origin.version or ''} {origin.title}"):
        return False
    return bool(version_markers(f"{candidate.version or ''} {candidate.title}"))


def artist_names(value: str | None) -> set[str]:
    parts = re.split(r"\s*(?:/|,|&|和|、|feat\.?|ft\.?)\s*", value or "", flags=re.I)
    return {name for name in (normalize_text(part) for part in parts) if name}


def artists_overlap(left: str | None, right: str | None) -> bool:
    return bool(artist_names(left) & artist_names(right))


def is_cross_platform_match(origin: TrackRef, candidate: TrackRef, *, min_score: float) -> bool:
    """Guards for a preview borrowed from another platform's official player."""
    if origin.platform == candidate.platform:
        return True
    if origin.isrc and candidate.isrc and origin.isrc.casefold() == candidate.isrc.casefold():
        # The same ISRC is the same recording, whatever the title says.
        return True
    if track_match_score(origin, candidate) < min_score:
        return False
    if version_variant_conflict(origin, candidate):
        return False
    return artists_overlap(origin.artist, candidate.artist)


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


def is_same_recording(left: TrackRef, right: TrackRef) -> bool:
    """Whether two tracks are the same recording, not a live/remix/duration sibling.

    ``normalize_text`` strips bracketed version words, so title equality alone
    would treat a studio take and its live twin as one song. Search merge and
    library badges both use this guard.
    """
    if left.isrc and right.isrc and left.isrc.casefold() == right.isrc.casefold():
        return True
    if version_variant_conflict(left, right) or version_variant_conflict(right, left):
        return False
    if normalize_text(left.title) != normalize_text(right.title):
        return False
    if not artists_overlap(left.artist, right.artist):
        return False
    if left.duration_ms and right.duration_ms:
        if abs(left.duration_ms - right.duration_ms) > 5_000:
            return False
    return artist_key(left.artist) == artist_key(right.artist) and track_match_score(
        left, right
    ) >= 0.9


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
