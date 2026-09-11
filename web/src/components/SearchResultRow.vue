<script setup lang="ts">
import { computed } from "vue";
import { platformLabel } from "../lib/boards";
import { resultToRankItem } from "../lib/search";
import { useTrackDownload } from "../composables/useTrackDownload";
import { usePlayerStore } from "../stores/player";
import type { SearchResult } from "../types";

const props = defineProps<{ result: SearchResult }>();
const player = usePlayerStore();
const download = useTrackDownload();

const item = computed(() => resultToRankItem(props.result));
const active = computed(
  () =>
    player.current?.platform === item.value.platform &&
    player.current?.external_id === item.value.external_id,
);

const actionState = computed(() => download.state(item.value));
const downloadLabel = computed(() => {
  if (actionState.value === "ready") return "已下载";
  if (actionState.value === "queued") return "队列中";
  return "下载";
});

const downloadClass = computed(() => {
  if (actionState.value === "ready") {
    return "bg-emerald-600/15 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300";
  }
  if (actionState.value === "queued") {
    return "bg-zinc-900/70 text-white/80 dark:bg-white/15 dark:text-zinc-300";
  }
  return "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900";
});

function play() {
  player.play(item.value);
}

function enqueue() {
  void download.enqueue(item.value);
}
</script>

<template>
  <div
    class="group flex min-h-[76px] items-center gap-3 px-3 py-3 text-left transition hover:bg-zinc-50 dark:hover:bg-white/5"
    :class="active ? 'bg-zinc-50 dark:bg-white/5' : ''"
  >
    <button
      type="button"
      class="flex min-w-0 flex-1 items-center gap-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-zinc-400 dark:focus-visible:outline-zinc-600"
      :aria-label="`播放 ${result.title} · ${result.artist}`"
      @click="play"
    >
      <div class="relative h-12 w-12 shrink-0 overflow-hidden rounded-lg bg-zinc-200 dark:bg-zinc-800">
        <img
          v-if="result.cover_url"
          :src="result.cover_url"
          :alt="result.title"
          class="h-full w-full object-cover transition duration-200 group-hover:scale-105"
        />
        <span class="absolute inset-0 grid place-items-center bg-zinc-950/35 text-xs text-white opacity-0 transition group-hover:opacity-100">
          ▶
        </span>
      </div>
      <div class="min-w-0 flex-1">
        <div class="truncate font-medium" :class="active ? 'text-emerald-600 dark:text-emerald-300' : ''">
          {{ result.title }}
        </div>
        <div class="truncate text-sm text-zinc-500 dark:text-zinc-400">
          {{ result.artist }}<span v-if="result.album"> · {{ result.album }}</span>
        </div>
        <div class="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-zinc-400">
          <span
            v-for="source in result.platforms"
            :key="`${source.platform}:${source.external_id}`"
            class="rounded-full bg-zinc-100 px-2 py-0.5 dark:bg-zinc-800"
          >
            {{ platformLabel(source.platform) }}
          </span>
          <span v-if="result.library_status === 'ready'" class="text-emerald-600 dark:text-emerald-300">
            本地已有
          </span>
        </div>
      </div>
    </button>
    <button
      type="button"
      class="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-zinc-900 text-white dark:bg-white dark:text-zinc-900"
      aria-label="播放"
      title="播放"
      @click="play"
    >
      ▶
    </button>
    <button
      type="button"
      class="h-11 shrink-0 rounded-full px-3 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-80"
      :class="downloadClass"
      :aria-label="downloadLabel"
      :title="downloadLabel"
      :disabled="actionState !== 'idle'"
      @click="enqueue"
    >
      {{ downloadLabel }}
    </button>
  </div>
</template>
