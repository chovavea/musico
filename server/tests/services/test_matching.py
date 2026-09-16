from app.domain.matching import (
    fuzzy_preview_rank,
    is_auto_match,
    is_cross_platform_match,
    is_fuzzy_preview_match,
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


def test_auto_match_accepts_overlapping_featured_credits() -> None:
    chart = TrackRef(
        platform="bilibili",
        external_id="b1",
        title="海屿你",
        artist="Cole先生,马也_Crabbit",
        duration_ms=240_000,
    )
    found = TrackRef(
        platform="netease",
        external_id="n1",
        title="海屿你",
        artist="马也_Crabbit",
        duration_ms=None,
    )
    assert is_auto_match(chart, found)
    assert is_cross_platform_match(chart, found, min_score=0.9)
    assert not is_same_recording(chart, found)


def test_cross_platform_preview_accepts_a_candidate_without_duration() -> None:
    origin = TrackRef(
        platform="qqmusic",
        external_id="q1",
        title="我不难过",
        artist="孙燕姿",
        duration_ms=320_000,
    )
    found = TrackRef(
        platform="kugou",
        external_id="k1",
        title="我不难过",
        artist="孙燕姿",
        duration_ms=None,
    )
    assert track_match_score(origin, found) == 0.9
    assert is_cross_platform_match(origin, found, min_score=0.9)
    assert not is_cross_platform_match(origin, found, min_score=0.94)


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


def test_fuzzy_preview_strips_parenthetical_aliases() -> None:
    chart = TrackRef(
        platform="kugou",
        external_id="k1",
        title="Whiplash (NINGNING Solo)",
        artist="aespa (에스파)",
        duration_ms=180_000,
    )
    found = TrackRef(
        platform="gequbao",
        external_id="g1",
        title="Whiplash",
        artist="aespa",
        duration_ms=None,
    )
    assert not is_auto_match(chart, found)
    assert is_fuzzy_preview_match(chart, found)


def test_fuzzy_preview_matches_live_to_studio_and_title_containment() -> None:
    live = TrackRef(
        platform="qqmusic",
        external_id="q1",
        title="想你就写信 (Live)",
        artist="告五人",
        duration_ms=280_000,
    )
    studio = TrackRef(
        platform="gequbao",
        external_id="g1",
        title="想你就写信",
        artist="告五人",
        duration_ms=240_000,
    )
    assert is_fuzzy_preview_match(live, studio)
    assert is_fuzzy_preview_match(
        TrackRef(platform="bili", external_id="b1", title="海屿你", artist="Cole先生,马也_Crabbit"),
        TrackRef(platform="netease", external_id="n1", title="海屿你 (马也_Crabbit)", artist="马也_Crabbit"),
    )


def test_fuzzy_preview_rejects_a_too_short_title() -> None:
    assert not is_fuzzy_preview_match(
        TrackRef(platform="chart", external_id="1", title="晴", artist="周杰伦"),
        TrackRef(platform="source", external_id="2", title="晴天", artist="周杰伦"),
    )


def test_fuzzy_preview_ranks_the_original_artist_ahead_of_a_cover() -> None:
    origin = TrackRef(platform="qqmusic", external_id="q1", title="稻香", artist="周杰伦")
    cover = TrackRef(platform="flmp3", external_id="c1", title="稻香", artist="大宥")
    original = TrackRef(platform="flmp3", external_id="o1", title="稻香", artist="周杰伦")
    assert is_fuzzy_preview_match(origin, cover)
    assert fuzzy_preview_rank(origin, original) > fuzzy_preview_rank(origin, cover)
