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

function streamUrl(item: RankItem): string {
  if (hasLocalAsset(item) && item.library_asset_id) {
    return `/api/v1/library/${encodeURIComponent(item.library_asset_id)}/stream`;
  }
  return `/api/v1/preview/${encodeURIComponent(item.platform)}/${encodeURIComponent(item.external_id)}/stream`;
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

function sameAudioSource(audio: HTMLAudioElement, item: RankItem): boolean {
  const expected = new URL(streamUrl(item), document.baseURI).href;
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
  }),
  getters: {
    canPreview: () => previewPlayable,
    progress: (state) => (state.duration > 0 ? state.currentTime / state.duration : 0),
    hasQueue: (state) => state.queue.length > 1,
    usingOfficial: (state) => Boolean(state.current && isQQOfficial(state.current)),
  },
  actions: {
    ensureAudio(): HTMLAudioElement {
      if (this.audio) {
        return this.audio;
      }
      const audio = new Audio();
      audio.addEventListener("ended", () => {
        this.playing = false;
        this.currentTime = 0;
        this.next();
      });
      audio.addEventListener("error", () => {
        if (!this.current || isQQOfficial(this.current)) {
          return;
        }
        // 本地曲库走 /library/{asset_id}/stream，不包含 external_id，
        // 因此按 streamUrl 生成的完整源地址匹配，避免错误被静默吞掉。
        if (!sameAudioSource(audio, this.current)) {
          return;
        }
        this.playing = false;
        this.failed = true;
        this.failStreak += 1;
        if (this.queue.length > 1 && this.failStreak < 3) {
          this.next();
        }
      });
      audio.addEventListener("timeupdate", () => {
        if (isQQOfficial(this.current)) {
          return;
        }
        this.currentTime = audio.currentTime;
      });
      audio.addEventListener("loadedmetadata", () => {
        if (isQQOfficial(this.current)) {
          return;
        }
        this.duration = Number.isFinite(audio.duration) ? audio.duration : 0;
      });
      this.audio = audio;
      return audio;
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
        if (!current || !isQQOfficial(current)) {
          return;
        }
        const playingMid = official.data?.song?.mid;
        if (playingMid && playingMid !== current.external_id) {
          official.pause();
          this.playing = false;
          this.failed = true;
          return;
        }
        this.playing = true;
        this.failed = false;
        this.failStreak = 0;
        const duration = official.duration;
        this.duration = Number.isFinite(duration) ? duration : this.duration;
      });
      official.on("pause", () => {
        if (!isQQOfficial(this.current)) {
          return;
        }
        this.playing = false;
      });
      official.on("ended", () => {
        if (!isQQOfficial(this.current)) {
          return;
        }
        this.playing = false;
        this.currentTime = 0;
        this.next();
      });
      official.on("timeupdate", (event: QQOfficialEvent) => {
        if (!isQQOfficial(this.current)) {
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
        if (!isQQOfficial(this.current)) {
          return;
        }
        this.playing = false;
        this.failed = true;
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
      this.failed = false;
      this.current = item;
      this.currentTime = 0;
      this.duration = 0;
      this.playing = false;
      if (isQQOfficial(item)) {
        this.stopLocalAudio();
        void this.startOfficial(item);
        return;
      }
      pauseQQOfficialPlayer();
      const audio = this.ensureAudio();
      audio.src = streamUrl(item);
      void audio.play().then(
        () => {
          this.playing = true;
          this.failStreak = 0;
        },
        () => {
          this.playing = false;
          this.failed = true;
        },
      );
    },
    async startOfficial(item: RankItem) {
      try {
        const official = await loadQQOfficialPlayer();
        const current = this.current;
        if (!current || !isQQOfficial(current) || current.external_id !== item.external_id) {
          return;
        }
        this.bindOfficial(official);
        official.play(item.external_id, { target: "web" });
      } catch {
        const current = this.current;
        if (current && isQQOfficial(current) && current.external_id === item.external_id) {
          this.playing = false;
          this.failed = true;
        }
      }
    },
    toggle() {
      if (!this.current) {
        return;
      }
      if (isQQOfficial(this.current)) {
        getQQOfficialPlayer()?.toggle();
        return;
      }
      if (!this.audio) {
        return;
      }
      if (this.playing) {
        this.audio.pause();
        this.playing = false;
      } else {
        void this.audio.play();
        this.playing = true;
      }
    },
    next() {
      if (this.index + 1 >= this.queue.length) {
        this.playing = false;
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
      if (isQQOfficial(this.current)) {
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
    openOfficial(item: RankItem) {
      if (item.official_url) {
        window.open(item.official_url, "_blank", "noopener");
      }
    },
  },
});

export { previewPlayable };
