<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { comingSoon } from "../lib/coming-soon";
import { formatClock } from "../lib/format";
import { usePlayerStore } from "../stores/player";
import { useThemeStore } from "../stores/theme";
import AppIcon from "./AppIcon.vue";
import CoverImage from "./CoverImage.vue";

const player = usePlayerStore();
const theme = useThemeStore();
const percent = computed(() => Math.round(player.progress * 1000) / 10);
const dragging = ref(false);
const root = ref<HTMLElement | null>(null);
let heightObserver: ResizeObserver | null = null;

const statusText = computed(() => {
  if (player.failed) return "暂无可用试听源";
  if (player.loading) return player.downloadOnly ? "正在查找可用音源" : "正在加载试听";
  if (player.loadCancelled) return "已取消加载";
  if (player.usingOfficial) return "QQ 官方试听";
  return player.current?.artist ?? "";
});
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
    aria-label="播放器"
  >
    <div
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
    <div class="gz-player-body">
      <div class="flex min-w-0 items-center gap-3">
        <CoverImage
          :src="player.current?.cover_url"
          :size="150"
          :alt="player.current?.title ?? ''"
          class="h-11 w-11 shrink-0 rounded-xl object-cover"
        />
        <div class="min-w-0">
          <div class="gz-title">{{ player.current?.title }}</div>
          <div class="gz-artist" :class="player.failed ? 'text-rose-400' : ''">
            {{ statusText }}
          </div>
        </div>
      </div>
      <div class="flex items-center gap-1">
        <button
          type="button"
          class="gz-ghost gz-player-skip"
          aria-label="上一首"
          :disabled="!player.hasPrev"
          @click="player.prev()"
        >
          <AppIcon name="chevron-left" :size="20" />
        </button>
        <button type="button" class="gz-ghost" :aria-label="toggleLabel" @click="player.toggle()">
          <AppIcon :name="player.loading ? 'spinner' : player.playing ? 'pause' : 'play'" :size="20" />
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
          class="gz-ghost gz-player-queue-mobile"
          aria-label="播放列表"
          @click="comingSoon('播放列表')"
        >
          <AppIcon name="queue" :size="18" />
        </button>
      </div>
      <div class="gz-player-extra">
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
        <button type="button" class="gz-ghost" aria-label="播放列表" @click="comingSoon('播放列表')">
          <AppIcon name="queue" :size="18" />
        </button>
      </div>
    </div>
  </footer>
  <footer
    v-else
    ref="root"
    class="fixed inset-x-0 bottom-0 z-30 border-t border-zinc-200 bg-white/95 pb-[env(safe-area-inset-bottom,0px)] backdrop-blur-md dark:border-white/10 dark:bg-zinc-950/95"
    aria-label="播放器"
  >
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
        <div class="flex min-w-0 items-center gap-3">
          <CoverImage
            :src="player.current?.cover_url"
            :size="150"
            :alt="player.current?.title ?? ''"
            class="h-11 w-11 shrink-0 rounded-lg object-cover"
          />
          <div class="min-w-0">
            <div class="type-title truncate">{{ player.current?.title }}</div>
            <div class="truncate text-[0.74rem]" :class="player.failed ? 'text-rose-600 dark:text-rose-300' : 'text-artist'">
              {{ statusText }}
            </div>
          </div>
        </div>

        <div class="flex items-center gap-1 sm:gap-2">
          <button
            type="button"
            class="grid h-11 w-11 place-items-center rounded-full hover:bg-zinc-100 disabled:cursor-default disabled:opacity-30 dark:hover:bg-white/10"
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
            <AppIcon :name="player.loading ? 'spinner' : player.playing ? 'pause' : 'play'" :size="19" />
          </button>
          <button
            type="button"
            class="grid h-11 w-11 place-items-center rounded-full hover:bg-zinc-100 disabled:cursor-default disabled:opacity-30 dark:hover:bg-white/10"
            aria-label="下一首"
            :disabled="!player.hasNext"
            @click="player.next()"
          >
            <AppIcon name="chevron-right" :size="20" />
          </button>
        </div>

        <div class="hidden min-w-0 items-center justify-end gap-3 sm:flex">
          <span class="tabular text-xs text-secondary">
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
