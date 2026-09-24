<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useLyrics } from "../composables/useLyrics";
import { coverImageUrl } from "../lib/cover-image";
import { formatClock } from "../lib/format";
import { usePlayerStore } from "../stores/player";
import { useThemeStore } from "../stores/theme";
import AppIcon from "./AppIcon.vue";
import CoverImage from "./CoverImage.vue";
import LyricsPanel from "./LyricsPanel.vue";

const player = usePlayerStore();
const theme = useThemeStore();
const lyric = useLyrics();
const percent = computed(() => Math.round(player.progress * 1000) / 10);
const dragging = ref(false);
const lyricsOpen = ref(false);
const root = ref<HTMLElement | null>(null);
let heightObserver: ResizeObserver | null = null;

const statusText = computed(() => {
  if (player.failed) return "暂无可用试听源";
  if (player.loading) return player.downloadOnly ? "正在查找可用音源" : "正在加载试听";
  if (player.loadCancelled) return "已取消加载";
  if (player.usingOfficial) return "QQ 官方试听";
  return player.current?.artist ?? "";
});
const barText = computed(() => {
  if (player.failed || player.loading || player.loadCancelled || lyricsOpen.value) {
    return statusText.value;
  }
  if (lyric.status.value === "ready" && lyric.activeText.value) return lyric.activeText.value;
  return statusText.value;
});
const coverBackdrop = computed(() =>
  lyricsOpen.value ? coverImageUrl(player.current?.cover_url, 500) : null,
);
const repeatLabel = computed(() => {
  if (player.repeatMode === "one") return "单曲循环";
  if (player.repeatMode === "all") return "列表循环";
  return "顺序播放";
});
const repeatIcon = computed(() => (player.repeatMode === "one" ? "repeat-one" : "repeat"));
const toggleLabel = computed(() => {
  if (player.loading) return "取消加载";
  if (player.failed) return "重试播放";
  return player.playing ? "暂停" : "播放";
});

function publishHeight() {
  const height = root.value?.offsetHeight ?? 0;
  document.documentElement.style.setProperty("--player-bar-h", `${height}px`);
}

onMounted(() => {
  publishHeight();
  if (typeof ResizeObserver === "undefined" || !root.value) return;
  heightObserver = new ResizeObserver(publishHeight);
  heightObserver.observe(root.value);
});

onBeforeUnmount(() => {
  heightObserver?.disconnect();
  heightObserver = null;
  document.documentElement.style.removeProperty("--player-bar-h");
});

function seekFromPointer(event: PointerEvent) {
  const target = event.currentTarget as HTMLButtonElement;
  const rect = target.getBoundingClientRect();
  player.seek((event.clientX - rect.left) / rect.width);
}

function onSeekPointer(event: PointerEvent) {
  if (!player.current || !player.duration) {
    return;
  }
  if (event.type === "pointerdown") {
    dragging.value = true;
    (event.currentTarget as HTMLButtonElement).setPointerCapture(event.pointerId);
  }
  if (event.type === "pointermove" && !dragging.value) {
    return;
  }
  seekFromPointer(event);
}

function onSeekEnd() {
  dragging.value = false;
}

function seekBy(delta: number) {
  if (!player.duration) return;
  player.seek(Math.min(1, Math.max(0, player.progress + delta)));
}

function toggleLyrics() {
  if (!player.current) return;
  lyricsOpen.value = !lyricsOpen.value;
}

function onSeekKey(event: KeyboardEvent) {
  if (!player.current || !player.duration) return;
  if (event.key === "ArrowRight") {
    event.preventDefault();
    seekBy(0.05);
  } else if (event.key === "ArrowLeft") {
    event.preventDefault();
    seekBy(-0.05);
  } else if (event.key === "Home") {
    event.preventDefault();
    player.seek(0);
  } else if (event.key === "End") {
    event.preventDefault();
    player.seek(1);
  }
}
</script>

