import { defineStore } from "pinia";
import {
  getQQOfficialPlayer,
  loadQQOfficialPlayer,
  pauseQQOfficialPlayer,
  type QQOfficialEvent,
  type QQOfficialPlayer,
} from "../lib/qq-official-player";
import { useDownloadsStore } from "./downloads";
import type { RankItem } from "../types";

function sameTrack(left: RankItem, right: RankItem): boolean {
  return left.platform === right.platform && left.external_id === right.external_id;
}

function hasLocalAsset(item: RankItem): boolean {
  if (!item.library_asset_id || item.library_status !== "ready") {
    return false;
  }
  return !useDownloadsStore().deletedAssetIds[item.library_asset_id];
}

function streamUrl(item: RankItem, downloadOnly = false): string {
  if (hasLocalAsset(item) && item.library_asset_id) {
    return `/api/v1/library/${encodeURIComponent(item.library_asset_id)}/stream`;
  }
  const query = new URLSearchParams({ title: item.title, artist: item.artist });
  for (const field of ["album", "isrc", "version"] as const) {
    if (item[field]) query.set(field, item[field]);
  }
  if (item.duration_ms && item.duration_ms > 0) {
    query.set("duration_ms", String(item.duration_ms));
  }
  if (downloadOnly) query.set("download_only", "true");
  return `/api/v1/preview/${encodeURIComponent(item.platform)}/${encodeURIComponent(item.external_id)}/stream?${query}`;
}

function previewPlayable(item: RankItem): boolean {
  if (item.platform === "qqmusic") {
    return Boolean(item.external_id);
  }
  if (item.preview_url && (!item.expire_at || Date.parse(item.expire_at) > Date.now())) {
    return true;
  }
  return Boolean(item.platform && item.external_id);
}

function isQQOfficial(item: RankItem | null): boolean {
  return item?.platform === "qqmusic" && !hasLocalAsset(item);
}

function sameAudioSource(audio: HTMLAudioElement, item: RankItem, downloadOnly: boolean): boolean {
  const expected = new URL(streamUrl(item, downloadOnly), document.baseURI).href;
  return audio.src === expected;
}

