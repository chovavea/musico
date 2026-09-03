<script setup lang="ts">
import { computed, ref } from "vue";
import { formatClock } from "../lib/format";
import { usePlayerStore } from "../stores/player";

const player = usePlayerStore();
const percent = computed(() => Math.round(player.progress * 1000) / 10);
const dragging = ref(false);

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
</script>

<template>
  <footer
    class="fixed inset-x-0 bottom-0 z-20 border-t border-zinc-200 bg-white/80 pb-[env(safe-area-inset-bottom,0px)] backdrop-blur-xl dark:border-white/10 dark:bg-zinc-950/70"
  >
    <button
      type="button"
      class="relative flex h-8 w-full touch-none items-center"
      :disabled="!player.current || !player.duration"
      @pointerdown="onSeekPointer"
      @pointermove="onSeekPointer"
      @pointerup="onSeekEnd"
      @pointercancel="onSeekEnd"
    >
      <span class="absolute inset-x-0 h-1 bg-zinc-200 dark:bg-zinc-800" />
      <span
        class="absolute left-0 h-1 bg-zinc-900 dark:bg-white"
        :style="{ width: `${percent}%` }"
      />
    </button>
    <div
      class="mx-auto flex max-w-7xl flex-col gap-1 px-4 pb-2 pt-1 md:flex-row md:items-center md:gap-4 md:py-3"
    >
      <div class="flex min-w-0 flex-1 items-center gap-3">
        <div class="h-12 w-12 shrink-0 overflow-hidden rounded-lg bg-zinc-200 dark:bg-zinc-800">
          <img
            v-if="player.current?.cover_url"
            :src="player.current.cover_url"
            class="h-full w-full object-cover"
            alt=""
          />
        </div>
        <div class="min-w-0 flex-1">
          <div class="truncate font-medium">{{ player.current?.title ?? "未选择曲目" }}</div>
          <div class="truncate text-sm text-zinc-500 dark:text-zinc-400">
            {{
              player.current
                ? player.failed
                  ? "这条没有官方试听，可去 App 听完整版"
                  : player.usingOfficial
                    ? "QQ 官方播放器试听"
                    : player.current.artist
                : "点试听或播放本榜，有官方预览的会在这里连播"
            }}
          </div>
        </div>
        <div
          v-if="player.current && player.duration"
          class="hidden tabular text-xs text-zinc-400 md:block"
        >
          {{ formatClock(player.currentTime) }} / {{ formatClock(player.duration) }}
        </div>
        <button
          v-if="player.current"
          type="button"
          class="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-zinc-900 text-white md:hidden dark:bg-white dark:text-zinc-900"
          @click="player.toggle()"
        >
          {{ player.playing ? "❚❚" : "▶" }}
        </button>
      </div>
      <div v-if="player.current" class="flex items-center gap-2">
        <button
          v-if="player.hasQueue"
          type="button"
          class="grid h-11 flex-1 place-items-center rounded-full text-sm text-zinc-500 md:flex-none md:px-3"
          @click="player.prev()"
        >
          上一首
        </button>
        <button
          type="button"
          class="hidden h-11 w-11 shrink-0 place-items-center rounded-full bg-zinc-900 text-white md:grid dark:bg-white dark:text-zinc-900"
          @click="player.toggle()"
        >
          {{ player.playing ? "❚❚" : "▶" }}
        </button>
        <button
          type="button"
          class="grid h-11 flex-[1.3] place-items-center rounded-full bg-zinc-100 px-4 text-sm dark:bg-zinc-800 md:flex-none"
          @click="player.openOfficial(player.current)"
        >
          去 App 听
        </button>
        <button
          v-if="player.hasQueue"
          type="button"
          class="grid h-11 flex-1 place-items-center rounded-full text-sm text-zinc-500 md:flex-none md:px-3"
          @click="player.next()"
        >
          下一首
        </button>
      </div>
    </div>
  </footer>
</template>
