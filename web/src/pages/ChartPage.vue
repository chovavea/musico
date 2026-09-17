<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import AppIcon from "../components/AppIcon.vue";
import BoardColumn from "../components/BoardColumn.vue";
import GlazeTrackRow from "../components/GlazeTrackRow.vue";
import PageHeader from "../components/PageHeader.vue";
import { useStalePoll } from "../composables/useStalePoll";
import { groupsOf, latestOfBoard, resolveCatalogBoard } from "../lib/catalog-board";
import { chartShortName, platformLabel } from "../lib/boards";
import { useChartsStore } from "../stores/charts";
import { useThemeStore } from "../stores/theme";

const props = defineProps<{ board: string }>();
const store = useChartsStore();
const theme = useThemeStore();
useStalePoll();

const selectedKey = ref("");
const PAGE_SIZE = 20;
const visibleCount = ref(PAGE_SIZE);

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
const glazeCharts = computed(() => {
  const platform = source.value?.platform;
  if (!platform) return [];
  const yaml = store.boards.filter((item) => item.enabled && item.platform === platform);
  if (yaml.length > 1) {
    return yaml.map((item) => ({
      key: item.chart_key || item.id,
      name: chartShortName(item.name),
    }));
  }
  return pickerGroups.value.flatMap((group) => group.charts);
});
const glazeItems = computed(() => latest.value?.items ?? []);
const visibleItems = computed(() => glazeItems.value.slice(0, visibleCount.value));
const hasMore = computed(() => visibleCount.value < glazeItems.value.length);

function applyDefault() {
  selectedKey.value = source.value?.chart_key || "";
}

function setKey(key: string) {
  selectedKey.value = key;
  visibleCount.value = PAGE_SIZE;
}

function onReorder(key: string, beforeKey: string | null) {
  if (!current.value) return;
  void store.reorderCatalogChart(current.value.platform, key, beforeKey);
}

function loadMore() {
  visibleCount.value = Math.min(glazeItems.value.length, visibleCount.value + PAGE_SIZE);
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
  visibleCount.value = PAGE_SIZE;
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
  <div v-if="theme.isGlaze">
    <RouterLink to="/" class="gz-more mb-3 inline-flex min-h-10">
      <AppIcon name="chevron-left" :size="16" />
      返回
    </RouterLink>
    <div class="gz-section mt-0">
      <h1 data-page-heading tabindex="-1" class="gz-section-title outline-none">
        <span aria-hidden="true">🔥</span>
        <span class="truncate">
          {{ current ? `${platformLabel(current.platform)} ${chartShortName(current.name)}` : "榜单" }}
        </span>
      </h1>
    </div>
    <div v-if="glazeCharts.length > 1" class="gz-tabs mb-3" role="tablist" aria-label="切换榜单">
      <button
        v-for="chart in glazeCharts"
        :key="chart.key"
        type="button"
        class="gz-tab"
        :class="(selectedKey || source?.chart_key) === chart.key ? 'is-on' : ''"
        role="tab"
        :aria-selected="(selectedKey || source?.chart_key) === chart.key"
        @click="setKey(chart.key)"
      >
        {{ chartShortName(chart.name) }}
      </button>
    </div>
    <div v-if="current" class="gz-tracks">
      <GlazeTrackRow
        v-for="(item, index) in visibleItems"
        :key="item.external_id"
        :item="item"
        :queue="glazeItems"
        :hit="index === 0"
      />
      <div v-if="!(glazeItems.length)" class="space-y-2 px-1 py-2">
        <div v-for="n in 8" :key="n" class="skel h-14 rounded-2xl" />
      </div>
      <button
        v-if="hasMore"
        type="button"
        class="gz-more mt-2 w-full justify-center"
        @click="loadMore"
      >
        加载更多
      </button>
    </div>
    <p v-else class="px-2 py-8 text-sm text-[color:var(--gz-muted)]">未找到该榜</p>
    <div
      v-if="store.error"
      class="mt-4 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-600 dark:bg-rose-500/10 dark:text-rose-300"
    >
      <div class="flex items-center justify-between gap-3">
        <p>{{ store.error }}</p>
        <button type="button" class="underline" @click="load()">重试</button>
      </div>
    </div>
  </div>
  <div v-else>
    <PageHeader
      :title="source ? platformLabel(source.platform) : '榜单'"
      eyebrow="单榜"
      back-to="/"
    />
    <div class="relative">
      <Transition name="page">
        <BoardColumn
          v-if="current"
          :key="current.id"
          :board="current"
          :latest="latest"
          :picker-groups="pickerGroups"
          @pick="setKey"
          @reorder="onReorder"
        />
        <p
          v-else
          key="missing"
          class="rounded-2xl bg-white p-6 text-zinc-500 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-white/10"
        >
          未找到该榜
        </p>
      </Transition>
    </div>
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
