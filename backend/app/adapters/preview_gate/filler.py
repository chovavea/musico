from __future__ import annotations

import asyncio

import structlog

from app.domain.models import PreviewInfo, RawRankItem, TrackRef
from app.ports.preview import PreviewPort

log = structlog.get_logger(__name__)


async def fill_previews(
    items: list[RawRankItem],
    preview: PreviewPort,
    platform: str,
    *,
    min_interval_sec: float,
    concurrency: int = 8,
) -> None:
    missing = [item for item in items if not item.preview_url]
    if not missing:
        return
    semaphore = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    last_at = 0.0
    loop = asyncio.get_running_loop()

    async def one(item: RawRankItem) -> None:
        nonlocal last_at
        async with semaphore:
            async with lock:
                now = loop.time()
                wait = min_interval_sec - (now - last_at)
                if wait > 0:
                    await asyncio.sleep(wait)
                last_at = loop.time()
            try:
                info: PreviewInfo = await preview.preview(
                    TrackRef(
                        platform=platform,
                        external_id=item.external_id,
                        title=item.title,
                        artist=item.artist,
                    )
                )
            except Exception:
                log.exception(
                    "preview_fill_failed",
                    platform=platform,
                    external_id=item.external_id,
                )
                return
            if info.preview_url:
                item.preview_url = info.preview_url
                item.preview_quality = info.quality
                item.preview_expire_at = info.expire_at

    await asyncio.gather(*(one(item) for item in missing))
