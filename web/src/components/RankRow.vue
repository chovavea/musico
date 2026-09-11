<script setup lang="ts">
import { computed } from "vue";
import type { RankItem } from "../types";
import { useTrackDownload } from "../composables/useTrackDownload";
import { rowGridClass } from "../lib/list-grid";
import { usePlayerStore } from "../stores/player";

const props = defineProps<{ item: RankItem; queue?: RankItem[] }>();
const player = usePlayerStore();
const download = useTrackDownload();

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

const actionState = computed(() => download.state(props.item));

const downloadState = computed(() => {
  if (actionState.value === "ready") return "已下载";
  if (actionState.value === "queued") return "队列中";
  return "下载";
});

const downloadPillClass = computed(() => {
  if (actionState.value === "ready") {
    return "bg-emerald-600/15 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300";
  }
  if (actionState.value === "queued") {
    return "bg-zinc-900/70 text-white/80 dark:bg-white/15 dark:text-zinc-300";
  }
  return "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900";
});

function onDownload() {
  void download.enqueue(props.item);
}
</script>

<template>
  <div
    class="group relative grid min-h-[52px] w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-zinc-50 dark:hover:bg-white/5"
    :class="[rowGridClass, active ? 'bg-zinc-50 dark:bg-white/5' : '']"
  >
    <button
      type="button"
      class="absolute inset-0 z-0 rounded-2xl focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-zinc-400 dark:focus-visible:outline-zinc-600"
      :aria-label="`播放 ${item.title} · ${item.artist}`"
      @click="onPlay"
    />
    <div class="pointer-events-none tabular text-right font-semibold" :class="rankKlass">
      {{ String(item.rank).padStart(2, "0") }}
    </div>
    <div class="pointer-events-none relative h-11 w-11 overflow-hidden rounded-lg">
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
    <div class="pointer-events-none min-w-0">
      <div class="truncate font-medium" :class="active ? 'text-emerald-600 dark:text-emerald-300' : ''">
        {{ item.title }}
      </div>
      <div class="truncate text-sm text-zinc-500 dark:text-zinc-400">{{ item.artist }}</div>
    </div>
    <div class="flex items-center justify-self-end gap-2 text-sm">
      <span class="pointer-events-none tabular hidden w-8 shrink-0 text-right text-zinc-400 sm:inline">{{ Math.round(item.normalized_score) }}</span>
      <span class="pointer-events-none rounded-full px-2 py-0.5 text-xs" :class="delta.klass">{{ delta.text }}</span>
      <span class="relative z-10 pointer-events-auto">
        <button
          type="button"
          class="grid h-11 w-11 place-items-center rounded-full"
          :class="downloadPillClass"
          :aria-label="downloadState"
          :title="downloadState"
          :disabled="actionState !== 'idle'"
          @click="onDownload"
        >
          <svg v-if="actionState !== 'ready'" viewBox="0 0 16 16" class="h-4 w-4" fill="none" aria-hidden="true">
            <path d="M8 2.5v7m0 0 2.5-2.5M8 9.5 5.5 7M3 11.5v1A1.5 1.5 0 0 0 4.5 14h7a1.5 1.5 0 0 0 1.5-1.5v-1" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <span v-else aria-hidden="true">✓</span>
        </button>
      </span>
    </div>
  </div>
</template>
