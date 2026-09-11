import { defineStore } from "pinia";
import {
  catalogLatest,
  latestBoard,
  listBoards,
  listCatalog,
  listPlatforms,
  moveBoard,
  moveCatalogChart,
  reorderCatalogChart,
} from "../api";
import type { BoardInfo, CatalogPlatform, LatestBoard, PlatformInfo } from "../types";

/** 目录榜（非 yaml 配置）没有服务端快照，沿用后端 live_spec 的 1 小时刷新周期。 */
const CATALOG_REFRESH_MS = 60 * 60 * 1000;
const latestRequests = new WeakMap<object, Map<string, Promise<void>>>();

type LatestStoreTarget = {
  latest: Record<string, LatestBoard>;
  latestLoading: Record<string, boolean>;
  latestErrors: Record<string, string>;
  syncError: () => void;
};

function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

function requestMap(store: object): Map<string, Promise<void>> {
  let requests = latestRequests.get(store);
  if (!requests) {
    requests = new Map();
    latestRequests.set(store, requests);
  }
  return requests;
}

function loadLatest(
  store: LatestStoreTarget,
  boardId: string,
  request: () => Promise<{ code: number; data: LatestBoard; msg: string }>,
): Promise<void> {
  const requests = requestMap(store);
  const inflight = requests.get(boardId);
  if (inflight) return inflight;

  store.latestLoading[boardId] = true;
  let promise!: Promise<void>;
  promise = (async () => {
    try {
      const response = await Promise.resolve().then(request);
      if (response.code === 0 && response.data && Array.isArray(response.data.items)) {
        store.latest[boardId] = { ...response.data, board_id: boardId };
        delete store.latestErrors[boardId];
      } else {
        store.latestErrors[boardId] = response.msg || "榜单加载失败";
      }
    } catch (reason) {
      store.latestErrors[boardId] = errorMessage(reason, "榜单加载失败");
    } finally {
      delete store.latestLoading[boardId];
      if (requests.get(boardId) === promise) requests.delete(boardId);
      store.syncError();
    }
  })();
  requests.set(boardId, promise);
  return promise;
}

function cloneCatalogPlatform(platform: CatalogPlatform): CatalogPlatform {
  return {
    ...platform,
    groups: platform.groups.map((group) => ({
      ...group,
      charts: group.charts.map((chart) => ({ ...chart })),
    })),
  };
}

function orderedBoards(boards: BoardInfo[]): BoardInfo[] {
  return boards
    .slice()
    .sort(
      (left, right) =>
        (left.sort_order ?? 10_000) - (right.sort_order ?? 10_000) ||
        left.id.localeCompare(right.id),
    );
}

