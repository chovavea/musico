<script setup lang="ts">
import { computed } from "vue";
import { RouterLink } from "vue-router";
import { chartShortName, platformLabel } from "../lib/boards";
import { formatUpdatedAt, risingCount } from "../lib/format";
import { usePlayerStore } from "../stores/player";
import type { BoardInfo, LatestBoard } from "../types";
import HeroCard from "./HeroCard.vue";
import RankRow from "./RankRow.vue";
import BoardChartPicker from "./BoardChartPicker.vue";
import type { CatalogGroup } from "../types";

const props = withDefaults(
  defineProps<{
    board: BoardInfo;
    latest?: LatestBoard;
    showHero?: boolean;
    linkToChart?: boolean;
    limit?: number;
    pickerGroups?: CatalogGroup[];
  }>(),
  { showHero: true, linkToChart: true },
);

const emit = defineEmits<{
  pick: [key: string];
  reorder: [key: string, beforeKey: string | null];
}>();

const allItems = computed(() => props.latest?.items ?? []);
const items = computed(() =>
  props.limit ? allItems.value.slice(0, props.limit) : allItems.value,
);
const player = usePlayerStore();
const staleLabel = computed(() => {
  const value = props.latest?.staleness;
  if (value === "stale") return "数据可能过期";
  if (value === "missing") return "尚无快照";
  return "";
});
</script>

<template>
  <section class="min-w-0">
    <HeroCard v-if="showHero" :board="board" :latest="latest" class="mb-4" />
    <div class="mb-3 flex items-end justify-between gap-3">
      <div class="min-w-0">
        <p class="text-xs font-medium text-zinc-500">{{ platformLabel(board.platform) }}</p>
        <BoardChartPicker
          v-if="pickerGroups?.length && board.chart_key"
          :name="chartShortName(board.name)"
          :chart-key="board.chart_key"
          :groups="pickerGroups"
          @select="emit('pick', $event)"
          @reorder="(key, beforeKey) => emit('reorder', key, beforeKey)"
        />
        <RouterLink
          v-else
          :to="`/charts/${board.id}`"
          class="inline-flex min-h-11 items-center text-lg font-semibold hover:underline"
        >
          {{ chartShortName(board.name) }}
        </RouterLink>
        <p class="text-xs text-zinc-500">
          {{ allItems.length }} 首 · 升 {{ risingCount(allItems) }}
          · {{ formatUpdatedAt(latest?.fetched_at ?? latest?.updated_at) }}
        </p>
        <p v-if="staleLabel" class="text-xs text-amber-600 dark:text-amber-400">{{ staleLabel }}</p>
      </div>
      <div class="flex shrink-0 items-center gap-1">
        <button
          v-if="allItems.length"
          type="button"
          class="grid h-11 place-items-center rounded-full px-3 text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-white"
          @click="allItems[0] && player.play(allItems[0], allItems)"
        >
          播放本榜
        </button>
        <RouterLink
          v-if="linkToChart"
          :to="`/charts/${board.id}`"
          class="grid h-11 place-items-center rounded-full px-3 text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-white"
        >
          全部
        </RouterLink>
      </div>
    </div>
    <div
      class="overflow-hidden rounded-2xl bg-white ring-1 ring-zinc-200/80 dark:bg-zinc-900 dark:ring-white/10"
    >
      <div
        class="grid grid-cols-[2.25rem_2.75rem_minmax(0,1fr)_auto] gap-3 border-b border-zinc-100 px-3 py-2 text-xs text-zinc-400 dark:border-white/5"
      >
        <span class="text-right">#</span>
        <span />
        <span>曲目</span>
        <span class="text-right">升降</span>
      </div>
      <div class="divide-y divide-zinc-100 dark:divide-white/5">
        <RankRow
          v-for="item in items"
          :key="item.external_id"
          :item="item"
          :queue="allItems"
        />
      </div>
      <div v-if="!items.length" class="space-y-3 px-3 py-4">
        <div v-for="n in 8" :key="n" class="flex items-center gap-3">
          <div class="skel h-4 w-6" />
          <div class="skel h-11 w-11 rounded-lg" />
          <div class="flex-1 space-y-2">
            <div class="skel h-3 w-2/3" />
            <div class="skel h-3 w-1/3" />
          </div>
        </div>
        <p class="text-center text-sm text-zinc-500">暂无条目，采集完成后会填满这张表</p>
      </div>
    </div>
  </section>
</template>
