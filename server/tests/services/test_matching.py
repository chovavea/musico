from app.domain.matching import is_auto_match, is_same_recording, normalize_text, track_key
from app.domain.models import TrackRef


def test_normalize_text_removes_version_noise() -> None:
    assert normalize_text("  Sky [Live] ") == "sky"


def test_track_matching_requires_artist_and_duration() -> None:
    source = TrackRef(platform="chart", external_id="1", title="晴天", artist="周杰伦", duration_ms=240000)
    assert is_auto_match(source, TrackRef(platform="source", external_id="2", title="晴天", artist="周杰伦", duration_ms=242000))
    assert not is_auto_match(source, TrackRef(platform="source", external_id="3", title="晴天", artist="其他", duration_ms=240000))


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
        TrackRef(platform="qqmusic", external_id="qq-1", title="我不难过", artist="孙燕姿", duration_ms=320_400),
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
