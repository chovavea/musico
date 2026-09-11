<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";
import { isAbortError, searchTracks } from "./api";
import AppIcon from "./components/AppIcon.vue";
import PlayerBar from "./components/PlayerBar.vue";
import SettingsMenu from "./components/SettingsMenu.vue";
import { platformLabel, platformShortName } from "./lib/boards";
import { useChartsStore } from "./stores/charts";
import { useHealthStore } from "./stores/health";
import { usePlayerStore } from "./stores/player";
import type { SearchResult } from "./types";

const route = useRoute();
const router = useRouter();
const charts = useChartsStore();
const health = useHealthStore();
const player = usePlayerStore();

const searchQuery = ref("");
const suggestions = ref<SearchResult[]>([]);
const searchOpen = ref(false);
const suggestionsLoading = ref(false);
const suggestionsError = ref("");
const activeSuggestion = ref(-1);
const searchRoot = ref<HTMLElement | null>(null);
const searchInput = ref<HTMLInputElement | null>(null);
const searchTrigger = ref<HTMLButtonElement | null>(null);
let searchTimer = 0;
let searchRequestNo = 0;
let searchController: AbortController | null = null;

const navBoards = computed(() =>
  [...charts.boards]
    .filter((item) => item.enabled)
    .sort((a, b) => (a.sort_order ?? 10_000) - (b.sort_order ?? 10_000))
    .filter(
      (item, index, items) =>
        items.findIndex((candidate) => candidate.platform === item.platform) === index,
    ),
);

