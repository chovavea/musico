<script setup lang="ts">
import { computed, ref } from "vue";
import { formatClock } from "../lib/format";
import { usePlayerStore } from "../stores/player";
import AppIcon from "./AppIcon.vue";
import CoverImage from "./CoverImage.vue";

const player = usePlayerStore();
const percent = computed(() => Math.round(player.progress * 1000) / 10);
const dragging = ref(false);
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
    class="fixed inset-x-0 bottom-0 z-30 pb-[env(safe-area-inset-bottom,0px)]"
    aria-label="播放器"
  >
    <div class="mx-auto max-w-4xl px-3 pb-3">
      <div class="overflow-hidden rounded-2xl border border-zinc-200 bg-white/95 dark:border-white/10 dark:bg-zinc-950/95">
        <div
          role="slider"
          tabindex="0"
          class="relative flex h-2 w-full cursor-pointer touch-none items-center focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2"
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
          <span class="absolute inset-x-0 h-2 bg-zinc-200 dark:bg-zinc-800" />
          <span class="absolute left-0 h-2 bg-zinc-900 dark:bg-white" :style="{ width: `${percent}%` }" />
        </div>

        <div class="grid min-h-[68px] grid-cols-[minmax(0,1fr)_auto] items-center gap-2 px-3 py-2 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] sm:gap-3 sm:px-4">
          <div class="flex min-w-0 items-center gap-3">
            <CoverImage
              :src="player.current?.cover_url"
              :size="150"
              :alt="player.current?.title ?? ''"
              class="hidden h-11 w-11 shrink-0 rounded-xl object-cover sm:block"
            />
            <div class="min-w-0">
              <div class="truncate text-sm font-medium">{{ player.current?.title }}</div>
              <div class="truncate text-xs" :class="player.failed ? 'text-rose-600 dark:text-rose-300' : 'text-secondary'">
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
    </div>
  </footer>
</template>
