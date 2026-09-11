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
  SearchPayload,
} from "./types";

export type ApiErrorKind =
  | "aborted"
  | "timeout"
  | "network"
  | "http"
  | "invalid-response";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly url: string;
  readonly status?: number;

  constructor(
    message: string,
    kind: ApiErrorKind,
    url: string,
    status?: number,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = "ApiError";
    this.kind = kind;
    this.url = url;
    this.status = status;
  }
}

export function isAbortError(reason: unknown): boolean {
  if (reason instanceof ApiError) return reason.kind === "aborted";
  return reason instanceof DOMException && reason.name === "AbortError";
}

const REQUEST_TIMEOUT_MS = 15_000;
let activeFullSearch: AbortController | null = null;

type LinkedSignal = {
  signal: AbortSignal;
  cleanup: () => void;
  timedOut: () => boolean;
};

function linkSignals(external?: AbortSignal, timeoutMs = 0): LinkedSignal {
  const controller = new AbortController();
  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  let didTimeout = false;

  const abortFromExternal = () => controller.abort(external?.reason);
  if (external?.aborted) {
    abortFromExternal();
  } else {
    external?.addEventListener("abort", abortFromExternal, { once: true });
  }
  if (timeoutMs > 0) {
    timeoutId = setTimeout(() => {
      didTimeout = true;
      controller.abort(new DOMException("Request timed out", "TimeoutError"));
    }, timeoutMs);
  }

  return {
    signal: controller.signal,
    cleanup: () => {
      if (timeoutId !== undefined) clearTimeout(timeoutId);
      external?.removeEventListener("abort", abortFromExternal);
    },
    timedOut: () => didTimeout,
  };
}

async function getJson<T>(url: string, init?: RequestInit): Promise<Envelope<T>> {
  return sendJson<T>(url, init);
}

async function sendJson<T>(url: string, init?: RequestInit): Promise<Envelope<T>> {
  const linked = linkSignals(init?.signal ?? undefined, REQUEST_TIMEOUT_MS);
  let response: Response;
  let text: string;
  try {
    response = await fetch(url, { ...init, signal: linked.signal });
    text = await response.text();
  } catch (cause) {
    if (linked.timedOut()) {
      throw new ApiError("请求超时，请检查网络后重试", "timeout", url, undefined, { cause });
    }
    if (linked.signal.aborted) {
      throw new ApiError("请求已取消", "aborted", url, undefined, { cause });
    }
    throw new ApiError("网络连接失败，请稍后重试", "network", url, undefined, { cause });
  } finally {
    linked.cleanup();
  }
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
    throw new ApiError(
      `服务暂时不可用（HTTP ${response.status}）`,
      "http",
      url,
      response.status,
    );
  }
  throw new ApiError("接口返回了无法识别的数据，请稍后重试", "invalid-response", url);
}

export function listPlatforms(): Promise<Envelope<PlatformInfo[]>> {
  return getJson("/api/v1/platforms");
}

export async function searchTracks(
  query: string,
  kind: "suggest" | "full" = "full",
  limit?: number,
  signal?: AbortSignal,
): Promise<Envelope<SearchPayload>> {
  const params = new URLSearchParams({ q: query, type: kind });
  if (limit != null) params.set("limit", String(limit));
  const url = `/api/v1/search?${params.toString()}`;
  if (kind !== "full") {
    return getJson(url, { signal });
  }

  activeFullSearch?.abort(new DOMException("Superseded by a newer search", "AbortError"));
  const controller = new AbortController();
  activeFullSearch = controller;
  const external = linkSignals(signal);
  const abortFullSearch = () => controller.abort(external.signal.reason);
  if (external.signal.aborted) {
    abortFullSearch();
  } else {
    external.signal.addEventListener("abort", abortFullSearch, { once: true });
  }
  try {
    return await getJson(url, { signal: controller.signal });
  } finally {
    external.signal.removeEventListener("abort", abortFullSearch);
    external.cleanup();
    if (activeFullSearch === controller) activeFullSearch = null;
  }
}

export function cancelFullSearch(): void {
  activeFullSearch?.abort(new DOMException("Search cancelled", "AbortError"));
  activeFullSearch = null;
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