<template>
  <footer
    v-if="theme.isGlaze"
    ref="root"
    class="gz-player"
    :class="lyricsOpen ? 'is-lyrics' : ''"
    aria-label="播放器"
  >
    <div v-if="coverBackdrop" class="player-cover-bg" aria-hidden="true">
      <img :src="coverBackdrop" alt="" />
    </div>
    <div
      v-if="!lyricsOpen"
      role="slider"
      tabindex="0"
      class="absolute left-3.5 right-3.5 top-0 z-10 h-5 cursor-pointer touch-none"
      :class="!player.duration ? 'cursor-default' : ''"
      aria-label="播放进度"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-valuenow="Math.round(player.progress * 100)"
      :aria-disabled="!player.duration"
      @pointerdown="onSeekPointer"
      @pointermove="onSeekPointer"
      @pointerup="onSeekEnd"
      @pointercancel="onSeekEnd"
      @keydown="onSeekKey"
    >
      <span class="gz-player-progress pointer-events-none">
        <span :style="{ width: `${percent}%` }" />
      </span>
    </div>
    <LyricsPanel v-if="lyricsOpen" @close="lyricsOpen = false" />
    <div
      v-if="lyricsOpen"
      role="slider"
      tabindex="0"
      class="gz-seek cursor-pointer touch-none"
      :class="!player.duration ? 'cursor-default' : ''"
      aria-label="播放进度"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-valuenow="Math.round(player.progress * 100)"
      :aria-disabled="!player.duration"
      @pointerdown="onSeekPointer"
      @pointermove="onSeekPointer"
      @pointerup="onSeekEnd"
      @pointercancel="onSeekEnd"
      @keydown="onSeekKey"
    >
      <span class="gz-seek-track pointer-events-none">
        <span :style="{ width: `${percent}%` }" />
      </span>
    </div>
    <div class="gz-player-body" :class="lyricsOpen ? 'is-dock' : ''">
      <div v-if="!lyricsOpen" class="flex min-w-0 items-center gap-3">
        <CoverImage
          :src="player.current?.cover_url"
          :size="150"
          :alt="player.current?.title ?? ''"
          class="h-11 w-11 shrink-0 rounded-xl object-cover"
        />
        <div class="min-w-0">
          <div class="gz-title">{{ player.current?.title }}</div>
          <button
            type="button"
            class="gz-artist block w-full truncate bg-transparent p-0 text-left"
            :class="player.failed ? 'text-rose-400' : ''"
            aria-label="歌词"
            :aria-pressed="lyricsOpen"
            @click="toggleLyrics"
          >
            {{ barText }}
          </button>
        </div>
      </div>
      <span v-else class="tabular shrink-0 text-xs text-[color:var(--gz-muted)]">
        {{ formatClock(player.currentTime) }} / {{ formatClock(player.duration) }}
      </span>
      <div class="gz-player-controls flex items-center justify-end gap-1">
        <div class="flex items-center">
          <button
            type="button"
            class="gz-ghost gz-player-skip"
            aria-label="上一首"
            :disabled="!player.hasPrev"
            @click="player.prev()"
          >
            <AppIcon name="chevron-left" :size="20" />
          </button>
          <button type="button" class="gz-play" :aria-label="toggleLabel" @click="player.toggle()">
            <AppIcon :name="player.loading ? 'spinner' : player.playing ? 'pause' : 'play'" :size="18" />
          </button>
          <button
            type="button"
            class="gz-ghost gz-player-skip"
            aria-label="下一首"
            :disabled="!player.hasNext"
            @click="player.next()"
          >
            <AppIcon name="chevron-right" :size="20" />
          </button>
          <button
            type="button"
            class="gz-ghost gz-player-skip"
            :class="player.repeatMode !== 'off' ? 'is-on' : ''"
            :aria-label="repeatLabel"
            :aria-pressed="player.repeatMode !== 'off'"
            :title="repeatLabel"
            @click="player.cycleRepeat()"
          >
            <AppIcon :name="repeatIcon" :size="18" />
          </button>
        </div>
      </div>
      <div v-if="!lyricsOpen" class="gz-player-extra">
        <span class="tabular text-xs text-[color:var(--gz-muted)]">
          {{ formatClock(player.currentTime) }} / {{ formatClock(player.duration) }}
        </span>
        <button
          v-if="player.current?.official_url"
          type="button"
          class="gz-ghost"
          aria-label="打开官方页面"
          @click="player.openOfficial(player.current)"
        >
          <AppIcon name="external" :size="17" />
        </button>
      </div>
    </div>
  </footer>
  <footer
    v-else
    ref="root"
    class="fixed inset-x-0 bottom-0 z-30 border-t border-zinc-200 pb-[env(safe-area-inset-bottom,0px)] backdrop-blur-md dark:border-white/10"
    :class="lyricsOpen ? 'is-lyrics bg-white/80 dark:bg-zinc-950/80' : 'bg-white/95 dark:bg-zinc-950/95'"
    aria-label="播放器"
  >
    <div v-if="coverBackdrop" class="player-cover-bg" aria-hidden="true">
      <img :src="coverBackdrop" alt="" />
    </div>
    <LyricsPanel v-if="lyricsOpen" @close="lyricsOpen = false" />
    <div
      role="slider"
      tabindex="0"
      class="relative flex h-4 w-full cursor-pointer touch-none items-center focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-zinc-400 dark:focus-visible:outline-zinc-600"
      :class="!player.duration ? 'cursor-default' : ''"
      aria-label="播放进度"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-valuenow="Math.round(player.progress * 100)"
      :aria-disabled="!player.duration"
      @pointerdown="onSeekPointer"
      @pointermove="onSeekPointer"
      @pointerup="onSeekEnd"
      @pointercancel="onSeekEnd"
      @keydown="onSeekKey"
    >
      <span class="absolute inset-x-0 h-1.5 bg-zinc-200 dark:bg-zinc-800" />
      <span class="absolute left-0 h-1.5 bg-accent" :style="{ width: `${percent}%` }" />
    </div>

    <div class="mx-auto w-full max-w-7xl px-3 pb-2 sm:px-4">
      <div
        class="grid min-h-[60px] grid-cols-[minmax(0,1fr)_auto] items-center gap-2 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] sm:gap-3"
      >
        <div v-if="!lyricsOpen" class="flex min-w-0 items-center gap-3">
          <CoverImage
            :src="player.current?.cover_url"
            :size="150"
            :alt="player.current?.title ?? ''"
            class="h-11 w-11 shrink-0 rounded-lg object-cover"
          />
          <div class="min-w-0">
            <div class="type-title truncate">{{ player.current?.title }}</div>
            <button
              type="button"
              class="block w-full truncate bg-transparent p-0 text-left text-[0.74rem]"
              :class="player.failed ? 'text-rose-600 dark:text-rose-300' : 'text-artist'"
              aria-label="歌词"
              :aria-pressed="lyricsOpen"
              @click="toggleLyrics"
            >
              {{ barText }}
            </button>
          </div>
        </div>
        <span v-else class="tabular text-xs text-secondary">
          {{ formatClock(player.currentTime) }} / {{ formatClock(player.duration) }}
        </span>

        <div class="flex items-center justify-end gap-1 sm:gap-2">
          <div class="flex items-center">
            <button
              type="button"
              class="grid h-11 w-11 place-items-center rounded-full text-zinc-600 hover:bg-zinc-100 disabled:cursor-default disabled:opacity-30 dark:text-zinc-300 dark:hover:bg-white/10"
              aria-label="上一首"
              :disabled="!player.hasPrev"
              @click="player.prev()"
            >
              <AppIcon name="chevron-left" :size="20" />
            </button>
            <button
              type="button"
              class="grid h-11 w-11 place-items-center rounded-full bg-zinc-900 text-white dark:bg-white dark:text-zinc-900"
              :aria-label="toggleLabel"
              @click="player.toggle()"
            >
              <AppIcon :name="player.loading ? 'spinner' : player.playing ? 'pause' : 'play'" :size="18" />
            </button>
            <button
              type="button"
              class="grid h-11 w-11 place-items-center rounded-full text-zinc-600 hover:bg-zinc-100 disabled:cursor-default disabled:opacity-30 dark:text-zinc-300 dark:hover:bg-white/10"
              aria-label="下一首"
              :disabled="!player.hasNext"
              @click="player.next()"
            >
              <AppIcon name="chevron-right" :size="20" />
            </button>
            <button
              type="button"
              class="grid h-11 w-11 place-items-center rounded-full text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-white/10"
              :class="player.repeatMode !== 'off' ? 'text-zinc-900 ring-1 ring-zinc-300 dark:text-white dark:ring-white/20' : ''"
              :aria-label="repeatLabel"
              :aria-pressed="player.repeatMode !== 'off'"
              :title="repeatLabel"
              @click="player.cycleRepeat()"
            >
              <AppIcon :name="repeatIcon" :size="18" />
            </button>
          </div>
        </div>

        <div class="hidden min-w-0 items-center justify-end gap-3 sm:flex">
          <span v-if="!lyricsOpen" class="tabular text-xs text-secondary">
            {{ formatClock(player.currentTime) }} / {{ formatClock(player.duration) }}
          </span>
          <button
            v-if="player.current?.official_url"
            type="button"
            class="grid h-11 w-11 place-items-center rounded-full ring-1 ring-zinc-300 hover:bg-zinc-100 dark:ring-white/15 dark:hover:bg-white/10"
            aria-label="打开官方页面"
            @click="player.openOfficial(player.current)"
          >
            <AppIcon name="external" :size="17" />
          </button>
        </div>
      </div>
    </div>
  </footer>
</template>

<style scoped>
.is-lyrics {
  overflow: hidden;
  color: #fff;
}

.is-lyrics .gz-ghost,
.is-lyrics .text-secondary,
.is-lyrics .text-zinc-600,
.is-lyrics .text-zinc-500,
.is-lyrics .text-artist {
  color: rgb(255 255 255 / 0.9);
}

.is-lyrics > :not(.player-cover-bg) {
  position: relative;
  z-index: 1;
}

.player-cover-bg {
  position: absolute;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
}

.player-cover-bg img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center;
  opacity: 0.32;
  transition: opacity 480ms ease;
}

.player-cover-bg::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(
    to bottom,
    rgb(0 0 0 / 0.28) 0%,
    rgb(0 0 0 / 0.42) 46%,
    rgb(0 0 0 / 0.62) 100%
  );
}
</style>
