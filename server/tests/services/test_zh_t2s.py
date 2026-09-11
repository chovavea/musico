from app.domain.zh_t2s import fold_traditional


def test_fold_traditional_maps_common_song_metadata() -> None:
    assert fold_traditional("米津玄師") == "米津玄师"
    assert fold_traditional("米津玄师") == "米津玄师"
    assert fold_traditional("周杰倫") == "周杰伦"
