from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from hashlib import sha256

from app.domain.models import TrackRef
from app.domain.zh_t2s import fold_traditional

_BRACKETS_RE = re.compile(r"[\(（][^)）]*[\)）]|[\[【][^\]】]*[\]】]")


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = re.sub(r"\([^)]*?(?:live|remix|instrumental|伴奏|现场)[^)]*\)", "", text)
    text = re.sub(r"\[[^]]*?(?:live|remix|instrumental|伴奏|现场)[^]]*\]", "", text)
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text, flags=re.UNICODE)


def artist_key(value: str | None) -> str:
    artists = re.split(r"\s*(?:/|,|&|和|、|feat\.?|ft\.?)\s*", value or "", flags=re.I)
    return normalize_text(artists[0] if artists else value)


def title_match_key(value: str | None) -> str:
    """Comparison key for titles, with traditional characters folded to simplified.

    ``normalize_text`` stays unfolded because it also builds the stored
    ``normalized_title``/``identity_key`` values; folding here keeps the same
    recording written as 繁体 and 简体 comparable without a data migration.
    """
    return fold_traditional(normalize_text(value))


def artist_match_key(value: str | None) -> str:
    """Artist comparison key; folds 繁/简 so either script still matches."""
    return fold_traditional(artist_key(value))


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
# Listen-only: a ringtone or snippet is not a full song, even when the title
# otherwise matches. Live / remix stay out of this list — those are complete edits.
_INCOMPLETE_LISTEN_CJK = (
    "片段",
    "铃声",
    "试听版",
    "铃声版",
    "截取",
    "彩铃",
    "30秒",
    "60秒",
)
_INCOMPLETE_LISTEN_ASCII = ("ringtone", "snippet")
LISTEN_SNIPPET_MAX_MS = 90_000
LISTEN_FULL_ORIGIN_MIN_MS = 120_000


def version_markers(value: str | None) -> frozenset[str]:
    """Return the version words that mark a recording as a different edit."""
    text = fold_traditional(unicodedata.normalize("NFKC", value or "").casefold())
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
    return bool(folded_artist_names(left) & folded_artist_names(right))


def folded_artist_names(value: str | None) -> set[str]:
    """Individual artist names, 繁简 folded, used to score artist overlap.

    Two tracks can only be the same recording when they share at least one of
    these names, which is also what lets the search merge bucket by
    (title, artist name) instead of by title alone.
    """
    return {fold_traditional(name) for name in artist_names(value)}


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
    if title_match_key(left.title) != title_match_key(right.title):
        return 0.0
    # Featured / split credits still match when they share a performer. First-artist
    # equality is kept for library identity (``is_same_recording``), not auto-match.
    if not artists_overlap(left.artist, right.artist):
        return 0.0
    if left.duration_ms and right.duration_ms:
        delta = abs(left.duration_ms - right.duration_ms)
        if delta > 5000:
            return 0.0
        return 0.98 if delta <= 2000 else 0.94
    return 0.9


def is_auto_match(left: TrackRef, right: TrackRef) -> bool:
    return track_match_score(left, right) >= 0.9


def is_incomplete_listen_edit(track: TrackRef) -> bool:
    """Whether the title/version marks this as a ringtone, snippet, or clip."""
    text = fold_traditional(
        unicodedata.normalize("NFKC", f"{track.version or ''} {track.title}").casefold()
    )
    if any(marker in text for marker in _INCOMPLETE_LISTEN_CJK):
        return True
    return any(
        re.search(rf"(?<![a-z]){marker}(?![a-z])", text)
        for marker in _INCOMPLETE_LISTEN_ASCII
    )


def is_incomplete_listen_duration(origin_ms: int | None, candidate_ms: int | None) -> bool:
    """Reject a short clip when the requested track is a full-length song."""
    if origin_ms is None or candidate_ms is None:
        return False
    if origin_ms < LISTEN_FULL_ORIGIN_MIN_MS:
        return False
    return candidate_ms < LISTEN_SNIPPET_MAX_MS and candidate_ms < origin_ms * 0.5


