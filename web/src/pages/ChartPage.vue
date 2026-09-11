<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import BoardColumn from "../components/BoardColumn.vue";
import { useStalePoll } from "../composables/useStalePoll";
import { groupsOf, latestOfBoard, resolveCatalogBoard } from "../lib/catalog-board";
import { platformLabel } from "../lib/boards";
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
        class="inline-flex min-h-11 items-center gap-1 text-base text-zinc-500 transition hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-white"
      >
        <svg viewBox="0 0 16 16" aria-hidden="true" class="h-5 w-5 shrink-0" fill="none">
          <path
            d="M10 3.5 5.5 8 10 12.5"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        返回
      </RouterLink>
      <h1 class="mt-5 text-2xl font-semibold tracking-tight md:text-3xl">
        {{ source ? platformLabel(source.platform) : "榜单" }}
      </h1>
    </section>
    <BoardColumn
      v-if="current"
      :board="current"
      :latest="latest"
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
