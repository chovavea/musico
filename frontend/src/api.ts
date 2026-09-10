import type {
  BoardInfo,
  CatalogPlatform,
  DownloadSummary,
  DownloadTask,
  Envelope,
  HealthPayload,
  LibraryAsset,
  LatestBoard,
  PlatformInfo,
} from "./types";

async function getJson<T>(url: string): Promise<Envelope<T>> {
  return sendJson<T>(url);
}

async function sendJson<T>(url: string, init?: RequestInit): Promise<Envelope<T>> {
  const response = await fetch(url, init);
  const text = await response.text();
  if (text) {
    try {
      const envelope = JSON.parse(text) as Partial<Envelope<T>>;
      if (typeof envelope.code === "number") {
        return envelope as Envelope<T>;
      }
    } catch {
      // Non-JSON upstream error body (proxy / gateway HTML, etc.)
    }
  }
  if (!response.ok) {
    throw new Error(`服务暂时不可用（HTTP ${response.status}）`);
  }
  throw new Error("接口无响应，稍后重试");
}

export function listPlatforms(): Promise<Envelope<PlatformInfo[]>> {
  return getJson("/api/v1/platforms");
}

export function listBoards(): Promise<Envelope<BoardInfo[]>> {
  return getJson("/api/v1/boards");
}

export function moveBoard(
  id: string,
  direction: "up" | "down",
): Promise<Envelope<BoardInfo[]>> {
  return sendJson(`/api/v1/boards/${encodeURIComponent(id)}/move`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ direction }),
  });
}

export function latestBoard(id: string): Promise<Envelope<LatestBoard>> {
  return getJson(`/api/v1/boards/${id}/latest`);
}

export function listCatalog(): Promise<Envelope<{ platforms: CatalogPlatform[] }>> {
  return getJson("/api/v1/catalog");
}

export function moveCatalogChart(
  platform: string,
  chartKey: string,
  direction: "up" | "down",
): Promise<Envelope<CatalogPlatform>> {
  return sendJson(
    `/api/v1/catalog/${encodeURIComponent(platform)}/charts/${encodeURIComponent(chartKey)}/move`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ direction }),
    },
  );
}

export function reorderCatalogChart(
  platform: string,
  chartKey: string,
  beforeKey: string | null,
): Promise<Envelope<CatalogPlatform>> {
  return sendJson(
    `/api/v1/catalog/${encodeURIComponent(platform)}/charts/${encodeURIComponent(chartKey)}/reorder`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ before_key: beforeKey }),
    },
  );
}

export function catalogLatest(
  platform: string,
  chartKey: string,
): Promise<Envelope<LatestBoard>> {
  return getJson(`/api/v1/catalog/${platform}/${encodeURIComponent(chartKey)}/latest`);
}

export function health(): Promise<Envelope<HealthPayload>> {
  return getJson("/api/v1/health");
}

export interface DownloadTrackPayload {
  platform: string;
  external_id: string;
  title: string;
  artist: string;
  album?: string | null;
  duration_ms?: number | null;
  isrc?: string | null;
  version?: string | null;
}

export function createDownload(
  track: DownloadTrackPayload,
): Promise<Envelope<{ state: string; task?: DownloadTask; asset?: LibraryAsset }>> {
  return sendJson("/api/v1/downloads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(track),
  });
}

export function downloadSummary(): Promise<Envelope<DownloadSummary>> {
  return getJson("/api/v1/downloads/summary");
}

export function listDownloads(): Promise<Envelope<{ items: DownloadTask[] }>> {
  return getJson("/api/v1/downloads");
}

export function retryDownload(id: string): Promise<Envelope<DownloadTask>> {
  return sendJson(`/api/v1/downloads/${encodeURIComponent(id)}/retry`, { method: "POST" });
}

export function listLibrary(): Promise<Envelope<{ items: LibraryAsset[] }>> {
  return getJson("/api/v1/library");
}

export function deleteLibraryAsset(id: string): Promise<Envelope<{ deleted: boolean }>> {
  return sendJson(`/api/v1/library/${encodeURIComponent(id)}`, { method: "DELETE" });
}
