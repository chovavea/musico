<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import BoardColumn from "../components/BoardColumn.vue";
import { useStalePoll } from "../composables/useStalePoll";
import { groupsOf, latestOfBoard, resolveCatalogBoard } from "../lib/catalog-board";
import { platformLabel } from "../lib/boards";
import { formatUpdatedAt, risingCount } from "../lib/format";
import { useChartsStore } from "../stores/charts";

const props = defineProps<{ board: string }>();
const store = useChartsStore();
useStalePoll();

const selectedKey = ref("");

const source = computed(() => store.boards.find((item) => item.id === props.board));

const current = computed(() => {
  if (!source.value) return undefined;
  const key = selectedKey.value || source.value.chart_key || "";
  if (!key) return source.value;
  return resolveCatalogBoard(store.catalog, store.boards, source.value.platform, key);
});

const latest = computed(() =>
  current.value ? latestOfBoard(store.latest, store.boards, current.value) : undefined,
);
const items = computed(() => latest.value?.items ?? []);
const pickerGroups = computed(() =>
  source.value ? groupsOf(store.catalog, source.value.platform) : [],
);

function applyDefault() {
  selectedKey.value = source.value?.chart_key || "";
}

function setKey(key: string) {
  selectedKey.value = key;
}

function onReorder(key: string, beforeKey: string | null) {
  if (!current.value) return;
  void store.reorderCatalogChart(current.value.platform, key, beforeKey);
}

async function load() {
  store.error = "";
  await store.loadBoards();
  try {
    await store.loadCatalog();
  } catch {
    // 目录失败时仍展示 yaml 单榜
  }
  applyDefault();
  if (current.value) {
    await store.ensureLatest(current.value);
  }
}

onMounted(() => {
  void load();
});

watch(
  () => props.board,
  () => {
    void load();
  },
);

watch(current, (board) => {
  if (board) void store.ensureLatest(board);
});
</script>

<template>
  <div>
    <section class="mb-6">
      <RouterLink
        to="/"
        class="inline-flex min-h-11 items-center text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-white"
      >
        ← 返回总览
      </RouterLink>
      <h1 class="mt-1 text-2xl font-semibold tracking-tight md:text-3xl">
        {{ source ? platformLabel(source.platform) : "榜单" }}
      </h1>
      <p class="mt-2 text-sm text-zinc-500">
        点榜名切换该平台全部官方榜。{{ items.length }} 首 · 升 {{ risingCount(items) }}
        · {{ formatUpdatedAt(latest?.fetched_at ?? latest?.updated_at) }}
        · 分数只在本榜内归一化
      </p>
    </section>
    <BoardColumn
      v-if="current"
      :board="current"
      :latest="latest"
      :link-to-chart="false"
      :picker-groups="pickerGroups"
      @pick="setKey"
      @reorder="onReorder"
    />
    <p
      v-else
      class="rounded-2xl bg-white p-6 text-zinc-500 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-white/10"
    >
      未找到该榜
    </p>
    <div
      v-if="store.error"
      class="mt-6 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-600 ring-1 ring-zinc-200 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-500/20"
    >
      <div class="flex items-center justify-between gap-3">
        <p>{{ store.error }}</p>
        <button type="button" class="underline" @click="load()">重试</button>
      </div>
    </div>
  </div>
</template>