const currentChartPlatform = computed(() => {
  if (route.name !== "chart") return "";
  const id = String(route.params.board ?? "");
  const fromStore = charts.boards.find((item) => item.id === id)?.platform;
  if (fromStore) return fromStore;
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

function navTo(id: string): string {
  return `/charts/${encodeURIComponent(id)}`;
}

function scheduleSuggestionSearch() {
  window.clearTimeout(searchTimer);
  searchRequestNo += 1;
  activeSuggestion.value = -1;
  const query = searchQuery.value.trim();
  if (query.length < 2) {
    suggestions.value = [];
    suggestionsError.value = "";
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
  suggestionsError.value = "";
  try {
    const response = await searchTracks(query, "suggest", 5, controller.signal);
    if (requestNo !== searchRequestNo) return;
    if (response.code !== 0) {
      suggestions.value = [];
      suggestionsError.value = response.msg || "搜索失败";
      return;
    }
    suggestions.value = response.data.items;
  } catch (error) {
    if (isAbortError(error) || controller.signal.aborted) return;
    if (requestNo === searchRequestNo) {
      suggestions.value = [];
      suggestionsError.value = error instanceof Error ? error.message : "搜索失败";
    }
  } finally {
    if (requestNo === searchRequestNo) suggestionsLoading.value = false;
  }
}

function closeSearchPanel() {
  searchOpen.value = false;
  activeSuggestion.value = -1;
}

function openSearchPanel() {
  searchOpen.value = true;
  void nextTick(() => {
    searchInput.value?.focus();
  });
}

function toggleSearch() {
  if (searchOpen.value) {
    closeSearchPanel();
    searchTrigger.value?.focus();
    return;
  }
  openSearchPanel();
}

function onDocumentPointerDown(event: PointerEvent) {
  if (!searchOpen.value || !(event.target instanceof Node)) return;
  if (searchRoot.value?.contains(event.target)) return;
  closeSearchPanel();
}

function onDocumentKey(event: KeyboardEvent) {
  if (event.key === "Escape" && searchOpen.value) {
    closeSearchPanel();
    searchTrigger.value?.focus();
  }
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
    event.preventDefault();
    closeSearchPanel();
    searchTrigger.value?.focus();
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
  document.addEventListener("keydown", onDocumentKey);
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
  closeSearchPanel();
  document.removeEventListener("pointerdown", onDocumentPointerDown);
  document.removeEventListener("keydown", onDocumentKey);
});
</script>

<template>
  <div
    class="relative min-h-dvh"
    :class="player.current ? 'pb-[calc(6.5rem+env(safe-area-inset-bottom,0px))]' : 'pb-4'"
  >
    <a
      href="#main-content"
      class="sr-only fixed left-4 top-4 z-[110] rounded-lg bg-white px-4 py-3 text-zinc-900 focus:not-sr-only"
    >
      跳到主要内容
    </a>
    <header
      class="sticky top-0 z-20 border-b border-zinc-200 bg-white/95 pt-[env(safe-area-inset-top,0px)] dark:border-white/10 dark:bg-zinc-950/95"
    >
      <div class="mx-auto grid max-w-7xl grid-cols-[auto_minmax(0,1fr)] items-center gap-2 px-4 py-2 md:py-3">
        <RouterLink to="/" class="flex min-h-11 items-center gap-2" aria-label="Musico 首页">
          <span
            class="grid h-8 w-8 place-items-center rounded-xl bg-zinc-900 text-sm font-bold text-white dark:bg-white dark:text-zinc-900"
          >
            m
          </span>
          <span class="text-lg font-semibold tracking-tight">musico</span>
        </RouterLink>

        <div class="flex min-w-0 items-center justify-end gap-1">
          <nav class="hidden items-center md:flex" aria-label="主要导航">
            <RouterLink to="/" :class="navClass(route.name === 'overview')">总览</RouterLink>
            <RouterLink
              v-for="board in navBoards"
              :key="board.platform"
              :to="navTo(board.id)"
              :class="navClass(currentChartPlatform === board.platform)"
            >
              {{ platformShortName(board.platform, charts.platforms) }}
            </RouterLink>
          </nav>
          <div ref="searchRoot" class="relative flex min-w-0 items-center justify-end gap-1">
            <form
              v-if="searchOpen"
              class="relative min-w-0 flex-1 md:max-w-xs"
              @submit.prevent="submitSearch"
            >
              <label class="sr-only" for="global-search">搜索歌曲</label>
              <AppIcon
                name="search"
                :size="16"
                class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400"
              />
              <input
                id="global-search"
                ref="searchInput"
                v-model="searchQuery"
                type="search"
                autocomplete="off"
                enterkeyhint="search"
                placeholder="搜索歌曲或歌手"
                class="h-11 w-full rounded-full bg-zinc-100 pl-9 pr-3 text-sm outline-none ring-1 ring-transparent transition placeholder:text-zinc-400 focus:bg-white focus:ring-zinc-300 dark:bg-zinc-800 dark:focus:bg-zinc-800 dark:focus:ring-white/20"
                @input="scheduleSuggestionSearch"
                @keydown="onSearchKeydown"
              />
            </form>
            <button
              ref="searchTrigger"
              type="button"
              class="grid h-11 w-11 shrink-0 place-items-center rounded-full text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-white/10 dark:hover:text-white"
              :class="searchOpen ? 'bg-zinc-100 text-zinc-900 dark:bg-white/10 dark:text-white' : ''"
              :aria-expanded="searchOpen"
              aria-controls="global-search-suggestions"
              aria-label="搜索"
              @click.stop="toggleSearch()"
            >
              <AppIcon name="search" :size="24" />
            </button>
            <div
              v-if="searchOpen && (suggestionsLoading || suggestionsError || suggestions.length || searchQuery.trim().length >= 2)"
              id="global-search-suggestions"
              class="absolute right-0 top-full z-30 mt-2 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-2xl bg-white shadow-xl ring-1 ring-zinc-200/80 dark:bg-zinc-900 dark:ring-white/10"
            >
              <div class="max-h-80 overflow-y-auto">
                  <div v-if="suggestionsLoading" class="px-4 py-4 text-sm text-zinc-500">
                    正在搜索…
                  </div>
                  <div v-else-if="suggestionsError" class="px-4 py-4 text-sm text-rose-600 dark:text-rose-300">
                    {{ suggestionsError }}，按 Enter 仍可查看全部结果
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
                        <span
                          v-for="source in result.platforms"
                          :key="`${source.platform}:${source.external_id}`"
                        >
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
          </div>
          <SettingsMenu />
        </div>

        <nav
          class="col-span-2 grid gap-1 rounded-full bg-zinc-200/80 p-1 text-zinc-700 md:hidden dark:bg-zinc-800 dark:text-zinc-200"
          :style="{ gridTemplateColumns: `repeat(${Math.max(1, navBoards.length + 1)}, minmax(0, 1fr))` }"
          aria-label="主要导航"
        >
          <RouterLink to="/" :class="navClass(route.name === 'overview')">总览</RouterLink>
          <RouterLink
            v-for="board in navBoards"
            :key="board.platform"
            :to="navTo(board.id)"
            :class="navClass(currentChartPlatform === board.platform)"
          >
            {{ platformShortName(board.platform, charts.platforms) }}
          </RouterLink>
        </nav>
      </div>
    </header>
    <main id="main-content" class="mx-auto max-w-7xl px-4 py-4 md:py-6">
      <RouterView />
    </main>
    <PlayerBar v-if="player.current" />
  </div>
</template>
