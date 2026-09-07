<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import BoardColumn from "../components/BoardColumn.vue";
import HeroCard from "../components/HeroCard.vue";
import { useStalePoll } from "../composables/useStalePoll";
import { groupsOf, latestOfBoard, resolveCatalogBoard } from "../lib/catalog-board";
import { platformShortName } from "../lib/boards";
import { risingCount, todayLabel } from "../lib/format";
import { useChartsStore } from "../stores/charts";
import type { BoardInfo } from "../types";

const store = useChartsStore();
useStalePoll();

const tab = ref<0 | 1>(0);
type OverviewSlot = "left" | "right";
const keys = ref<Partial<Record<OverviewSlot, string>>>({});

const leftSource = computed(() =>
  store.boards.find((item) => item.enabled && item.overview_slot === "left"),
);
const rightSource = computed(() =>
  store.boards.find((item) => item.enabled && item.overview_slot === "right"),
);

function columnBoard(
  source: BoardInfo | undefined,
  slot: OverviewSlot,
  fallbackPlatform: string,
  fallbackKey: string,
): BoardInfo {
  const platform = source?.platform ?? fallbackPlatform;
  const key = keys.value[slot] || source?.chart_key || fallbackKey;
  return resolveCatalogBoard(store.catalog, store.boards, platform, key);
}

const left = computed(() => columnBoard(leftSource.value, "left", "qqmusic", "26"));
const right = computed(() => columnBoard(rightSource.value, "right", "netease", "3778678"));

const leftLatest = computed(() => latestOfBoard(store.latest, store.boards, left.value));
const rightLatest = computed(() => latestOfBoard(store.latest, store.boards, right.value));
const leftItems = computed(() => leftLatest.value?.items ?? []);
const rightItems = computed(() => rightLatest.value?.items ?? []);

function applyDefaults() {
  const sources: Array<[OverviewSlot, BoardInfo | undefined]> = [
    ["left", leftSource.value],
    ["right", rightSource.value],
  ];
  for (const [slot, board] of sources) {
    if (board?.chart_key && !keys.value[slot]) {
      keys.value[slot] = board.chart_key;
    }
  }
}

function setKey(slot: OverviewSlot, key: string) {
  keys.value = { ...keys.value, [slot]: key };
}

watch(
  () =>
    store.boards
      .map((item) => `${item.id}:${item.chart_key}:${item.overview_slot ?? ""}`)
      .join(),
  () => applyDefaults(),
);

watch([left, right], ([nextLeft, nextRight]) => {
  void store.ensureLatest(nextLeft);
  void store.ensureLatest(nextRight);
});

onMounted(() => {
  void store.refreshAll().then(() => {
    applyDefaults();
    if (!leftItems.value.length || !rightItems.value.length) {
      window.setTimeout(() => {
        void store.refreshAll().then(applyDefaults);
      }, 2000);
    }
  });
});
</script>

<template>
  <div>
    <section class="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <p class="text-sm text-zinc-500">{{ todayLabel() }}</p>
        <h1 class="mt-1 text-2xl font-semibold tracking-tight md:text-3xl">今日榜单</h1>
        <p class="mt-2 max-w-xl text-sm text-zinc-500">
          点每列榜名切换该平台全部官方榜。分数只在本榜内归一化，不是跨平台同一首歌。
        </p>
      </div>
      <div class="flex flex-wrap gap-2 text-sm">
        <span
          class="rounded-full bg-white px-3 py-1 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-white/10"
        >
          {{ platformShortName(left.platform, store.platforms) }} {{ leftItems.length }} 首 · 升
          {{ risingCount(leftItems) }}
        </span>
        <span
          class="rounded-full bg-white px-3 py-1 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-white/10"
        >
          {{ platformShortName(right.platform, store.platforms) }} {{ rightItems.length }} 首 · 升
          {{ risingCount(rightItems) }}
        </span>
      </div>
    </section>

    <div class="mb-4 grid grid-cols-2 gap-1 rounded-full bg-zinc-200/80 p-1 md:hidden dark:bg-zinc-800">
      <button
        type="button"
        class="grid h-11 place-items-center rounded-full px-3 text-sm"
        :class="tab === 0 ? 'bg-white shadow-sm dark:bg-zinc-950' : 'text-zinc-500'"
        @click="tab = 0"
      >
        {{ platformShortName(left.platform, store.platforms) }}
      </button>
      <button
        type="button"
        class="grid h-11 place-items-center rounded-full px-3 text-sm"
        :class="tab === 1 ? 'bg-white shadow-sm dark:bg-zinc-950' : 'text-zinc-500'"
        @click="tab = 1"
      >
        {{ platformShortName(right.platform, store.platforms) }}
      </button>
    </div>

    <div class="grid gap-4 md:grid-cols-2">
      <HeroCard
        :class="tab === 0 ? '' : 'hidden md:block'"
        :board="left"
        :latest="leftLatest"
      />
      <HeroCard
        :class="tab === 1 ? '' : 'hidden md:block'"
        :board="right"
        :latest="rightLatest"
      />
    </div>

    <div class="mt-6 grid gap-8 md:grid-cols-2">
      <BoardColumn
        :class="tab === 0 ? '' : 'hidden md:block'"
        :board="left"
        :latest="leftLatest"
        :show-hero="false"
        :limit="15"
        :link-to-chart="!left.id.startsWith('catalog:')"
        :picker-groups="groupsOf(store.catalog, left.platform)"
        @pick="setKey('left', $event)"
        @reorder="(key, beforeKey) => store.reorderCatalogChart(left.platform, key, beforeKey)"
      />
      <BoardColumn
        :class="tab === 1 ? '' : 'hidden md:block'"
        :board="right"
        :latest="rightLatest"
        :show-hero="false"
        :limit="15"
        :link-to-chart="!right.id.startsWith('catalog:')"
        :picker-groups="groupsOf(store.catalog, right.platform)"
        @pick="setKey('right', $event)"
        @reorder="(key, beforeKey) => store.reorderCatalogChart(right.platform, key, beforeKey)"
      />
    </div>

    <div
      v-if="store.error"
      class="mt-6 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-600 ring-1 ring-zinc-200 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-500/20"
    >
      <div class="flex items-center justify-between gap-3">
        <p>{{ store.error }}</p>
        <button type="button" class="underline" @click="store.refreshAll()">重试</button>
      </div>
    </div>
  </div>
</template>
