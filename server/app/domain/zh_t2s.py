from __future__ import annotations

from functools import cache
from pathlib import Path

# Character table derived from OpenCC TSCharacters.txt (Apache-2.0).
# https://github.com/BYVoid/OpenCC


@cache
def _table() -> dict[int, int]:
    raw = Path(__file__).with_name("zh_t2s.txt").read_text(encoding="utf-8")
    traditional, simplified, *_rest = raw.splitlines()
    if len(traditional) != len(simplified):
        raise RuntimeError("zh_t2s.txt traditional/simplified lengths differ")
    return str.maketrans(traditional, simplified)


def fold_traditional(text: str) -> str:
    """Map traditional CJK characters to their simplified counterparts."""
    return text.translate(_table())
