<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import PageHeader from "../components/PageHeader.vue";
import SearchResultRow from "../components/SearchResultRow.vue";
import { isAbortError, searchTracks } from "../api";
import type { SearchPayload } from "../types";

const route = useRoute();
const query = ref("");
const payload = ref<SearchPayload | null>(null);
const loading = ref(false);
const error = ref("");
let requestNo = 0;
let controller: AbortController | null = null;
const selectedPlatform = ref("all");

const normalizedQuery = computed(() => String(route.query.q ?? "").trim());
const hasPlatformError = computed(() =>
  Boolean(payload.value?.platforms.some((item) => item.status === "error")),
);
const hasSuccessfulPlatform = computed(() =>
  Boolean(payload.value?.platforms.some((item) => item.status !== "error")),
);
const visibleItems = computed(() => {
  const items = payload.value?.items ?? [];
  if (selectedPlatform.value === "all") return items;
  return items.filter((item) =>
    item.platforms.some((source) => source.platform === selectedPlatform.value),
  );
});

async function load() {
  const currentQuery = normalizedQuery.value;
  const currentRequest = ++requestNo;
  query.value = currentQuery;
  payload.value = null;
  error.value = "";
  selectedPlatform.value = "all";
  loading.value = false;
  controller?.abort();
  controller = null;
  if (currentQuery.length < 2) return;

  loading.value = true;
  const currentController = new AbortController();
  controller = currentController;
  try {
    const response = await searchTracks(currentQuery, "full", 20, currentController.signal);
    if (currentRequest !== requestNo) return;
    if (response.code !== 0) {
      error.value = response.msg || "搜索失败";
      return;
    }
    payload.value = response.data;
  } catch (reason) {
    if (isAbortError(reason) || currentController.signal.aborted) {
      return;
    }
    if (currentRequest === requestNo) {
      error.value = reason instanceof Error ? reason.message : "搜索失败";
    }
  } finally {
    if (currentRequest === requestNo) loading.value = false;
  }
}

function retry() {
  void load();
}

onMounted(() => {
  void load();
});
onUnmounted(() => controller?.abort());

watch(
  () => route.query.q,
  () => {
    void load();
  },
);
</script>

<template>
  <section>
    <PageHeader
      :title="query || '输入歌曲名或歌手'"
      eyebrow="搜索结果"
      back-to="/"
    />

    <div
      v-if="error"
      role="alert"
      class="mb-4 flex items-center justify-between gap-3 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-600 ring-1 ring-rose-200 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-500/20"
    >
      <span>{{ error }}</span>
      <button type="button" class="shrink-0 underline" @click="retry">重试</button>
    </div>

    <div
      v-if="loading"
      class="space-y-2 overflow-hidden rounded-2xl bg-white p-3 ring-1 ring-zinc-200/80 dark:bg-zinc-900 dark:ring-white/10"
    >
      <div v-for="n in 6" :key="n" class="flex items-center gap-3 px-1 py-2">
        <div class="skel h-12 w-12 rounded-lg" />
        <div class="flex-1 space-y-2">
          <div class="skel h-3 w-2/3" />
          <div class="skel h-3 w-1/3" />
        </div>
      </div>
    </div>

    <template v-else-if="payload">
      <div class="mb-3 flex flex-wrap items-center justify-between gap-2 text-sm text-secondary">
        <span>{{ visibleItems.length ? `显示 ${visibleItems.length} 首相关歌曲` : "没有找到相关歌曲" }}</span>
        <span v-if="hasPlatformError && hasSuccessfulPlatform" class="text-amber-600 dark:text-amber-400">
          部分平台暂时不可用
        </span>
        <span v-else-if="hasPlatformError" class="text-rose-600 dark:text-rose-300">
          搜索平台暂时不可用
        </span>
      </div>

      <div v-if="payload.platforms.length > 1" class="mb-3 flex gap-2 overflow-x-auto pb-1" aria-label="平台筛选">
        <button
          type="button"
          class="h-11 shrink-0 rounded-full px-4 text-sm ring-1 ring-zinc-300 dark:ring-white/15"
          :class="selectedPlatform === 'all' ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900' : ''"
          :aria-pressed="selectedPlatform === 'all'"
          @click="selectedPlatform = 'all'"
        >
          全部
        </button>
        <button
          v-for="platform in payload.platforms"
          :key="platform.id"
          type="button"
          class="h-11 shrink-0 rounded-full px-4 text-sm ring-1 ring-zinc-300 disabled:opacity-50 dark:ring-white/15"
          :class="selectedPlatform === platform.id ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900' : ''"
          :aria-pressed="selectedPlatform === platform.id"
          :disabled="platform.status === 'error'"
          @click="selectedPlatform = platform.id"
        >
          {{ platform.name }}
        </button>
      </div>

      <div
        v-if="visibleItems.length"
        class="divide-y divide-zinc-100 overflow-hidden rounded-2xl bg-white ring-1 ring-zinc-200/80 dark:divide-white/5 dark:bg-zinc-900 dark:ring-white/10"
      >
        <SearchResultRow v-for="result in visibleItems" :key="`${result.platform}:${result.external_id}`" :result="result" />
      </div>
      <div
        v-else
        class="rounded-2xl bg-white px-4 py-12 text-center text-sm text-secondary ring-1 ring-zinc-200/80 dark:bg-zinc-900 dark:ring-white/10"
      >
        换个歌曲名或歌手试试
      </div>
    </template>

    <div
      v-else-if="query.length < 2"
      class="rounded-2xl bg-white px-4 py-12 text-center text-sm text-secondary ring-1 ring-zinc-200/80 dark:bg-zinc-900 dark:ring-white/10"
    >
      至少输入 2 个字符开始搜索
    </div>
  </section>
</template>
