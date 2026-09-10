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

type LocalDownloadState = {
  status: "queued" | "ready";
  taskId?: string;
  assetId?: string;
  trackId?: string;
};

const ACTIVE_STATUSES = ["resolving", "queued", "downloading", "retrying"];

export const useDownloadsStore = defineStore("downloads", {
  state: () => ({
    summary: null as DownloadSummary | null,
    tasks: [] as DownloadTask[],
    assets: [] as LibraryAsset[],
    loading: false,
    error: "",
    timer: 0,
    initialized: false,
    libraryLoaded: false,
    failureNotice: null as DownloadTask | null,
    localStates: {} as Record<string, LocalDownloadState>,
    deletedAssetIds: {} as Record<string, boolean>,
    actionError: "",
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
        const previousActiveId = this.summary?.active?.id ?? null;
        const previousActiveStatus = this.summary?.active?.status ?? null;
        const previousFailed = this.summary?.counts.failed ?? 0;
        const previousCompleted = this.summary?.counts.completed ?? 0;
        this.summary = response.data;
        const activeId = response.data.active?.id ?? null;
        const activeStatus = response.data.active?.status ?? null;
        const activeChanged =
          previousActiveId !== activeId || previousActiveStatus !== activeStatus;
        const completedChanged =
          (response.data.counts.completed ?? 0) !== previousCompleted;
        const failedChanged = (response.data.counts.failed ?? 0) !== previousFailed;
        if (this.initialized && (activeChanged || completedChanged || failedChanged)) {
          await this.loadTasks();
          if (failedChanged && (response.data.counts.failed ?? 0) > previousFailed) {
            this.failureNotice = this.tasks.find((item) => item.status === "failed") ?? null;
          }
        }
        if (
          this.initialized &&
          (completedChanged || activeChanged || (this.summary.active == null && previousActiveId != null))
        ) {
          await this.loadLibrary();
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
      if (response.code === 0) {
        this.tasks = response.data.items;
        this.syncLocalStates();
      }
    },
    async loadLibrary() {
      const response = await listLibrary();
      if (response.code === 0) {
        this.assets = response.data.items;
        this.libraryLoaded = true;
        this.syncLocalStates();
      }
    },
    async enqueue(track: DownloadTrackPayload) {
      const response = await createDownload(track);
      if (response.code !== 0) throw new Error(response.msg || "下载任务创建失败");
      this.startPolling();
      await this.refreshSummary();
      return response.data;
    },
    markLocalQueued(key: string, taskId?: string) {
      this.localStates[key] = { status: "queued", taskId };
    },
    markLocalReady(key: string, assetId?: string, trackId?: string) {
      this.localStates[key] = { status: "ready", assetId, trackId };
    },
    clearLocalState(key: string) {
      delete this.localStates[key];
    },
    setActionError(message: string) {
      this.actionError = message;
    },
    clearActionError() {
      this.actionError = "";
    },
    syncLocalStates() {
      for (const [key, local] of Object.entries(this.localStates)) {
        if (local.taskId) {
          const task = this.tasks.find((item) => item.id === local.taskId);
          if (!task) continue;
          if (task.status === "completed") {
            const asset = this.assets.find(
              (item) => item.track_id === task.track_id && item.status === "ready",
            );
            // Keep the task id until the library refresh catches up. Without
            // it, a loadTasks-before-loadLibrary race can leave a permanent
            // ready state with no asset id, which deletion cannot clear.
            this.localStates[key] = asset
              ? { status: "ready", assetId: asset.id, trackId: asset.track_id }
              : { status: "ready", taskId: task.id };
          } else if (task.status === "failed") {
            delete this.localStates[key];
          } else if (ACTIVE_STATUSES.includes(task.status)) {
            this.localStates[key] = { status: "queued", taskId: task.id };
          }
          continue;
        }
        if (local.status === "ready" && local.assetId && this.libraryLoaded) {
          const asset = this.assets.find(
            (item) => item.id === local.assetId && item.status === "ready",
          );
          if (!asset) {
            delete this.localStates[key];
          }
        }
      }
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
      const asset = this.assets.find((item) => item.id === id);
      this.deletedAssetIds[id] = true;
      const deletedTrackTaskIds = new Set(
        asset
          ? this.tasks
              .filter((item) => item.track_id === asset.track_id)
              .map((item) => item.id)
          : [],
      );
      for (const [key, local] of Object.entries(this.localStates)) {
        if (
          local.assetId === id ||
          deletedTrackTaskIds.has(local.taskId ?? "") ||
          (asset && local.trackId === asset.track_id)
        ) {
          delete this.localStates[key];
        }
      }
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
