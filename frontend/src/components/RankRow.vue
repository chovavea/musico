<script setup lang="ts">
import { computed } from "vue";
import type { RankItem } from "../types";
import { rowGridClass } from "../lib/list-grid";
import { usePlayerStore } from "../stores/player";
import { useDownloadsStore } from "../stores/downloads";

const props = defineProps<{ item: RankItem; queue?: RankItem[] }>();
const player = usePlayerStore();
const downloads = useDownloadsStore();

const delta = computed(() => {
  if (props.item.previous_rank == null) {
    return { text: "新", klass: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300" };
  }
  const diff = props.item.previous_rank - props.item.rank;
  if (diff > 0) {
    return {
      text: `↑${diff}`,
      klass: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
    };
  }
  if (diff < 0) {
    return {
      text: `↓${Math.abs(diff)}`,
      klass: "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
    };
  }
  return { text: "平", klass: "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400" };
});

const rankKlass = computed(() => {
  if (props.item.rank === 1) return "text-xl text-amber-500";
  if (props.item.rank === 2) return "text-lg text-zinc-400";
  if (props.item.rank === 3) return "text-lg text-amber-700 dark:text-amber-600";
  return "text-zinc-500 dark:text-zinc-400";
});

const active = computed(
  () =>
    player.current?.platform === props.item.platform &&
    player.current?.external_id === props.item.external_id,
);

function onPlay() {
  player.play(props.item, props.queue);
}

const downloadState = computed(() => {
  if (props.item.library_status === "ready") return "已下载";
  if (props.item.active_download_id) return "队列中";
  return "下载";
});

async function onDownload(event: MouseEvent) {
  event.stopPropagation();
  if (props.item.library_status === "ready" || props.item.active_download_id) return;
  await downloads.enqueue({
    platform: props.item.platform,
    external_id: props.item.external_id,
    title: props.item.title,
    artist: props.item.artist,
    album: props.item.album,
    duration_ms: props.item.duration_ms,
    isrc: props.item.isrc,
    version: props.item.version,
  });
}

function onRowKey(event: KeyboardEvent) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    onPlay();
  }
}
</script>

<template>
  <div
    role="button"
    tabindex="0"
    class="group min-h-[52px] w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-zinc-50 dark:hover:bg-white/5"
    :class="[rowGridClass, active ? 'bg-zinc-50 dark:bg-white/5' : '']"
    @click="onPlay"
    @keydown="onRowKey"
  >
    <div class="tabular text-right font-semibold" :class="rankKlass">
      {{ String(item.rank).padStart(2, "0") }}
    </div>
    <div class="relative h-11 w-11 overflow-hidden rounded-lg">
      <img
        v-if="item.cover_url"
        :src="item.cover_url"
        :alt="item.title"
        class="h-full w-full object-cover transition duration-200 group-hover:-translate-y-0.5"
      />
      <div v-else class="h-full w-full bg-zinc-200 dark:bg-zinc-800" />
      <span
        class="absolute inset-0 hidden place-items-center bg-zinc-950/45 text-xs text-white md:grid md:opacity-0 md:group-hover:opacity-100"
      >
        ▶
      </span>
    </div>
    <div class="min-w-0">
      <div class="truncate font-medium" :class="active ? 'text-emerald-600 dark:text-emerald-300' : ''">
        {{ item.title }}
      </div>
      <div class="truncate text-sm text-zinc-500 dark:text-zinc-400">{{ item.artist }}</div>
    </div>
    <div class="flex items-center gap-2 text-sm">
      <span class="tabular hidden w-8 shrink-0 text-right text-zinc-400 sm:inline">{{ Math.round(item.normalized_score) }}</span>
      <span class="rounded-full px-2 py-0.5 text-xs" :class="delta.klass">{{ delta.text }}</span>
      <span
        class="grid h-11 min-w-11 place-items-center rounded-full bg-zinc-900 px-3 text-xs text-white dark:bg-white dark:text-zinc-900"
      >
        试听
      </span>
      <button
        type="button"
        class="grid h-11 min-w-11 place-items-center rounded-full px-3 text-xs ring-1 ring-zinc-300 hover:bg-zinc-100 dark:ring-white/15 dark:hover:bg-white/10"
        :class="item.library_status === 'ready' ? 'text-emerald-600 dark:text-emerald-300' : 'text-zinc-600 dark:text-zinc-300'"
        :aria-label="downloadState"
        :title="downloadState"
        @click="onDownload"
      >
        <svg v-if="item.library_status !== 'ready'" viewBox="0 0 16 16" class="h-4 w-4" fill="none" aria-hidden="true">
          <path d="M8 2.5v7m0 0 2.5-2.5M8 9.5 5.5 7M3 11.5v1A1.5 1.5 0 0 0 4.5 14h7a1.5 1.5 0 0 0 1.5-1.5v-1" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        <span v-else aria-hidden="true">✓</span>
      </button>
    </div>
  </div>
</template>
