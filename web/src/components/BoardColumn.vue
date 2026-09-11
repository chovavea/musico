<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import { chartShortName, platformLabel } from "../lib/boards";
import { useChartsStore } from "../stores/charts";
import { usePlayerStore } from "../stores/player";
import type { BoardInfo, LatestBoard } from "../types";
import HeroCard from "./HeroCard.vue";
import RankRow from "./RankRow.vue";
import BoardChartPicker from "./BoardChartPicker.vue";
import type { CatalogGroup } from "../types";
import AppIcon from "./AppIcon.vue";

const props = withDefaults(
  defineProps<{
    board: BoardInfo;
    latest?: LatestBoard;
    showHero?: boolean;
    pickerGroups?: CatalogGroup[];
  }>(),
  { showHero: true },
);
const charts = useChartsStore();

const emit = defineEmits<{
  pick: [key: string];
  reorder: [key: string, beforeKey: string | null];
}>();

const PAGE_SIZE = 10;
const allItems = computed(() => props.latest?.items ?? []);
const visibleCount = ref(PAGE_SIZE);
const items = computed(() => allItems.value.slice(0, visibleCount.value));
const hasMore = computed(() => visibleCount.value < allItems.value.length);

const sentinel = ref<HTMLElement | null>(null);
let observer: IntersectionObserver | null = null;

function loadMore() {
  if (!hasMore.value) return;
  visibleCount.value = Math.min(allItems.value.length, visibleCount.value + PAGE_SIZE);
}

function connectObserver() {
  observer?.disconnect();
  observer = null;
  const el = sentinel.value;
  if (!el) return;
  observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) loadMore();
    }
  }, { rootMargin: "200px 0px" });
  observer.observe(el);
}

watch([hasMore, sentinel], () => connectObserver(), { flush: "post" });
watch(
  () => props.board.id,
  () => {
    visibleCount.value = PAGE_SIZE;
  },
);
onMounted(() => connectObserver());
onBeforeUnmount(() => observer?.disconnect());
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
        <p class="text-xs font-medium text-secondary">{{ platformLabel(board.platform) }}</p>
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
        <p v-if="staleLabel" class="text-xs text-amber-600 dark:text-amber-400">{{ staleLabel }}</p>
      </div>
      <div class="flex shrink-0 items-center">
        <button
          v-if="allItems.length"
          type="button"
          class="inline-flex h-11 shrink-0 items-center gap-1.5 rounded-full px-4 text-sm font-medium text-zinc-600 ring-1 ring-zinc-300 transition hover:bg-zinc-100 hover:text-zinc-900 active:scale-95 dark:text-zinc-300 dark:ring-white/15 dark:hover:bg-white/10 dark:hover:text-white"
          :aria-label="`播放本榜：${board.name}`"
          :title="`播放本榜：${board.name}`"
          @click="allItems[0] && player.play(allItems[0], allItems)"
        >
          <AppIcon name="play" :size="16" />
          播放本榜
        </button>
      </div>
    </div>
    <div
      class="overflow-hidden rounded-2xl bg-white ring-1 ring-zinc-200/80 dark:bg-zinc-900 dark:ring-white/10"
    >
      <div
        class="hidden gap-3 border-b border-zinc-100 px-3 py-2 text-xs text-secondary sm:grid sm:grid-cols-[2.25rem_2.75rem_minmax(0,1fr)_9rem] dark:border-white/5"
      >
        <span class="text-right">排名</span>
        <span />
        <span>曲目</span>
        <span class="flex items-center gap-2"><span class="hidden w-8 shrink-0 sm:inline-block" aria-hidden="true" /><span>升降</span></span>
      </div>
      <div class="divide-y divide-zinc-100 dark:divide-white/5">
        <RankRow
          v-for="item in items"
          :key="item.external_id"
          :item="item"
          :queue="allItems"
        />
      </div>
      <div v-if="hasMore" ref="sentinel" class="h-4" aria-hidden="true" />
      <div
        v-if="!items.length && charts.latestErrors[board.id]"
        role="alert"
        class="px-4 py-8 text-center text-sm text-rose-700 dark:text-rose-300"
      >
        <p>{{ charts.latestErrors[board.id] }}</p>
        <button type="button" class="mt-3 h-11 rounded-full px-4 font-medium underline" @click="charts.ensureLatest(board)">
          重新加载
        </button>
      </div>
      <div v-else-if="!items.length" class="space-y-3 px-3 py-4">
        <div v-for="n in 8" :key="n" class="flex items-center gap-3">
          <div class="skel h-4 w-6" />
          <div class="skel h-11 w-11 rounded-lg" />
          <div class="flex-1 space-y-2">
            <div class="skel h-3 w-2/3" />
            <div class="skel h-3 w-1/3" />
          </div>
        </div>
        <p v-if="!charts.latestLoading[board.id]" class="text-center text-sm text-secondary">暂无条目，采集完成后会填满这张表</p>
      </div>
    </div>
  </section>
</template>
