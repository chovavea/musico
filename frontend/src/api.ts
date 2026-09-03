import type {
  BoardInfo,
  CatalogPlatform,
  Envelope,
  HealthPayload,
  LatestBoard,
  PlatformInfo,
} from "./types";

async function getJson<T>(url: string): Promise<Envelope<T>> {
  return sendJson<T>(url);
}

async function sendJson<T>(url: string, init?: RequestInit): Promise<Envelope<T>> {
  const response = await fetch(url, init);
  const text = await response.text();
  if (!text) {
    throw new Error("接口无响应，稍后重试");
  }
  return JSON.parse(text) as Envelope<T>;
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
