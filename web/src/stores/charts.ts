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

export const useChartsStore = defineStore("charts", {
  state: () => ({
    boards: [] as BoardInfo[],
    platforms: [] as PlatformInfo[],
    catalog: [] as CatalogPlatform[],
    latest: {} as Record<string, LatestBoard>,
    loading: false,
    error: "",
  }),
  actions: {
    async loadBoards() {
      try {
        const res = await listBoards();
        if (res.code === 0) {
          this.boards = res.data.filter((item) => item.enabled);
          this.error = "";
        } else {
          this.error = res.msg || "榜单加载失败";
        }
      } catch (err) {
        this.error = err instanceof Error ? err.message : "榜单加载失败";
      }
    },
    async loadPlatforms() {
      try {
        const res = await listPlatforms();
        if (res.code === 0) {
          this.platforms = res.data;
        }
      } catch {
        this.platforms = [];
      }
    },
    async loadCatalog() {
      const res = await listCatalog();
      if (res.code === 0) {
        this.catalog = res.data.platforms;
      }
    },
    async refreshLatest(id: string) {
      try {
        const res = await latestBoard(id);
        if (res.data && Array.isArray(res.data.items)) {
          this.latest[id] = res.data;
          this.error = "";
          return;
        }
        if (res.msg) this.error = res.msg;
      } catch (err) {
        const msg = err instanceof Error ? err.message : "榜单加载失败";
        if (!this.latest[id]?.items.length) this.error = msg;
      }
    },
    async refreshCatalogLatest(platform: string, chartKey: string, boardId: string) {
      try {
        const res = await catalogLatest(platform, chartKey);
        if (res.data && Array.isArray(res.data.items)) {
          this.latest[boardId] = { ...res.data, board_id: boardId };
          this.error = "";
          return;
        }
        if (res.msg) this.error = res.msg;
      } catch (err) {
        const msg = err instanceof Error ? err.message : "榜单加载失败";
        if (!this.latest[boardId]?.items.length) this.error = msg;
      }
    },
    async ensureLatest(board: BoardInfo) {
      if (this.latest[board.id]?.items.length) return;
      if (board.id.startsWith("catalog:") && board.chart_key) {
        await this.refreshCatalogLatest(board.platform, board.chart_key, board.id);
        return;
      }
      await this.refreshLatest(board.id);
    },
    /**
     * 轮询入口：yaml 榜单按服务端 staleness 判定；目录榜（catalog:）按拉取时间与 1 小时
     * 周期判定，避免每分钟打无意义的 live 请求。
     */
    async refreshLatestEntry(id: string) {
      const board = this.latest[id];
      if (board?.staleness === "fresh" && board.items.length) return;
      if (board) {
        const fetchedAt = board.fetched_at ?? board.updated_at;
        const ageMs = fetchedAt ? Date.now() - Date.parse(fetchedAt) : Number.NaN;
        if (!Number.isNaN(ageMs) && ageMs < CATALOG_REFRESH_MS) return;
      }
      if (id.startsWith("catalog:")) {
        const [, platform, ...rest] = id.split(":");
        const chartKey = rest.join(":");
        if (platform && chartKey) {
          await this.refreshCatalogLatest(platform, chartKey, id);
          return;
        }
      }
      await this.refreshLatest(id);
    },
    async moveBoard(id: string, direction: "up" | "down") {
      const res = await moveBoard(id, direction);
      if (res.code === 0 && Array.isArray(res.data)) {
        this.boards = res.data.filter((item) => item.enabled);
        return;
      }
      this.error = res.msg || "调整顺序失败";
    },
    async moveCatalogChart(platform: string, chartKey: string, direction: "up" | "down") {
      const res = await moveCatalogChart(platform, chartKey, direction);
      if (res.code === 0 && res.data?.groups) {
        this.catalog = this.catalog.map((item) =>
          item.id === platform ? { ...item, groups: res.data.groups } : item,
        );
        return;
      }
      this.error = res.msg || "调整顺序失败";
    },
    async reorderCatalogChart(platform: string, chartKey: string, beforeKey: string | null) {
      try {
        const res = await reorderCatalogChart(platform, chartKey, beforeKey);
        if (res.code === 0 && res.data?.groups) {
          this.catalog = this.catalog.map((item) =>
            item.id === platform ? { ...item, groups: res.data.groups } : item,
          );
          this.error = "";
          return true;
        }
        this.error = res.msg || "调整顺序失败";
      } catch {
        this.error = "调整顺序失败，请重试";
      }
      try {
        await this.loadCatalog();
      } catch {
        // 重排与回拉都失败时，重建该平台 groups 引用，通知下拉清除乐观状态，
        // 列表立即回到服务端顺序而不是停留在本地假顺序。
        this.catalog = this.catalog.map((item) =>
          item.id === platform ? { ...item, groups: [...item.groups] } : item,
        );
      }
      return false;
    },
    async refreshAll() {
      this.loading = true;
      this.error = "";
      try {
        await Promise.all([this.loadBoards(), this.loadPlatforms()]);
        await Promise.all(this.boards.map((board) => this.refreshLatest(board.id)));
        void this.loadCatalog().catch(() => {
          this.catalog = this.catalog.length ? this.catalog : [];
        });
      } catch (err) {
        this.error = err instanceof Error ? err.message : "加载失败";
      } finally {
        this.loading = false;
      }
    },
  },
});