def listen_candidate_is_incomplete(origin: TrackRef, candidate: TrackRef) -> bool:
    if is_incomplete_listen_edit(candidate) and not is_incomplete_listen_edit(origin):
        return True
    return is_incomplete_listen_duration(origin.duration_ms, candidate.duration_ms)


def is_listen_match(origin: TrackRef, candidate: TrackRef) -> bool:
    """Strict listen match: same recording, and not a ringtone/snippet."""
    if listen_candidate_is_incomplete(origin, candidate):
        return False
    return is_auto_match(origin, candidate)


def loose_title_key(value: str | None) -> str:
    """Title key with every parenthetical alias stripped, not only live/remix tags."""
    return fold_traditional(normalize_text(_BRACKETS_RE.sub(" ", value or "")))


def loose_artist_names(value: str | None) -> set[str]:
    """Artist tokens after dropping ``(에스파)``-style aliases that block overlap."""
    return folded_artist_names(_BRACKETS_RE.sub(" ", value or ""))


def loose_artists_overlap(left: str | None, right: str | None) -> bool:
    return bool(loose_artist_names(left) & loose_artist_names(right))


def fuzzy_title_score(left: str | None, right: str | None) -> float:
    origin = loose_title_key(left)
    candidate = loose_title_key(right)
    if not origin or not candidate:
        return 0.0
    if origin == candidate:
        return 1.0
    shorter, longer = (origin, candidate) if len(origin) <= len(candidate) else (candidate, origin)
    if shorter in longer:
        return 0.9 * (len(shorter) / len(longer))
    return SequenceMatcher(None, origin, candidate).ratio()


def is_fuzzy_listen_match(origin: TrackRef, candidate: TrackRef) -> bool:
    """Last-resort listen match that still drops ringtones and snippets."""
    if listen_candidate_is_incomplete(origin, candidate):
        return False
    return is_fuzzy_preview_match(origin, candidate)


def is_fuzzy_preview_match(origin: TrackRef, candidate: TrackRef) -> bool:
    """Last-resort listen match: prefer playing something over a perfect recording.

    Parenthetical aliases, live/studio tags and duration are ignored. A shared
    artist still ranks higher at the call site, but title similarity alone is
    enough once the strict ladder has already missed.
    """
    if origin.isrc and candidate.isrc and origin.isrc.casefold() == candidate.isrc.casefold():
        return True
    origin_key = loose_title_key(origin.title)
    candidate_key = loose_title_key(candidate.title)
    if not _title_long_enough(origin_key) or not _title_long_enough(candidate_key):
        return False
    if origin_key == candidate_key:
        return True
    shorter, longer = (
        (origin_key, candidate_key)
        if len(origin_key) <= len(candidate_key)
        else (candidate_key, origin_key)
    )
    if shorter in longer and len(shorter) / len(longer) >= 0.45:
        return True
    return SequenceMatcher(None, origin_key, candidate_key).ratio() >= 0.6


def fuzzy_preview_rank(origin: TrackRef, candidate: TrackRef) -> tuple[int, float]:
    """Prefer a shared performer, then the closer title, when several fuzzy hits exist."""
    overlap = 1 if loose_artists_overlap(origin.artist, candidate.artist) else 0
    return (overlap, fuzzy_title_score(origin.title, candidate.title))


def _title_long_enough(key: str) -> bool:
    if not key:
        return False
    cjk = sum(1 for char in key if "\u4e00" <= char <= "\u9fff")
    if cjk:
        return cjk >= 2
    return len(key) >= 4


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
    if title_match_key(left.title) != title_match_key(right.title):
        return False
    if not artists_overlap(left.artist, right.artist):
        return False
    if left.duration_ms and right.duration_ms:
        if abs(left.duration_ms - right.duration_ms) > 5_000:
            return False
    return artist_match_key(left.artist) == artist_match_key(right.artist) and track_match_score(
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
