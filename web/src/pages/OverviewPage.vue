<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import BoardColumn from "../components/BoardColumn.vue";
import HeroCard from "../components/HeroCard.vue";
import { useStalePoll } from "../composables/useStalePoll";
import { groupsOf, latestOfBoard, resolveCatalogBoard } from "../lib/catalog-board";
import { platformShortName } from "../lib/boards";
import { todayLabel } from "../lib/format";
import { useChartsStore } from "../stores/charts";

const store = useChartsStore();
useStalePoll();

const tab = ref(0);
const keys = ref<Record<string, string>>({});
const slotOrder: Record<string, number> = { left: 0, right: 1 };

const overviewSources = computed(() =>
  [...store.boards]
    .filter((item) => item.enabled)
    .sort(
      (a, b) =>
        (slotOrder[a.overview_slot ?? ""] ?? 2) - (slotOrder[b.overview_slot ?? ""] ?? 2) ||
        (a.sort_order ?? 10_000) - (b.sort_order ?? 10_000),
    )
    .filter(
      (item, index, items) =>
        items.findIndex((candidate) => candidate.platform === item.platform) === index,
    )
    .slice(0, 3),
);

const columns = computed(() =>
  overviewSources.value.map((source) => {
    const key = keys.value[source.id] || source.chart_key || "";
    const board = key
      ? resolveCatalogBoard(store.catalog, store.boards, source.platform, key)
      : source;
    return {
      source,
      board,
      latest: latestOfBoard(store.latest, store.boards, board),
    };
  }),
);

function applyDefaults() {
  const next = { ...keys.value };
  for (const source of overviewSources.value) {
    if (source.chart_key && !next[source.id]) next[source.id] = source.chart_key;
  }
  keys.value = next;
  if (tab.value >= overviewSources.value.length) tab.value = 0;
}

function setKey(sourceId: string, key: string) {
  keys.value = { ...keys.value, [sourceId]: key };
}

watch(
  () => store.boards.map((item) => `${item.id}:${item.chart_key}:${item.sort_order}`).join(),
  applyDefaults,
);
watch(
  () => columns.value.map((item) => item.board.id).join(),
  () => {
    for (const column of columns.value) void store.ensureLatest(column.board);
  },
);

let retryTimer = 0;
onMounted(() => {
  void store.refreshAll().then(() => {
    applyDefaults();
    if (columns.value.some((column) => !column.latest?.items.length)) {
      retryTimer = window.setTimeout(() => void store.refreshAll().then(applyDefaults), 2000);
    }
  });
});
onUnmounted(() => window.clearTimeout(retryTimer));
</script>

<template>
  <div>
    <section class="mb-6">
      <p class="text-sm text-secondary">{{ todayLabel() }}</p>
      <h1 data-page-heading tabindex="-1" class="mt-1 text-2xl font-semibold tracking-tight outline-none md:text-3xl">今日榜单</h1>
    </section>

    <div class="mb-4 flex gap-1 overflow-x-auto rounded-full bg-zinc-200/80 p-1 md:hidden dark:bg-zinc-800">
      <button
        v-for="(column, index) in columns"
        :key="column.source.id"
        type="button"
        class="grid h-11 min-w-24 flex-1 place-items-center rounded-full px-3 text-sm"
        :class="tab === index ? 'bg-white dark:bg-zinc-950' : 'text-secondary'"
        :aria-pressed="tab === index"
        @click="tab = index"
      >
        {{ platformShortName(column.board.platform, store.platforms) }}
      </button>
    </div>

    <div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      <HeroCard
        v-for="(column, index) in columns"
        :key="`hero:${column.source.id}`"
        :class="tab === index ? '' : 'hidden md:block'"
        :board="column.board"
        :latest="column.latest"
      />
    </div>

    <div class="mt-6 grid gap-8 md:grid-cols-2 lg:grid-cols-3">
      <BoardColumn
        v-for="(column, index) in columns"
        :key="`list:${column.source.id}`"
        :class="tab === index ? '' : 'hidden md:block'"
        :board="column.board"
        :latest="column.latest"
        :show-hero="false"
        :picker-groups="groupsOf(store.catalog, column.board.platform)"
        @pick="setKey(column.source.id, $event)"
        @reorder="(key, beforeKey) => store.reorderCatalogChart(column.board.platform, key, beforeKey)"
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
