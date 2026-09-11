def normalized_score(rank: int, n: int) -> float:
    if n <= 1:
        return 100.0
    return 100.0 * (n - rank) / (n - 1)
