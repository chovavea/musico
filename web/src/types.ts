export type Staleness = "fresh" | "stale" | "missing";

export interface Envelope<T> {
  code: number;
  data: T;
  msg: string;
  extra?: Record<string, unknown>;
  chart_key?: string | null;
  sort_order?: number;
}

export interface PlatformInfo {
  id: string;
  name: string;
}

export type SearchPlatformStatus = "ok" | "empty" | "error";

export interface SearchPlatformStatusInfo {
  id: string;
  name: string;
  status: SearchPlatformStatus;
  result_count: number;
}

export interface SearchTrack {
  platform: string;
  external_id: string;
  title: string;
  artist: string;
  album: string | null;
  duration_ms: number | null;
  isrc: string | null;
  version: string | null;
  cover_url: string | null;
  official_url: string | null;
  search_rank: number;
  library_status: "ready" | "missing" | null;
  library_asset_id: string | null;
  active_download_id: string | null;
}

export interface SearchResult extends SearchTrack {
  platforms: SearchTrack[];
  platform_count: number;
}

export interface SearchPayload {
  query: string;
  type: "suggest" | "full";
  items: SearchResult[];
  platforms: SearchPlatformStatusInfo[];
  partial: boolean;
  reason?: string;
}

export interface BoardInfo {
  id: string;
  platform: string;
  name: string;
  type: string;
  enabled: boolean;
  interval_sec: number;
  extra?: Record<string, unknown>;
  chart_key?: string | null;
  overview_slot?: "left" | "right" | null;
  sort_order?: number;
}

export interface CatalogChart {
  key: string;
  name: string;
  playable: boolean;
  sort_order?: number;
}

export interface CatalogGroup {
  name: string;
  charts: CatalogChart[];
}

export interface CatalogPlatform {
  id: string;
  name: string;
  groups: CatalogGroup[];
}

export interface RankItem {
  rank: number;
  previous_rank: number | null;
  normalized_score: number;
  raw_score: number | null;
  title: string;
  artist: string;
  album?: string | null;
  duration_ms?: number | null;
  isrc?: string | null;
  version?: string | null;
  cover_url: string | null;
  official_url: string | null;
  external_id: string;
  platform: string;
  preview_url: string | null;
  quality: "low" | "medium" | null;
  expire_at: string | null;
  library_status?: "ready" | "missing" | "deleting" | null;
  library_asset_id?: string | null;
  active_download_id?: string | null;
}

export interface LatestBoard {
  board_id: string;
  snapshot_id?: string;
  fetched_at?: string;
  updated_at?: string;
  staleness: Staleness;
  items: RankItem[];
}

export interface HealthSource {
  board_id: string;
  platform: string;
  name: string;
  last_success_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  last_latency_ms: number | null;
  last_item_count: number | null;
}

export interface HealthPayload {
  status: "starting" | "ready" | "degraded";
  staleness_multiplier: number;
  sources: HealthSource[];
}

export type DownloadStatus =
  | "resolving"
  | "queued"
  | "downloading"
  | "retrying"
  | "completed"
  | "failed"
  | "missing";

export interface DownloadTask {
  id: string;
  track_id: string;
  title: string | null;
  artist: string | null;
  status: DownloadStatus;
  bytes_done: number;
  bytes_total: number | null;
  progress: number | null;
  attempt_count: number;
  max_attempts: number;
  selected_source_id: string | null;
  selected_quality: Record<string, unknown> | null;
  source_page_url: string | null;
  last_error: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface LibraryAsset {
  id: string;
  track_id: string;
  title: string;
  artist: string;
  album: string | null;
  format: string;
  sample_rate_hz: number | null;
  bit_depth: number | null;
  channels: number | null;
  dsd_rate: string | null;
  relative_path: string;
  file_size: number;
  sha256: string | null;
  status: "ready" | "missing" | "deleting";
  downloaded_at: string | null;
}

export interface DownloadSummary {
  counts: Record<string, number>;
  active: DownloadTask | null;
}
