<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";
import { searchTracks } from "./api";
import PlayerBar from "./components/PlayerBar.vue";
import SettingsMenu from "./components/SettingsMenu.vue";
import { defaultBoardForPlatform, platformLabel } from "./lib/boards";
import { useChartsStore } from "./stores/charts";
import { useHealthStore } from "./stores/health";
import type { SearchResult } from "./types";

const route = useRoute();
const router = useRouter();
const charts = useChartsStore();
const health = useHealthStore();
const searchQuery = ref("");
const suggestions = ref<SearchResult[]>([]);
const searchOpen = ref(false);
const suggestionsLoading = ref(false);
const activeSuggestion = ref(-1);
const searchRoot = ref<HTMLElement | null>(null);
let searchTimer = 0;
let searchRequestNo = 0;
let searchController: AbortController | null = null;

const qqBoard = computed(() => defaultBoardForPlatform(charts.boards, "qqmusic"));
const neteaseBoard = computed(() => defaultBoardForPlatform(charts.boards, "netease"));
const bilibiliBoard = computed(() => defaultBoardForPlatform(charts.boards, "bilibili"));
const qqTo = computed(() => `/charts/${qqBoard.value?.id ?? "qq_hot"}`);
const neteaseTo = computed(() => `/charts/${neteaseBoard.value?.id ?? "netease_hot"}`);
const bilibiliTo = computed(() => `/charts/${bilibiliBoard.value?.id ?? "bilibili_hot"}`);

const currentChartPlatform = computed(() => {
  if (route.name !== "chart") return "";
  const id = String(route.params.board ?? "");
  const fromStore = charts.boards.find((item) => item.id === id)?.platform;
  if (fromStore) return fromStore;
  if (id === qqBoard.value?.id || id === "qq_hot") return "qqmusic";
  if (id === neteaseBoard.value?.id || id === "netease_hot") return "netease";
  if (id === bilibiliBoard.value?.id || id === "bilibili_hot") return "bilibili";
  return "";
});

function navClass(active: boolean): string {
  return [
    "grid h-11 place-items-center rounded-full px-2 text-sm transition md:h-auto md:px-3 md:py-1.5",
    active
      ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900"
      : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-white/10",
  ].join(" ");
}

function scheduleSuggestionSearch() {
  window.clearTimeout(searchTimer);
  searchRequestNo += 1;
  searchOpen.value = true;
  activeSuggestion.value = -1;
  const query = searchQuery.value.trim();
  if (query.length < 2) {
    suggestions.value = [];
    suggestionsLoading.value = false;
    searchController?.abort();
    return;
  }
  searchTimer = window.setTimeout(() => {
    void loadSuggestions(query);
  }, 300);
}

async function loadSuggestions(query: string) {
  const requestNo = ++searchRequestNo;
  searchController?.abort();
  const controller = new AbortController();
  searchController = controller;
  suggestionsLoading.value = true;
  try {
    const response = await searchTracks(query, "suggest", 5, controller.signal);
    if (requestNo !== searchRequestNo) return;
    suggestions.value = response.code === 0 ? response.data.items : [];
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    if (requestNo === searchRequestNo) suggestions.value = [];
  } finally {
    if (requestNo === searchRequestNo) suggestionsLoading.value = false;
  }
}

function closeSearchPanel() {
  searchOpen.value = false;
  activeSuggestion.value = -1;
}

function onDocumentPointerDown(event: PointerEvent) {
  const root = searchRoot.value;
  if (!root || !searchOpen.value) return;
  if (event.target instanceof Node && root.contains(event.target)) return;
  closeSearchPanel();
}

function submitSearch() {
  const query = searchQuery.value.trim();
  if (query.length < 2) return;
  closeSearchPanel();
  void router.push({ name: "search", query: { q: query } });
}

function chooseSuggestion(result: SearchResult) {
  searchQuery.value = `${result.title} ${result.artist}`.trim();
  submitSearch();
}

function onSearchKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") {
    closeSearchPanel();
    return;
  }
  if (event.key === "ArrowDown" && suggestions.value.length) {
    event.preventDefault();
    activeSuggestion.value = (activeSuggestion.value + 1) % suggestions.value.length;
    return;
  }
  if (event.key === "ArrowUp" && suggestions.value.length) {
    event.preventDefault();
    activeSuggestion.value =
      activeSuggestion.value <= 0
        ? suggestions.value.length - 1
        : activeSuggestion.value - 1;
    return;
  }
  if (event.key === "Enter") {
    event.preventDefault();
    const result = suggestions.value[activeSuggestion.value];
    if (result) {
      chooseSuggestion(result);
    } else {
      submitSearch();
    }
  }
}

let pollTimer = 0;
onMounted(() => {
  searchQuery.value = String(route.query.q ?? "");
  if (!charts.boards.length) {
    void charts.loadBoards();
  }
  void health.refresh();
  pollTimer = window.setInterval(() => {
    void health.refresh();
  }, 60_000);
  document.addEventListener("pointerdown", onDocumentPointerDown);
});
watch(
  () => route.query.q,
  (value) => {
    searchQuery.value = value == null ? "" : String(value);
  },
);
watch(
  () => route.fullPath,
  () => {
    closeSearchPanel();
  },
);
onUnmounted(() => {
  window.clearInterval(pollTimer);
  window.clearTimeout(searchTimer);
  searchController?.abort();
  document.removeEventListener("pointerdown", onDocumentPointerDown);
});
</script>

