<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import GlazeHero from "../components/GlazeHero.vue";
import GlazeTrackRow from "../components/GlazeTrackRow.vue";
import PlatformMark from "../components/PlatformMark.vue";
import AppIcon from "../components/AppIcon.vue";
import type { OverviewColumn } from "../composables/useOverviewColumns";
import { comingSoon } from "../lib/coming-soon";
import { chartShortName, platformLabel, platformShortName } from "../lib/boards";
import { useChartsStore } from "../stores/charts";
import type { RankItem } from "../types";

const DESKTOP_TRACKS = 10;

const props = defineProps<{
  columns: OverviewColumn[];
  error?: string;
}>();

const emit = defineEmits<{
  retry: [];
}>();

const router = useRouter();
const charts = useChartsStore();
const platformTab = ref("");
const query = ref("");

const visibleColumns = computed(() => {
  if (!platformTab.value) return props.columns;
  return props.columns.filter((column) => column.board.platform === platformTab.value);
});

function tracksOf(column: OverviewColumn): RankItem[] {
  return column.latest?.items.slice(0, DESKTOP_TRACKS) ?? [];
}

function boardTitle(column: OverviewColumn): string {
  return `${platformLabel(column.board.platform)} ${chartShortName(column.board.name)}`;
}

function submitSearch() {
  const value = query.value.trim();
  if (!value) return;
  void router.push({ name: "search", query: { q: value } });
}

function more(column?: OverviewColumn) {
  const board = column?.board ?? visibleColumns.value[0]?.board;
  if (board) void router.push(`/charts/${encodeURIComponent(board.id)}`);
}
</script>

<template>
  <section>
    <h1 data-page-heading tabindex="-1" class="sr-only outline-none">musico 首页</h1>
    <div class="gz-tabs" role="tablist" aria-label="平台">
      <button
        type="button"
        class="gz-tab"
        :class="platformTab === '' ? 'is-on' : ''"
        role="tab"
        :aria-selected="platformTab === ''"
        @click="platformTab = ''"
      >
        <AppIcon name="waveform" :size="15" />
        总览
      </button>
      <button
        v-for="column in columns"
        :key="column.source.id"
        type="button"
        class="gz-tab"
        :class="platformTab === column.board.platform ? 'is-on' : ''"
        role="tab"
        :aria-selected="platformTab === column.board.platform"
        @click="platformTab = column.board.platform"
      >
        <PlatformMark :platform="column.board.platform" :size="16" />
        {{ platformShortName(column.board.platform, charts.platforms) }}
      </button>
    </div>

    <form class="gz-search" @submit.prevent="submitSearch">
      <AppIcon name="search" :size="16" />
      <label class="sr-only" for="gz-search">搜索歌曲</label>
      <input
        id="gz-search"
        v-model="query"
        type="search"
        autocomplete="off"
        enterkeyhint="search"
        placeholder="搜索歌曲、歌手、专辑"
      />
      <button
        type="button"
        class="gz-ghost"
        aria-label="随机播放"
        @click="comingSoon('随机播放')"
      >
        <AppIcon name="shuffle" :size="16" />
      </button>
    </form>

    <GlazeHero :columns="visibleColumns" />

    <div class="relative">
    <Transition name="page">
      <div :key="platformTab || 'all'" class="gz-home-boards">
      <template v-if="!visibleColumns.length">
        <div v-for="n in 3" :key="`board-skel-${n}`" class="space-y-2 py-4">
          <div class="skel h-8 w-40 rounded-full" />
          <div v-for="row in 6" :key="row" class="skel h-14 rounded-2xl" />
        </div>
      </template>
      <section
        v-for="(column, index) in visibleColumns"
        :key="column.source.id"
        class="gz-home-board"
        :class="{ 'is-extra': index > 0 }"
      >
        <div class="gz-section">
          <h2 class="gz-section-title">
            <PlatformMark :platform="column.board.platform" :size="16" />
            <span class="truncate">{{ boardTitle(column) }}</span>
          </h2>
          <button type="button" class="gz-more" @click="more(column)">
            更多
            <AppIcon name="chevron-right" :size="14" />
          </button>
        </div>
        <div class="gz-tracks">
          <GlazeTrackRow
            v-for="(item, index) in tracksOf(column)"
            :key="item.external_id"
            :item="item"
            :queue="column.latest?.items"
            :hit="index === 0"
          />
          <div v-if="!tracksOf(column).length" class="space-y-2 px-1 py-2">
            <div v-for="n in 6" :key="n" class="skel h-14 rounded-2xl" />
          </div>
        </div>
      </section>
    </div>
    </Transition>
    </div>

    <div
      v-if="error"
      class="mt-4 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-600 ring-1 ring-rose-200 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-500/20"
    >
      <div class="flex items-center justify-between gap-3">
        <p>{{ error }}</p>
        <button type="button" class="underline" @click="emit('retry')">重试</button>
      </div>
    </div>
  </section>
</template>