export const useChartsStore = defineStore("charts", {
  state: () => ({
    boards: [] as BoardInfo[],
    platforms: [] as PlatformInfo[],
    catalog: [] as CatalogPlatform[],
    latest: {} as Record<string, LatestBoard>,
    loading: false,
    error: "",
    loadErrors: {} as Partial<Record<"boards" | "platforms" | "catalog", string>>,
    latestLoading: {} as Record<string, boolean>,
    latestErrors: {} as Record<string, string>,
    boardMovePending: false,
    catalogMovePending: {} as Record<string, boolean>,
    catalogReorderPending: {} as Record<string, boolean>,
    actionError: "",
  }),
  actions: {
    syncError() {
      this.error =
        this.actionError ||
        this.loadErrors.boards ||
        this.loadErrors.catalog ||
        this.loadErrors.platforms ||
        Object.values(this.latestErrors)[0] ||
        "";
    },
    async loadBoards() {
      try {
        const res = await listBoards();
        if (res.code === 0) {
          this.boards = res.data.filter((item) => item.enabled);
          delete this.loadErrors.boards;
        } else {
          this.loadErrors.boards = res.msg || "榜单加载失败";
        }
      } catch (err) {
        this.loadErrors.boards = errorMessage(err, "榜单加载失败");
      } finally {
        this.syncError();
      }
    },
    async loadPlatforms() {
      try {
        const res = await listPlatforms();
        if (res.code === 0) {
          this.platforms = res.data;
          delete this.loadErrors.platforms;
        } else {
          this.loadErrors.platforms = res.msg || "平台加载失败";
        }
      } catch (err) {
        this.loadErrors.platforms = errorMessage(err, "平台加载失败");
      } finally {
        this.syncError();
      }
    },
    async loadCatalog() {
      try {
        const res = await listCatalog();
        if (res.code === 0) {
          this.catalog = res.data.platforms;
          delete this.loadErrors.catalog;
          return true;
        }
        this.loadErrors.catalog = res.msg || "目录加载失败";
      } catch (err) {
        this.loadErrors.catalog = errorMessage(err, "目录加载失败");
      } finally {
        this.syncError();
      }
      return false;
    },
    refreshLatest(id: string) {
      return loadLatest(this, id, () => latestBoard(id));
    },
    refreshCatalogLatest(platform: string, chartKey: string, boardId: string) {
      return loadLatest(this, boardId, () => catalogLatest(platform, chartKey));
    },
    async ensureLatest(board: BoardInfo) {
      if (board.id.startsWith("catalog:") && board.chart_key) {
        const current = this.latest[board.id];
        if (current?.items.length) {
          const fetchedAt = current.fetched_at ?? current.updated_at;
          const ageMs = fetchedAt ? Date.now() - Date.parse(fetchedAt) : Number.NaN;
          if (!Number.isNaN(ageMs) && ageMs < CATALOG_REFRESH_MS) return;
        }
        await this.refreshCatalogLatest(board.platform, board.chart_key, board.id);
        return;
      }
      const current = this.latest[board.id];
      if (current?.staleness === "fresh" && current.items.length) return;
      await this.refreshLatest(board.id);
    },
    /**
     * 轮询入口：yaml 榜单按服务端 staleness 判定；目录榜（catalog:）按拉取时间与 1 小时
     * 周期判定，避免每分钟打无意义的 live 请求。
     */
    async refreshLatestEntry(id: string) {
      const board = this.latest[id];
      if (id.startsWith("catalog:")) {
        if (board?.items.length) {
          const fetchedAt = board.fetched_at ?? board.updated_at;
          const ageMs = fetchedAt ? Date.now() - Date.parse(fetchedAt) : Number.NaN;
          if (!Number.isNaN(ageMs) && ageMs < CATALOG_REFRESH_MS) return;
        }
        const [, platform, ...rest] = id.split(":");
        const chartKey = rest.join(":");
        if (platform && chartKey) {
          await this.refreshCatalogLatest(platform, chartKey, id);
          return;
        }
        this.latestErrors[id] = "目录榜标识无效";
        this.syncError();
        return;
      }
      if (board?.staleness === "fresh" && board.items.length) return;
      await this.refreshLatest(id);
    },
    async moveBoard(id: string, direction: "up" | "down") {
      if (this.boardMovePending) return false;
      const snapshot = this.boards.map((board) => ({ ...board }));
      const ordered = orderedBoards(this.boards);
      const from = ordered.findIndex((board) => board.id === id);
      const to = direction === "up" ? from - 1 : from + 1;
      if (from < 0 || to < 0 || to >= ordered.length) return false;

      [ordered[from], ordered[to]] = [ordered[to], ordered[from]];
      this.boards = ordered.map((board, index) => ({ ...board, sort_order: index }));
      this.boardMovePending = true;
      this.actionError = "";
      this.syncError();
      try {
        const res = await moveBoard(id, direction);
        if (res.code === 0 && Array.isArray(res.data)) {
          this.boards = res.data.filter((item) => item.enabled);
          return true;
        }
        this.boards = snapshot;
        this.actionError = res.msg || "调整顺序失败";
      } catch (err) {
        this.boards = snapshot;
        this.actionError = errorMessage(err, "调整顺序失败");
      } finally {
        this.boardMovePending = false;
        this.syncError();
      }
      return false;
    },
    async moveCatalogChart(platform: string, chartKey: string, direction: "up" | "down") {
      const pendingKey = `${platform}:${chartKey}`;
      if (this.catalogMovePending[pendingKey]) return false;
      const current = this.catalog.find((item) => item.id === platform);
      const snapshot = current ? cloneCatalogPlatform(current) : null;
      let succeeded = false;
      this.catalogMovePending[pendingKey] = true;
      this.actionError = "";
      this.syncError();
      try {
        const res = await moveCatalogChart(platform, chartKey, direction);
        if (res.code === 0 && res.data?.groups) {
          this.catalog = this.catalog.map((item) =>
            item.id === platform ? { ...item, groups: res.data.groups } : item,
          );
          succeeded = true;
          return true;
        }
        this.actionError = res.msg || "调整顺序失败";
      } catch (err) {
        this.actionError = errorMessage(err, "调整顺序失败");
      } finally {
        if (snapshot && !succeeded) {
          this.catalog = this.catalog.map((item) =>
            item.id === platform ? cloneCatalogPlatform(snapshot) : item,
          );
        }
        delete this.catalogMovePending[pendingKey];
        this.syncError();
      }
      return false;
    },
    async reorderCatalogChart(platform: string, chartKey: string, beforeKey: string | null) {
      const pendingKey = `${platform}:${chartKey}`;
      if (this.catalogReorderPending[pendingKey]) return false;
      const current = this.catalog.find((item) => item.id === platform);
      const snapshot = current ? cloneCatalogPlatform(current) : null;
      let succeeded = false;
      this.catalogReorderPending[pendingKey] = true;
      this.actionError = "";
      this.syncError();
      try {
        const res = await reorderCatalogChart(platform, chartKey, beforeKey);
        if (res.code === 0 && res.data?.groups) {
          this.catalog = this.catalog.map((item) =>
            item.id === platform ? { ...item, groups: res.data.groups } : item,
          );
          succeeded = true;
          return true;
        }
        this.actionError = res.msg || "调整顺序失败";
      } catch (err) {
        this.actionError = errorMessage(err, "调整顺序失败，请重试");
      } finally {
        if (snapshot && !succeeded) {
          // 始终替换 groups 引用，使组件清除其拖拽乐观状态。
          this.catalog = this.catalog.map((item) =>
            item.id === platform ? cloneCatalogPlatform(snapshot) : item,
          );
        }
        delete this.catalogReorderPending[pendingKey];
        this.syncError();
      }
      return false;
    },
    async refreshAll() {
      this.loading = true;
      try {
        await Promise.all([this.loadBoards(), this.loadPlatforms()]);
        await Promise.all(this.boards.map((board) => this.ensureLatest(board)));
        void this.loadCatalog();
      } finally {
        this.loading = false;
        this.syncError();
      }
    },
  },
});
