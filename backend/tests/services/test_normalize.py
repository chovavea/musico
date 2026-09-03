from app.domain.normalize import normalized_score


def test_normalize_single_item() -> None:
    assert normalized_score(1, 1) == 100.0


def test_normalize_zero_or_empty() -> None:
    assert normalized_score(1, 0) == 100.0


def test_normalize_scale() -> None:
    assert normalized_score(1, 3) == 100.0
    assert normalized_score(2, 3) == 50.0
    assert normalized_score(3, 3) == 0.0
