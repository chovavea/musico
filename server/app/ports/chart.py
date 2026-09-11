from typing import Protocol

from app.domain.models import BoardSpec, RawRankItem


class ChartPort(Protocol):
    async def fetch_board(self, board_config: BoardSpec) -> list[RawRankItem]: ...
