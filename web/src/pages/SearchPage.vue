<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import SearchResultRow from "../components/SearchResultRow.vue";
import { searchTracks } from "../api";
import type { SearchPayload } from "../types";

const route = useRoute();
const router = useRouter();
const query = ref("");
const payload = ref<SearchPayload | null>(null);
const loading = ref(false);
const error = ref("");
let requestNo = 0;

const normalizedQuery = computed(() => String(route.query.q ?? "").trim());
const hasPlatformError = computed(() =>
  Boolean(payload.value?.platforms.some((item) => item.status === "error")),
);
const hasSuccessfulPlatform = computed(() =>
  Boolean(payload.value?.platforms.some((item) => item.status !== "error")),
);

async function load() {
  const currentQuery = normalizedQuery.value;
  const currentRequest = ++requestNo;
  query.value = currentQuery;
  payload.value = null;
  error.value = "";
  if (currentQuery.length < 2) return;

  loading.value = true;
  try {
    const response = await searchTracks(currentQuery, "full", 20);
    if (currentRequest !== requestNo) return;
    if (response.code !== 0) {
      error.value = response.msg || "搜索失败";
      return;
    }
    payload.value = response.data;
  } catch (reason) {
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

function goHome() {
  void router.push("/");
}

onMounted(() => {
  void load();
});

watch(
  () => route.query.q,
  () => {
    void load();
  },
);
</script>

<template>
  <section>
    <div class="mb-6">
      <button
        type="button"
        class="inline-flex min-h-11 items-center gap-1 text-base text-zinc-500 transition hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-white"
        @click="goHome"
      >
        <svg viewBox="0 0 16 16" aria-hidden="true" class="h-5 w-5 shrink-0" fill="none">
          <path d="M10 3.5 5.5 8 10 12.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        返回
      </button>
      <p class="mt-5 text-sm text-zinc-500">搜索结果</p>
      <h1 class="mt-1 truncate text-2xl font-semibold tracking-tight md:text-3xl">
        {{ query || "输入歌曲名或歌手" }}
      </h1>
    </div>

    <div
      v-if="error"
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
      <div class="mb-3 flex flex-wrap items-center justify-between gap-2 text-sm text-zinc-500 dark:text-zinc-400">
        <span>{{ payload.items.length ? `找到 ${payload.items.length} 首相关歌曲` : "没有找到相关歌曲" }}</span>
        <span v-if="hasPlatformError && hasSuccessfulPlatform" class="text-amber-600 dark:text-amber-400">
          部分平台暂时不可用
        </span>
        <span v-else-if="hasPlatformError" class="text-rose-600 dark:text-rose-300">
          搜索平台暂时不可用
        </span>
      </div>

      <div
        v-if="payload.items.length"
        class="divide-y divide-zinc-100 overflow-hidden rounded-2xl bg-white ring-1 ring-zinc-200/80 dark:divide-white/5 dark:bg-zinc-900 dark:ring-white/10"
      >
        <SearchResultRow v-for="result in payload.items" :key="`${result.platform}:${result.external_id}`" :result="result" />
      </div>
      <div
        v-else
        class="rounded-2xl bg-white px-4 py-12 text-center text-sm text-zinc-500 ring-1 ring-zinc-200/80 dark:bg-zinc-900 dark:ring-white/10"
      >
        换个歌曲名或歌手试试
      </div>
    </template>

    <div
      v-else-if="query.length < 2"
      class="rounded-2xl bg-white px-4 py-12 text-center text-sm text-zinc-500 ring-1 ring-zinc-200/80 dark:bg-zinc-900 dark:ring-white/10"
    >
      至少输入 2 个字符开始搜索
    </div>
  </section>
</template>
