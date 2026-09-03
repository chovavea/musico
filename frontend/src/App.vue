<script setup lang="ts">
import { computed, onMounted, onUnmounted } from "vue";
import { RouterLink, RouterView, useRoute } from "vue-router";
import PlayerBar from "./components/PlayerBar.vue";
import SettingsMenu from "./components/SettingsMenu.vue";
import { defaultBoardForPlatform } from "./lib/boards";
import { useChartsStore } from "./stores/charts";
import { useHealthStore } from "./stores/health";

const route = useRoute();
const charts = useChartsStore();
const health = useHealthStore();

const qqBoard = computed(() => defaultBoardForPlatform(charts.boards, "qqmusic"));
const neteaseBoard = computed(() => defaultBoardForPlatform(charts.boards, "netease"));
const qqTo = computed(() => `/charts/${qqBoard.value?.id ?? "qq_hot"}`);
const neteaseTo = computed(() => `/charts/${neteaseBoard.value?.id ?? "netease_hot"}`);

const currentChartPlatform = computed(() => {
  if (route.name !== "chart") return "";
  const id = String(route.params.board ?? "");
  const fromStore = charts.boards.find((item) => item.id === id)?.platform;
  if (fromStore) return fromStore;
  if (id === qqBoard.value?.id || id === "qq_hot") return "qqmusic";
  if (id === neteaseBoard.value?.id || id === "netease_hot") return "netease";
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

let pollTimer = 0;
onMounted(() => {
  if (!charts.boards.length) {
    void charts.loadBoards();
  }
  void health.refresh();
  pollTimer = window.setInterval(() => {
    void health.refresh();
  }, 60_000);
});
onUnmounted(() => window.clearInterval(pollTimer));
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
        <nav
          class="grid grid-cols-3 gap-1 rounded-full bg-zinc-200/80 p-1 text-zinc-600 md:ml-auto md:flex md:items-center md:bg-transparent md:p-0 dark:bg-zinc-800 md:dark:bg-transparent"
        >
          <RouterLink to="/" :class="navClass(route.name === 'overview')">总览</RouterLink>
          <RouterLink :to="qqTo" :class="navClass(currentChartPlatform === 'qqmusic')">
            QQ
          </RouterLink>
          <RouterLink :to="neteaseTo" :class="navClass(currentChartPlatform === 'netease')">
            网易
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
