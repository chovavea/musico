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

export interface BoardInfo {
  id: string;
  platform: string;
  name: string;
  type: string;
  enabled: boolean;
  interval_sec: number;
  extra?: Record<string, unknown>;
  chart_key?: string | null;
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
  cover_url: string | null;
  official_url: string | null;
  external_id: string;
  platform: string;
  preview_url: string | null;
  quality: "low" | "medium" | null;
  expire_at: string | null;
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
