from typing import Protocol

from app.domain.models import RawRankItem


class SearchPort(Protocol):
    async def search(self, q: str) -> list[RawRankItem]: ...
