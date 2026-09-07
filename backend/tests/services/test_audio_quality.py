from app.domain.models import AudioQuality


def test_quality_prefers_hires_flac_over_cd_wav() -> None:
    hires_flac = AudioQuality(format="flac", sample_rate_hz=96_000, bit_depth=24)
    cd_wav = AudioQuality(format="wav", sample_rate_hz=44_100, bit_depth=16)
    assert hires_flac.sort_key() > cd_wav.sort_key()


def test_quality_prefers_dsd_container() -> None:
    dsd = AudioQuality(format="dsf", dsd_rate="DSD64")
    hires_flac = AudioQuality(format="flac", sample_rate_hz=192_000, bit_depth=24)
    assert dsd.sort_key() > hires_flac.sort_key()
