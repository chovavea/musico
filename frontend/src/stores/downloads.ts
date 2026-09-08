import { defineStore } from "pinia";
import {
  createDownload,
  deleteLibraryAsset,
  downloadSummary,
  listDownloads,
  listLibrary,
  retryDownload,
  type DownloadTrackPayload,
} from "../api";
import type { DownloadSummary, DownloadTask, LibraryAsset } from "../types";

export const useDownloadsStore = defineStore("downloads", {
  state: () => ({
    summary: null as DownloadSummary | null,
    tasks: [] as DownloadTask[],
    assets: [] as LibraryAsset[],
    loading: false,
    error: "",
    timer: 0,
    initialized: false,
    failureNotice: null as DownloadTask | null,
  }),
  getters: {
    active: (state) => Boolean(state.summary?.active),
    percent: (state) => Math.round((state.summary?.active?.progress ?? 0) * 100),
    hasPending: (state) =>
      Boolean(
        state.summary &&
          Object.entries(state.summary.counts).some(
            ([status, count]) =>
              ["resolving", "queued", "downloading", "retrying"].includes(status) && count > 0,
          ),
      ),
  },
  actions: {
    async refreshSummary() {
      try {
        const response = await downloadSummary();
        if (response.code !== 0) {
          this.error = response.msg || "下载状态读取失败";
          return;
        }
        const previousFailed = this.summary?.counts.failed ?? 0;
        this.summary = response.data;
        if (this.initialized && (response.data.counts.failed ?? 0) > previousFailed) {
          await this.loadTasks();
          this.failureNotice = this.tasks.find((item) => item.status === "failed") ?? null;
        }
        this.initialized = true;
        this.error = "";
        // 仅在仍有未完成任务时保持 1.5s 轮询，空闲后自动停表。
        if (this.hasPending) {
          this.startPolling();
        } else {
          this.stopPolling();
        }
      } catch (error) {
        this.error = error instanceof Error ? error.message : "下载状态读取失败";
      }
    },
    async loadTasks() {
      const response = await listDownloads();
      if (response.code === 0) this.tasks = response.data.items;
    },
    async loadLibrary() {
      const response = await listLibrary();
      if (response.code === 0) this.assets = response.data.items;
    },
    async enqueue(track: DownloadTrackPayload) {
      const response = await createDownload(track);
      if (response.code !== 0) throw new Error(response.msg || "下载任务创建失败");
      this.startPolling();
      await this.refreshSummary();
      return response.data;
    },
    async retry(id: string) {
      const response = await retryDownload(id);
      if (response.code !== 0) throw new Error(response.msg || "重试失败");
      await this.refreshSummary();
      await this.loadTasks();
    },
    async remove(id: string) {
      const response = await deleteLibraryAsset(id);
      if (response.code !== 0) throw new Error(response.msg || "删除失败");
      this.assets = this.assets.filter((item) => item.id !== id);
    },
    startPolling() {
      if (this.timer) return;
      this.timer = window.setInterval(() => {
        void this.refreshSummary();
      }, 1500);
    },
    stopPolling() {
      if (this.timer) window.clearInterval(this.timer);
      this.timer = 0;
    },
  },
});