<template>
  <div
    class="relative min-h-dvh pb-[calc(9.5rem+env(safe-area-inset-bottom,0px))] md:pb-[calc(6.5rem+env(safe-area-inset-bottom,0px))]"
  >
    <div class="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div
        class="absolute -left-16 -top-24 h-72 w-72 rounded-full bg-rose-300/25 blur-3xl dark:bg-rose-500/10"
      />
      <div
        class="absolute right-0 top-24 h-80 w-80 rounded-full bg-indigo-300/20 blur-3xl dark:bg-indigo-500/10"
      />
      <div
        class="absolute bottom-10 left-1/3 h-64 w-64 rounded-full bg-amber-200/20 blur-3xl dark:bg-amber-500/5"
      />
    </div>
    <header
      class="sticky top-0 z-20 border-b border-zinc-200 bg-white/70 pt-[env(safe-area-inset-top,0px)] backdrop-blur-xl dark:border-white/10 dark:bg-zinc-950/60"
    >
      <div
        class="mx-auto flex max-w-7xl flex-col gap-2 px-4 py-2 md:flex-row md:items-center md:py-3"
      >
        <div class="flex items-center justify-between gap-3 md:contents">
          <RouterLink to="/" class="flex min-h-11 items-center gap-2">
            <span
              class="grid h-8 w-8 place-items-center rounded-xl bg-zinc-900 text-sm font-bold text-white dark:bg-white dark:text-zinc-900"
            >
              m
            </span>
            <span class="text-lg font-semibold tracking-tight">musico</span>
          </RouterLink>
          <SettingsMenu class="md:order-last" />
        </div>
        <div ref="searchRoot" class="relative order-2 min-w-0 flex-1 md:order-none md:max-w-md">
          <form @submit.prevent="submitSearch">
            <label class="sr-only" for="global-search">搜索歌曲</label>
            <div class="relative">
              <svg
                viewBox="0 0 20 20"
                aria-hidden="true"
                class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400"
                fill="none"
              >
                <circle cx="8.5" cy="8.5" r="5.5" stroke="currentColor" stroke-width="1.5" />
                <path d="m13 13 4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
              </svg>
              <input
                id="global-search"
                v-model="searchQuery"
                type="search"
                autocomplete="off"
                placeholder="搜索歌曲或歌手"
                class="h-11 w-full rounded-full bg-zinc-100 pl-9 pr-4 text-sm outline-none ring-1 ring-transparent transition placeholder:text-zinc-400 focus:bg-white focus:ring-zinc-300 dark:bg-zinc-900 dark:focus:bg-zinc-900 dark:focus:ring-white/20"
                @input="scheduleSuggestionSearch"
                @focus="searchOpen = true"
                @keydown="onSearchKeydown"
              />
            </div>
          </form>
          <div
            v-if="searchOpen && (suggestionsLoading || suggestions.length || searchQuery.trim().length >= 2)"
            class="absolute inset-x-0 top-12 z-30 overflow-hidden rounded-2xl bg-white shadow-xl ring-1 ring-zinc-200/80 dark:bg-zinc-900 dark:ring-white/10"
          >
            <div v-if="suggestionsLoading" class="px-4 py-4 text-sm text-zinc-500">
              正在搜索…
            </div>
            <template v-else-if="suggestions.length">
              <button
                v-for="(result, index) in suggestions"
                :key="`${result.platform}:${result.external_id}`"
                type="button"
                class="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-zinc-50 dark:hover:bg-white/5"
                :class="activeSuggestion === index ? 'bg-zinc-50 dark:bg-white/5' : ''"
                @click="chooseSuggestion(result)"
              >
                <div class="min-w-0 flex-1">
                  <div class="truncate text-sm font-medium">{{ result.title }}</div>
                  <div class="truncate text-xs text-zinc-500 dark:text-zinc-400">
                    {{ result.artist }}
                  </div>
                </div>
                <span class="flex shrink-0 gap-1 text-xs text-zinc-400">
                  <span v-for="source in result.platforms" :key="`${source.platform}:${source.external_id}`">
                    {{ platformLabel(source.platform) }}
                  </span>
                </span>
              </button>
              <button
                type="button"
                class="w-full border-t border-zinc-100 px-4 py-3 text-left text-sm text-zinc-500 hover:bg-zinc-50 dark:border-white/5 dark:text-zinc-400 dark:hover:bg-white/5"
                @click="submitSearch"
              >
                查看全部结果
              </button>
            </template>
            <div v-else class="px-4 py-4 text-sm text-zinc-500">
              暂无匹配歌曲，按 Enter 查看结果
            </div>
          </div>
        </div>
        <nav
          class="order-3 grid grid-cols-4 gap-1 rounded-full bg-zinc-200/80 p-1 text-zinc-600 md:order-none md:ml-auto md:flex md:items-center md:bg-transparent md:p-0 dark:bg-zinc-800 md:dark:bg-transparent"
        >
          <RouterLink to="/" :class="navClass(route.name === 'overview')">总览</RouterLink>
          <RouterLink :to="qqTo" :class="navClass(currentChartPlatform === 'qqmusic')">
            QQ
          </RouterLink>
          <RouterLink :to="neteaseTo" :class="navClass(currentChartPlatform === 'netease')">
            网易
          </RouterLink>
          <RouterLink :to="bilibiliTo" :class="navClass(currentChartPlatform === 'bilibili')">
            B站
          </RouterLink>
        </nav>
      </div>
    </header>
    <main class="mx-auto max-w-7xl px-4 py-4 md:py-6">
      <RouterView />
    </main>
    <PlayerBar />
  </div>
</template>
