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
      const res = await listBoards();
      if (res.code === 0) {
        this.boards = res.data.filter((item) => item.enabled);
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
      const res = await latestBoard(id);
      if (res.data && Array.isArray(res.data.items)) {
        this.latest[id] = res.data;
      }
    },
    async refreshCatalogLatest(platform: string, chartKey: string, boardId: string) {
      const res = await catalogLatest(platform, chartKey);
      if (res.data && Array.isArray(res.data.items)) {
        this.latest[boardId] = { ...res.data, board_id: boardId };
      }
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
      const res = await reorderCatalogChart(platform, chartKey, beforeKey);
      if (res.code === 0 && res.data?.groups) {
        this.catalog = this.catalog.map((item) =>
          item.id === platform ? { ...item, groups: res.data.groups } : item,
        );
        return;
      }
      this.error = res.msg || "调整顺序失败";
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
