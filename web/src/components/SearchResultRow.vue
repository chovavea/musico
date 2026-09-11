<script setup lang="ts">
import { computed } from "vue";
import { platformLabel } from "../lib/boards";
import { formatClock } from "../lib/format";
import { resultToRankItem } from "../lib/search";
import { usePlayerStore } from "../stores/player";
import type { SearchResult } from "../types";
import AppIcon from "./AppIcon.vue";
import CoverImage from "./CoverImage.vue";
import TrackDownloadAction from "./TrackDownloadAction.vue";

const props = defineProps<{ result: SearchResult }>();
const player = usePlayerStore();
const item = computed(() => resultToRankItem(props.result));
const active = computed(
  () =>
    player.current?.platform === item.value.platform &&
    player.current?.external_id === item.value.external_id,
);
const durationLabel = computed(() =>
  props.result.duration_ms ? formatClock(props.result.duration_ms / 1000) : "",
);

function play() {
  player.play(item.value);
}
</script>

<template>
  <div
    class="group flex min-h-16 items-center gap-3 px-3 py-2.5 text-left transition hover:bg-zinc-50 dark:hover:bg-white/5"
    :class="active ? 'bg-zinc-50 dark:bg-white/5' : ''"
  >
    <button
      type="button"
      class="flex min-w-0 flex-1 items-center gap-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-zinc-400 dark:focus-visible:outline-zinc-600"
      :aria-label="`播放 ${result.title} · ${result.artist}`"
      @click="play"
    >
      <div class="relative h-11 w-11 shrink-0 overflow-hidden rounded-lg bg-zinc-200 dark:bg-zinc-800">
        <CoverImage
          :src="result.cover_url"
          :size="150"
          :alt="result.title"
          class="h-full w-full object-cover transition duration-200 group-hover:scale-105"
        />
        <span class="absolute inset-0 grid place-items-center bg-zinc-950/35 text-white opacity-0 transition group-hover:opacity-100 group-focus-within:opacity-100">
          <AppIcon name="play" :size="16" />
        </span>
      </div>
      <div class="min-w-0 flex-1">
        <div class="truncate font-medium" :class="active ? 'text-emerald-600 dark:text-emerald-300' : ''">
          {{ result.title }}
        </div>
        <div class="truncate text-sm text-zinc-500 dark:text-zinc-400">
          {{ result.artist }}<span v-if="result.album"> · {{ result.album }}</span>
        </div>
        <div class="mt-0.5 flex items-center gap-1.5 truncate text-xs text-secondary">
          <span
            v-for="source in result.platforms"
            :key="`${source.platform}:${source.external_id}`"
            class="shrink-0 rounded-full bg-zinc-100 px-1.5 py-0.5 dark:bg-zinc-800"
          >
            {{ platformLabel(source.platform) }}
          </span>
          <span v-if="durationLabel" class="shrink-0">{{ durationLabel }}</span>
          <span v-if="result.version" class="min-w-0 truncate">{{ result.version }}</span>
          <span v-if="result.library_status === 'ready'" class="text-emerald-700 dark:text-emerald-300">
            本地已有
          </span>
        </div>
      </div>
    </button>
    <TrackDownloadAction :item="item" :show-label="true" />
  </div>
</template>
