<script setup lang="ts">
import { computed } from "vue";
import type { RankItem } from "../types";
import { usePlayerStore } from "../stores/player";

const props = defineProps<{ item: RankItem; queue?: RankItem[] }>();
const player = usePlayerStore();

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
</script>

<template>
  <button
    type="button"
    class="group grid min-h-[52px] w-full grid-cols-[2.25rem_2.75rem_minmax(0,1fr)_auto] items-center gap-3 px-3 py-2.5 text-left hover:bg-zinc-50 dark:hover:bg-white/5"
    :class="active ? 'bg-zinc-50 dark:bg-white/5' : ''"
    @click="onPlay"
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
      <span class="tabular hidden text-zinc-400 sm:inline">{{ Math.round(item.normalized_score) }}</span>
      <span class="rounded-full px-2 py-0.5 text-xs" :class="delta.klass">{{ delta.text }}</span>
      <span
        class="grid h-11 min-w-11 place-items-center rounded-full bg-zinc-900 px-3 text-xs text-white dark:bg-white dark:text-zinc-900"
      >
        试听
      </span>
    </div>
  </button>
</template>
