from app.domain.matching import (
    is_auto_match,
    is_same_recording,
    normalize_text,
    title_match_key,
    track_key,
    track_match_score,
    version_markers,
)
from app.domain.models import TrackRef


def test_normalize_text_removes_version_noise() -> None:
    assert normalize_text("  Sky [Live] ") == "sky"


def test_stored_normalization_keeps_traditional_characters() -> None:
    """Stored keys stay unfolded, so identity_key values do not shift."""
    assert normalize_text("告白氣球") == "告白氣球"
    assert title_match_key("告白氣球") == title_match_key("告白气球")


def test_traditional_and_simplified_credits_are_the_same_recording() -> None:
    simplified = TrackRef(
        platform="qqmusic", external_id="q1", title="告白气球", artist="周杰伦", duration_ms=220_000
    )
    traditional = TrackRef(
        platform="kuwo", external_id="k1", title="告白氣球", artist="周杰倫", duration_ms=221_000
    )
    assert is_same_recording(simplified, traditional)
    assert track_match_score(simplified, traditional) >= 0.94


def test_version_markers_recognize_folded_markers() -> None:
    assert version_markers("晴天 (現場)") == frozenset({"现场"})


def test_track_matching_requires_artist_and_duration() -> None:
    source = TrackRef(
        platform="chart", external_id="1", title="晴天", artist="周杰伦", duration_ms=240_000
    )
    assert is_auto_match(
        source,
        TrackRef(
            platform="source", external_id="2", title="晴天", artist="周杰伦", duration_ms=242_000
        ),
    )
    assert not is_auto_match(
        source,
        TrackRef(
            platform="source", external_id="3", title="晴天", artist="其他", duration_ms=240_000
        ),
    )


def test_same_recording_keeps_live_and_remix_apart_from_studio() -> None:
    studio = TrackRef(
        platform="library",
        external_id="lib-1",
        title="我不难过",
        artist="孙燕姿",
        duration_ms=320_000,
    )
    assert is_same_recording(
        studio,
        TrackRef(
            platform="qqmusic",
            external_id="qq-1",
            title="我不难过",
            artist="孙燕姿",
            duration_ms=320_400,
        ),
    )
    assert not is_same_recording(
        studio,
        TrackRef(
            platform="qqmusic",
            external_id="qq-live",
            title="我不难过 (Live)",
            artist="孙燕姿",
            duration_ms=309_000,
        ),
    )
    assert not is_same_recording(
        studio,
        TrackRef(
            platform="netease",
            external_id="163-remix",
            title="我不难过 (Remix)",
            artist="孙燕姿",
            duration_ms=320_000,
        ),
    )


def test_track_key_is_stable() -> None:
    track = TrackRef(platform="chart", external_id="1", title="晴天", artist="周杰伦")
    assert track_key(track) == track_key(track.model_copy())
