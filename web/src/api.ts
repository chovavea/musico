import type {
  BoardInfo,
  CatalogPlatform,
  DownloadSummary,
  DownloadTask,
  Envelope,
  FallbackResolution,
  HealthPayload,
  LibraryAsset,
  LyricPayload,
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
// 下载兜底要在服务端串行读好几个页面（每个请求上限 FALLBACK_TIMEOUT_SEC），
// 所以它拿到的超时必须比默认值宽松，否则浏览器先放弃、用户点了没有任何反应。
const FALLBACK_RESOLVE_TIMEOUT_MS = 120_000;
// 设置了 API_TOKEN 的部署要求写操作带令牌。令牌只存在本机浏览器里，由「配置」
// 菜单填写；曲库列表、曲库文件和下载记录也要求令牌（后端按白名单放行榜单、
// 搜索、试听这些公开读接口）。
const API_TOKEN_STORAGE_KEY = "musico-api-token";
// <audio src> / <a href> 这类媒体地址带不了请求头，令牌还要以同源 Cookie 的
// 形式送过去；后端只在 GET/HEAD 上认它，写操作仍然必须带 X-API-Token。
const API_TOKEN_COOKIE_KEY = "musico_api_token";
const AUTH_ERROR_CODE = 40101;
const AUTH_ERROR_MESSAGE = "请在「配置」中填写有效的 API Token";
let activeFullSearch: AbortController | null = null;
// localStorage 不可用（无痕模式 / 禁用存储）时，令牌只活在本页会话里。
let sessionApiToken = "";

export function getApiToken(): string {
  try {
    const stored = globalThis.localStorage?.getItem(API_TOKEN_STORAGE_KEY)?.trim();
    if (stored) return stored;
  } catch {
    // 无痕模式或禁用存储：退回本页会话里的值。
  }
  return sessionApiToken;
}

/** 把已保存的令牌同步进 Cookie；应用启动和保存令牌时各调一次。 */
export function syncApiTokenCookie(): void {
  const doc = globalThis.document;
  if (!doc) return;
  const token = getApiToken();
  const secure = globalThis.location?.protocol === "https:" ? "; Secure" : "";
  doc.cookie = token
    ? `${API_TOKEN_COOKIE_KEY}=${encodeURIComponent(token)}; path=/; SameSite=Strict${secure}`
    : `${API_TOKEN_COOKIE_KEY}=; path=/; SameSite=Strict; Max-Age=0`;
}

export function setApiToken(value: string): void {
  const trimmed = value.trim();
  sessionApiToken = trimmed;
  try {
    if (trimmed) {
      globalThis.localStorage?.setItem(API_TOKEN_STORAGE_KEY, trimmed);
    } else {
      globalThis.localStorage?.removeItem(API_TOKEN_STORAGE_KEY);
    }
  } catch {
    // 无痕模式或禁用存储时，令牌只在本页会话里生效。
  }
  syncApiTokenCookie();
}

function requestHeaders(init?: RequestInit): Headers {
  const headers = new Headers(init?.headers);
  const method = (init?.method ?? "GET").toUpperCase();
  const token = getApiToken();
  if (token && method !== "GET" && method !== "HEAD") {
    headers.set("X-API-Token", token);
  }
  return headers;
}

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

async function getJson<T>(
  url: string,
  init?: RequestInit,
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<Envelope<T>> {
  return sendJson<T>(url, init, timeoutMs);
}

async function sendJson<T>(
  url: string,
  init?: RequestInit,
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<Envelope<T>> {
  const linked = linkSignals(init?.signal ?? undefined, timeoutMs);
  let response: Response;
  let text: string;
  try {
    response = await fetch(url, { ...init, headers: requestHeaders(init), signal: linked.signal });
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
        if (envelope.code === AUTH_ERROR_CODE) envelope.msg = AUTH_ERROR_MESSAGE;
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

export function lyrics(item: {
  platform: string;
  external_id: string;
  title: string;
  artist: string;
  duration_ms?: number | null;
}): Promise<Envelope<LyricPayload>> {
  const query = new URLSearchParams({
    platform: item.platform,
    external_id: item.external_id,
    title: item.title,
    artist: item.artist,
  });
  if (item.duration_ms && item.duration_ms > 0) {
    query.set("duration_ms", String(item.duration_ms));
  }
  return getJson(`/api/v1/lyrics?${query}`);
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

/**
 * Link-out fallback for a failed download. The backend only reads pages; the
 * returned ``url`` is an external share page the caller navigates to.
 */
export function resolveDownloadFallback(id: string): Promise<Envelope<FallbackResolution>> {
  return sendJson(
    `/api/v1/downloads/${encodeURIComponent(id)}/fallback`,
    { method: "POST" },
    FALLBACK_RESOLVE_TIMEOUT_MS,
  );
}

export function listLibrary(): Promise<Envelope<{ items: LibraryAsset[] }>> {
  return getJson("/api/v1/library");
}

export function deleteLibraryAsset(id: string): Promise<Envelope<{ deleted: boolean }>> {
  return sendJson(`/api/v1/library/${encodeURIComponent(id)}`, { method: "DELETE" });
}