export const usePlayerStore = defineStore("player", {
  state: () => ({
    current: null as RankItem | null,
    queue: [] as RankItem[],
    index: -1,
    playing: false,
    audio: null as HTMLAudioElement | null,
    failed: false,
    failStreak: 0,
    currentTime: 0,
    duration: 0,
    officialBound: false,
    officialPlaybackId: 0,
    playbackMode: "stream" as "official" | "stream",
    playbackId: 0,
    downloadOnly: false,
    loading: false,
    loadState: "idle" as "idle" | "loading" | "ready" | "cancelled" | "failed",
    wantsPlayback: false,
    officialTimer: null as ReturnType<typeof setTimeout> | null,
  }),
  getters: {
    canPreview: () => previewPlayable,
    progress: (state) => (state.duration > 0 ? state.currentTime / state.duration : 0),
    hasQueue: (state) => state.queue.length > 1,
    hasPrev: (state) => state.index > 0,
    hasNext: (state) => state.index >= 0 && state.index + 1 < state.queue.length,
    loadCancelled: (state) => state.loadState === "cancelled",
    usingOfficial: (state) => Boolean(state.current && state.playbackMode === "official"),
  },
  actions: {
    ensureAudio(): HTMLAudioElement {
      if (this.audio) {
        return this.audio;
      }
      const audio = new Audio();
      audio.addEventListener("ended", () => {
        if (this.usingOfficial || !this.current ||
            !sameAudioSource(audio, this.current, this.downloadOnly)) {
          return;
        }
        this.playing = false;
        this.currentTime = 0;
        this.next();
      });
      audio.addEventListener("error", () => {
        if (!this.current || this.usingOfficial || !this.wantsPlayback) {
          return;
        }
        // 本地曲库走 /library/{asset_id}/stream，不包含 external_id，
        // 因此按 streamUrl 生成的完整源地址匹配，避免错误被静默吞掉。
        if (!sameAudioSource(audio, this.current, this.downloadOnly)) {
          return;
        }
        this.failPlayback(this.playbackId);
      });
      audio.addEventListener("timeupdate", () => {
        if (this.usingOfficial || !this.current ||
            !sameAudioSource(audio, this.current, this.downloadOnly)) {
          return;
        }
        this.currentTime = audio.currentTime;
      });
      audio.addEventListener("loadedmetadata", () => {
        if (this.usingOfficial || !this.current ||
            !sameAudioSource(audio, this.current, this.downloadOnly)) {
          return;
        }
        this.duration = Number.isFinite(audio.duration) ? audio.duration : 0;
      });
      this.audio = audio;
      return audio;
    },
    clearOfficialTimer() {
      if (this.officialTimer !== null) {
        clearTimeout(this.officialTimer);
        this.officialTimer = null;
      }
    },
    waitForOfficial(playbackId: number) {
      this.clearOfficialTimer();
      this.officialTimer = setTimeout(() => {
        if (this.playbackId === playbackId) this.startFallback();
      }, 12_000);
    },
    stopLocalAudio() {
      if (!this.audio) {
        return;
      }
      this.audio.pause();
      this.audio.removeAttribute("src");
      this.audio.load();
    },
    bindOfficial(official: QQOfficialPlayer) {
      if (this.officialBound) {
        return;
      }
      this.officialBound = true;
      official.on("play", () => {
        const current = this.current;
        // A new official session is only armed right before the SDK is told which
        // song to play, so an event arriving with a stale id belongs to the song
        // we already left behind.
        if (!current || !this.usingOfficial || !this.wantsPlayback ||
            this.officialPlaybackId !== this.playbackId) {
          // The SDK may finish loading after we have already switched sources.
          official.pause();
          return;
        }
        const playingMid = official.data?.song?.mid;
        if (playingMid && playingMid !== current.external_id) {
          this.startFallback();
          return;
        }
        this.clearOfficialTimer();
        this.loading = false;
        this.loadState = "ready";
        this.playing = true;
        this.failed = false;
        this.failStreak = 0;
        const duration = official.duration;
        this.duration = Number.isFinite(duration) ? duration : this.duration;
      });
      official.on("pause", () => {
        if (!this.usingOfficial || this.officialPlaybackId !== this.playbackId) {
          return;
        }
        this.playing = false;
      });
      official.on("ended", () => {
        if (!this.usingOfficial || !this.wantsPlayback ||
            this.officialPlaybackId !== this.playbackId) {
          return;
        }
        const current = this.current;
        const playingMid = official.data?.song?.mid;
        if (!current || (playingMid && playingMid !== current.external_id)) {
          return;
        }
        // Only a song that actually played can be finished: a late "ended" from
        // the previous song must not advance the queue for a track that has no
        // progress of its own yet.
        if (this.duration <= 0 || this.currentTime <= 0) {
          return;
        }
        this.playing = false;
        this.currentTime = 0;
        this.next();
      });
      official.on("timeupdate", (event: QQOfficialEvent) => {
        if (!this.usingOfficial || this.officialPlaybackId !== this.playbackId) {
          return;
        }
        const time = event.currentTime ?? official.currentTime;
        if (Number.isFinite(time)) {
          this.currentTime = time;
        }
        const duration = official.duration;
        if (Number.isFinite(duration) && duration > 0) {
          this.duration = duration;
        }
      });
      official.on("error", () => {
        const current = this.current;
        const playingMid = official.data?.song?.mid;
        if (!current || !this.usingOfficial || !this.wantsPlayback ||
            this.officialPlaybackId !== this.playbackId) {
          return;
        }
        if (playingMid && playingMid !== current.external_id) {
          return;
        }
        this.startFallback();
      });
    },
    play(item: RankItem, queue?: RankItem[]) {
      this.failStreak = 0;
      this.queue = queue?.length ? queue : [item];
      this.index = this.queue.findIndex((entry) => sameTrack(entry, item));
      if (this.index < 0) {
        this.queue = [item];
        this.index = 0;
      }
      this.start(item);
    },
    start(item: RankItem) {
      this.clearOfficialTimer();
      this.playbackId += 1;
      this.failed = false;
      this.loading = true;
      this.loadState = "loading";
      this.wantsPlayback = true;
      this.downloadOnly = false;
      this.current = item;
      this.currentTime = 0;
      this.duration = 0;
      this.playing = false;
      if (isQQOfficial(item)) {
        this.playbackMode = "official";
        this.stopLocalAudio();
        this.waitForOfficial(this.playbackId);
        void this.startOfficial(item, this.playbackId);
        return;
      }
      this.startAudio(item);
    },
    startAudio(item: RankItem, downloadOnly = false) {
      this.clearOfficialTimer();
      this.officialPlaybackId = 0;
      this.playbackMode = "stream";
      this.downloadOnly = downloadOnly;
      this.loading = true;
      this.loadState = "loading";
      this.playing = false;
      pauseQQOfficialPlayer();
      const audio = this.ensureAudio();
      audio.src = streamUrl(item, downloadOnly);
      this.playAudio(this.playbackId);
    },
    playAudio(playbackId: number) {
      const audio = this.ensureAudio();
      void audio.play().then(
        () => {
          if (this.playbackId !== playbackId || !this.wantsPlayback || this.usingOfficial) {
            return;
          }
          this.loading = false;
          this.loadState = "ready";
          this.playing = true;
          this.failStreak = 0;
        },
        (error: unknown) => {
          if (this.playbackId !== playbackId || !this.wantsPlayback) return;
          if (error instanceof DOMException && error.name === "NotAllowedError") {
            // Browser autoplay policy is not a missing source; allow a manual retry.
            this.pause();
            return;
          }
          this.failPlayback(playbackId);
        },
      );
    },
    startFallback() {
      if (!this.current || !this.usingOfficial || !this.wantsPlayback) return;
      // Keep the same track and queue position. The SDK has already given up on
      // this platform, so let the backend walk its whole ladder: this platform's
      // official preview, another platform's official preview, then the
      // configured download sites. Never advance the queue on a failed source.
      this.currentTime = 0;
      this.duration = 0;
      this.startAudio(this.current);
    },
    failPlayback(playbackId: number) {
      if (this.playbackId !== playbackId || this.failed || !this.wantsPlayback) return;
      // Keep the requested song selected and let the player bar explain the
      // state: skipping ahead would hide that no source could be played.
      this.playing = false;
      this.loading = false;
      this.loadState = "failed";
      this.failed = true;
      this.wantsPlayback = false;
      this.failStreak += 1;
    },
    async startOfficial(item: RankItem, playbackId: number) {
      try {
        const official = await loadQQOfficialPlayer();
        const current = this.current;
        if (this.playbackId !== playbackId || !this.wantsPlayback ||
            !current || !this.usingOfficial || !sameTrack(current, item)) {
          return;
        }
        this.bindOfficial(official);
        this.officialPlaybackId = playbackId;
        official.play(item.external_id, { target: "web" });
      } catch {
        if (this.playbackId === playbackId) this.startFallback();
      }
    },
    pause() {
      const cancelledLoading = this.loading;
      this.playbackId += 1;
      this.clearOfficialTimer();
      this.wantsPlayback = false;
      this.loading = false;
      this.loadState = cancelledLoading ? "cancelled" : this.current ? "ready" : "idle";
      this.playing = false;
      this.audio?.pause();
      pauseQQOfficialPlayer();
    },
    toggle() {
      if (!this.current) {
        return;
      }
      if (this.playing || this.loading) {
        this.pause();
        return;
      }
      if (this.failed) {
        this.failStreak = 0;
        this.start(this.current);
        return;
      }
      this.wantsPlayback = true;
      this.loading = true;
      this.loadState = "loading";
      if (this.usingOfficial) {
        const official = getQQOfficialPlayer();
        if (!official || official.data?.song?.mid !== this.current.external_id) {
          this.start(this.current);
          return;
        }
        this.waitForOfficial(this.playbackId);
        this.officialPlaybackId = this.playbackId;
        try {
          official.toggle(true);
        } catch {
          this.startFallback();
        }
        return;
      }
      this.playAudio(this.playbackId);
    },
    next() {
      if (this.index + 1 >= this.queue.length) {
        return;
      }
      this.index += 1;
      const item = this.queue[this.index];
      if (item) {
        this.start(item);
      }
    },
    prev() {
      if (this.index <= 0) {
        return;
      }
      this.index -= 1;
      const item = this.queue[this.index];
      if (item) {
        this.start(item);
      }
    },
    seek(ratio: number) {
      const nextRatio = Math.min(1, Math.max(0, ratio));
      if (this.usingOfficial) {
        const official = getQQOfficialPlayer();
        if (!official || !Number.isFinite(official.duration) || official.duration <= 0) {
          return;
        }
        official.currentTime = nextRatio * official.duration;
        this.currentTime = official.currentTime;
        return;
      }
      if (!this.audio || !Number.isFinite(this.audio.duration) || this.audio.duration <= 0) {
        return;
      }
      const next = nextRatio * this.audio.duration;
      this.audio.currentTime = next;
      this.currentTime = next;
    },
    openOfficial(item: RankItem): boolean {
      if (!item.official_url) return false;
      try {
        return window.open(item.official_url, "_blank", "noopener") !== null;
      } catch {
        return false;
      }
    },
  },
});

export { previewPlayable };
