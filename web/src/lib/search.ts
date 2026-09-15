import type { RankItem, SearchResult, SearchTrack } from "../types";

export const SEARCH_PAGE_SIZE = 10;
export const SEARCH_SENTINEL_MARGIN_PX = 200;

export function nextVisibleCount(
  visibleCount: number,
  total: number,
  pageSize = SEARCH_PAGE_SIZE,
): number {
  if (total <= 0) return 0;
  return Math.min(total, Math.max(0, visibleCount) + pageSize);
}

export function sentinelNeedsMore(
  sentinelTop: number,
  viewportHeight: number,
  marginPx = SEARCH_SENTINEL_MARGIN_PX,
): boolean {
  return sentinelTop <= viewportHeight + marginPx;
}

export function searchTrackToRankItem(track: SearchTrack): RankItem {
  return {
    rank: 0,
    previous_rank: null,
    normalized_score: 0,
    raw_score: null,
    title: track.title,
    artist: track.artist,
    album: track.album,
    duration_ms: track.duration_ms,
    isrc: track.isrc,
    version: track.version,
    cover_url: track.cover_url,
    official_url: track.official_url,
    external_id: track.external_id,
    platform: track.platform,
    preview_url: null,
    quality: null,
    expire_at: null,
    library_status: track.library_status,
    library_asset_id: track.library_asset_id,
    active_download_id: track.active_download_id,
  };
}

export function resultToRankItem(result: SearchResult): RankItem {
  return searchTrackToRankItem(result);
}
