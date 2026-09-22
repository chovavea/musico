<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch, nextTick } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import { isAbortError, searchTracks } from "./api";
import AppIcon from "./components/AppIcon.vue";
import PageStage from "./components/PageStage.vue";
import PlayerBar from "./components/PlayerBar.vue";
import SettingsMenu from "./components/SettingsMenu.vue";
import ComingSoonToast from "./components/ComingSoonToast.vue";
import GlazeLayout from "./layouts/GlazeLayout.vue";
import { platformLabel, platformShortName } from "./lib/boards";
import { useChartsStore } from "./stores/charts";
import { useHealthStore } from "./stores/health";
import { usePlayerStore } from "./stores/player";
import { usePageAmbient } from "./composables/usePageAmbient";
import { useSlidingPill } from "./composables/useSlidingPill";
import { useThemeStore } from "./stores/theme";
import type { SearchResult } from "./types";

const theme = useThemeStore();
usePageAmbient();

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
const suggestionsEl = ref<HTMLElement | null>(null);
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

const desktopNav = ref<HTMLElement | null>(null);
const mobileNav = ref<HTMLElement | null>(null);
const navActive = computed(() =>
  route.name === "overview" ? "overview" : currentChartPlatform.value,
);
const desktopPill = useSlidingPill(desktopNav, () => [navActive.value, navBoards.value.length]);
const mobilePill = useSlidingPill(mobileNav, () => [navActive.value, navBoards.value.length]);

