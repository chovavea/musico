from app.domain.models import (
    ALLOWED_DOWNLOAD_FORMATS,
    AudioQuality,
    is_allowed_download_format,
)


def test_download_formats_are_exactly_the_three_lossless_formats() -> None:
    assert ALLOWED_DOWNLOAD_FORMATS == ("flac", "wav", "dsf")
    assert is_allowed_download_format("FLAC")
    assert is_allowed_download_format(".wav")
    assert is_allowed_download_format("dsf")
    assert not is_allowed_download_format("mp3")
    assert not is_allowed_download_format("dff")


def test_quality_prefers_hires_flac_over_cd_wav() -> None:
    hires_flac = AudioQuality(format="flac", sample_rate_hz=96_000, bit_depth=24)
    cd_wav = AudioQuality(format="wav", sample_rate_hz=44_100, bit_depth=16)
    assert hires_flac.sort_key() > cd_wav.sort_key()


def test_quality_prefers_dsd_container() -> None:
    dsd = AudioQuality(format="dsf", dsd_rate="DSD64")
    hires_flac = AudioQuality(format="flac", sample_rate_hz=192_000, bit_depth=24)
    assert dsd.sort_key() > hires_flac.sort_key()


def test_quality_matching_requires_all_requested_dimensions() -> None:
    actual = AudioQuality(
        format="flac",
        sample_rate_hz=96_000,
        bit_depth=24,
        channels=2,
    )
    assert actual.matches_requested(
        AudioQuality(format="flac", sample_rate_hz=96_000, bit_depth=24)
    )
    assert not actual.matches_requested(
        AudioQuality(format="flac", sample_rate_hz=96_000, bit_depth=16)
    )
    assert not actual.matches_requested(
        AudioQuality(format="flac", sample_rate_hz=96_000, bit_depth=24, channels=1)
    )


def test_unknown_source_dimensions_are_deferred_until_download() -> None:
    advertised = AudioQuality(format="flac")
    requested = AudioQuality(format="flac", sample_rate_hz=96_000, bit_depth=24)
    assert advertised.may_match_requested(requested)
    assert not AudioQuality(
        format="flac", sample_rate_hz=44_100, bit_depth=16
    ).may_match_requested(requested)