function navClass(active: boolean): string {
  return [
    "type-title relative z-10 grid h-11 place-items-center rounded-full px-2 transition-colors duration-200 md:h-auto md:px-3 md:py-1.5",
    active
      ? "text-white dark:text-zinc-900"
      : "text-zinc-900 hover:bg-zinc-100/80 dark:text-zinc-100 dark:hover:bg-white/10",
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
  if (!query) {
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
  if (!searchQuery.value.trim()) {
    suggestions.value = [];
    suggestionsError.value = "";
    suggestionsLoading.value = false;
  }
}

function openSearchPanel() {
  searchOpen.value = true;
  void nextTick(() => {
    searchInput.value?.focus({ preventScroll: true });
  });
}

function toggleSearch() {
  if (searchOpen.value) {
    closeSearchPanel();
    restoreSearchTrigger();
    return;
  }
  openSearchPanel();
}

function onDocumentPointerDown(event: PointerEvent) {
  if (!searchOpen.value || !(event.target instanceof Element)) return;
  if (event.target.closest("[data-search-ui]")) return;
  closeSearchPanel();
}

function restoreSearchTrigger() {
  void nextTick(() => {
    searchTrigger.value?.focus({ preventScroll: true });
  });
}

function onDocumentKey(event: KeyboardEvent) {
  if (event.key === "Escape" && searchOpen.value) {
    closeSearchPanel();
    restoreSearchTrigger();
  }
}

function submitSearch() {
  const query = searchQuery.value.trim();
  if (!query) return;
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
    restoreSearchTrigger();
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
    if (!searchQuery.value.trim()) {
      suggestions.value = [];
      suggestionsError.value = "";
    }
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
  <div class="relative min-h-dvh">
    <Transition name="shell">
      <GlazeLayout v-if="theme.isGlaze" key="glaze" />
      <div v-else key="minimal" class="relative min-h-dvh" data-shell="minimal">
    <a
      href="#main-content"
      class="sr-only fixed left-4 top-4 z-[110] rounded-lg bg-white px-4 py-3 text-zinc-900 focus:not-sr-only"
    >
      跳到主要内容
    </a>
    <header
      class="sticky top-0 z-20 border-b border-zinc-200 bg-white/95 pt-[env(safe-area-inset-top,0px)] dark:border-white/10 dark:bg-zinc-950/95"
    >
      <div class="mx-auto grid max-w-7xl grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-2 px-4 py-2 md:py-3">
        <RouterLink to="/" class="flex min-h-11 items-center gap-2.5" aria-label="Musico 首页">
          <span
            class="grid h-10 w-10 place-items-center rounded-xl bg-zinc-900 text-white dark:bg-white dark:text-zinc-900"
          >
            <svg viewBox="0 0 24 24" fill="none" class="h-5 w-5" aria-hidden="true">
              <path d="M5 17V9.5" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" />
              <path d="M9.5 17v-4" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" />
              <path d="M14 17V7" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" />
              <path d="M18.5 17v-5.5" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" />
            </svg>
          </span>
          <span class="text-[1.25rem] font-bold leading-none tracking-[-0.03em]">musico</span>
        </RouterLink>

        <div class="flex min-w-0 items-center justify-end gap-1">
          <nav
            ref="desktopNav"
            class="relative hidden max-w-full items-center overflow-x-auto md:flex"
            aria-label="主要导航"
          >
            <span class="nav-pill nav-pill-ink" :style="desktopPill" aria-hidden="true" />
            <RouterLink
              to="/"
              :data-nav-on="route.name === 'overview'"
              :class="navClass(route.name === 'overview')"
            >
              总览
            </RouterLink>
            <RouterLink
              v-for="board in navBoards"
              :key="board.platform"
              :to="navTo(board.id)"
              :data-nav-on="currentChartPlatform === board.platform"
              :class="navClass(currentChartPlatform === board.platform)"
            >
              {{ platformShortName(board.platform, charts.platforms) }}
            </RouterLink>
          </nav>
          <div
            ref="searchRoot"
            data-search-ui
            class="relative flex min-w-0 flex-1 items-center justify-end"
          >
            <form
              v-if="searchOpen"
              class="min-w-0 w-full"
              @submit.prevent="submitSearch"
            >
              <label class="sr-only" for="global-search">搜索歌曲</label>
              <input
                id="global-search"
                ref="searchInput"
                v-model="searchQuery"
                type="search"
                autocomplete="off"
                enterkeyhint="search"
                placeholder="搜索歌曲"
                class="h-8 w-full appearance-none rounded-full bg-zinc-100 px-3 text-[16px] leading-8 outline-none ring-1 ring-zinc-200/70 transition placeholder:text-zinc-400 focus:bg-white focus:ring-zinc-300 dark:bg-zinc-800 dark:ring-white/10 dark:focus:bg-zinc-800 dark:focus:ring-white/20"
                @input="scheduleSuggestionSearch"
                @keydown="onSearchKeydown"
              />
            </form>
            <button
              ref="searchTrigger"
              type="button"
              class="search-trigger grid h-11 w-11 shrink-0 place-items-center rounded-full text-zinc-500 transition hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-white"
              :class="searchOpen ? 'text-zinc-900 dark:text-white' : ''"
              :aria-expanded="searchOpen"
              aria-controls="global-search-suggestions"
              aria-label="搜索"
              @click.stop="toggleSearch()"
            >
              <AppIcon name="search" :size="24" />
            </button>
          </div>
          <SettingsMenu />
        </div>

        <nav
          ref="mobileNav"
          class="relative col-span-2 flex gap-1 overflow-x-auto rounded-full bg-zinc-200/80 p-1 text-zinc-700 md:hidden dark:bg-zinc-800 dark:text-zinc-200"
          aria-label="主要导航"
        >
          <span class="nav-pill nav-pill-ink" :style="mobilePill" aria-hidden="true" />
          <RouterLink
            to="/"
            class="min-w-fit flex-1"
            :data-nav-on="route.name === 'overview'"
            :class="navClass(route.name === 'overview')"
          >
            总览
          </RouterLink>
          <RouterLink
            v-for="board in navBoards"
            :key="board.platform"
            class="min-w-fit flex-1"
            :to="navTo(board.id)"
            :data-nav-on="currentChartPlatform === board.platform"
            :class="navClass(currentChartPlatform === board.platform)"
          >
            {{ platformShortName(board.platform, charts.platforms) }}
          </RouterLink>
        </nav>
      </div>
      <div
        v-if="searchOpen && (suggestionsLoading || suggestionsError || suggestions.length || searchQuery.trim().length >= 1)"
        id="global-search-suggestions"
        ref="suggestionsEl"
        data-search-ui
        class="absolute right-4 top-full z-30 mt-1.5 w-[min(16.5rem,calc(100vw-2rem))] overflow-hidden rounded-xl bg-white shadow-lg ring-1 ring-zinc-200/80 dark:bg-zinc-900 dark:ring-white/10"
        @pointerdown.stop
      >
        <div class="max-h-64 overflow-y-auto">
          <div v-if="suggestionsLoading" class="px-3 py-2.5 text-sm text-zinc-500">
            正在搜索…
          </div>
          <div v-else-if="suggestionsError" class="px-3 py-2.5 text-sm text-rose-600 dark:text-rose-300">
            {{ suggestionsError }}，按 Enter 仍可查看全部结果
          </div>
          <template v-else-if="suggestions.length">
            <button
              v-for="(result, index) in suggestions"
              :key="`${result.platform}:${result.external_id}`"
              type="button"
              class="flex w-full items-center gap-2 px-3 py-2 text-left transition hover:bg-zinc-50 dark:hover:bg-white/5"
              :class="activeSuggestion === index ? 'bg-zinc-50 dark:bg-white/5' : ''"
              @click="chooseSuggestion(result)"
            >
              <div class="min-w-0 flex-1">
                <div class="type-title truncate">{{ result.title }}</div>
                <div class="truncate text-[0.74rem] text-artist">
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
              class="w-full border-t border-zinc-100 px-3 py-2.5 text-left text-sm text-zinc-500 hover:bg-zinc-50 dark:border-white/5 dark:text-zinc-400 dark:hover:bg-white/5"
              @click="submitSearch"
            >
              查看全部结果
            </button>
          </template>
          <div v-else class="px-3 py-2.5 text-sm text-zinc-500">
            暂无匹配歌曲，按 Enter 查看结果
          </div>
        </div>
      </div>
    </header>
    <main
      id="main-content"
      class="page-stage mx-auto max-w-7xl px-4 pt-4 md:pt-6"
      :class="
        player.current
          ? 'pb-[calc(var(--player-bar-h,5.5rem)+1rem)] md:pb-[calc(var(--player-bar-h,5.5rem)+1.5rem)]'
          : 'pb-4 md:pb-6'
      "
    >
      <PageStage />
    </main>
    <PlayerBar v-if="player.current" />
    <ComingSoonToast />
      </div>
    </Transition>
  </div>
</template>
