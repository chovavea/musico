<script setup lang="ts">
import { computed } from "vue";
import BoardColumn from "../components/BoardColumn.vue";
import HeroCard from "../components/HeroCard.vue";
import PlatformMark from "../components/PlatformMark.vue";
import GlazeHome from "./GlazeHome.vue";
import { useOverviewColumns } from "../composables/useOverviewColumns";
import { platformShortName } from "../lib/boards";
import { todayLabel } from "../lib/format";
import { useThemeStore } from "../stores/theme";

const theme = useThemeStore();
const { store, tab, columns, setKey, groupsOf } = useOverviewColumns();
const activeColumn = computed(() => columns.value[tab.value]);
</script>

<template>
  <GlazeHome
    v-if="theme.isGlaze"
    :columns="columns"
    :error="store.error"
    @retry="store.refreshAll()"
  />
  <div v-else>
    <section class="mb-6">
      <p class="text-[0.72rem] font-medium text-tertiary">{{ todayLabel() }}</p>
      <h1 data-page-heading tabindex="-1" class="mt-1 text-[1.35rem] font-bold leading-[1.2] outline-none md:text-[1.5rem]">今日榜单</h1>
    </section>

    <div
      class="mb-4 flex w-full gap-1 [scrollbar-width:none] md:hidden [&::-webkit-scrollbar]:hidden"
      role="tablist"
      aria-label="平台"
    >
      <button
        v-for="(column, index) in columns"
        :key="column.source.id"
        type="button"
        role="tab"
        class="inline-flex h-9 min-w-0 flex-1 items-center justify-center gap-1 overflow-hidden rounded-full px-2 text-[0.78rem] leading-none"
        :class="
          tab === index
            ? 'bg-zinc-900 font-medium text-white dark:bg-zinc-100 dark:text-zinc-900'
            : 'bg-zinc-100 font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300'
        "
        :aria-selected="tab === index"
        @click="tab = index"
      >
        <PlatformMark :platform="column.board.platform" :size="16" />
        <span class="min-w-0 truncate">{{ platformShortName(column.board.platform, store.platforms) }}</span>
      </button>
    </div>

    <div class="relative md:hidden">
      <Transition name="page">
        <div v-if="activeColumn" :key="activeColumn.source.id">
          <HeroCard class="mb-4" :board="activeColumn.board" :latest="activeColumn.latest" />
          <BoardColumn
            :board="activeColumn.board"
            :latest="activeColumn.latest"
            :show-hero="false"
            :picker-groups="groupsOf(store.catalog, activeColumn.board.platform)"
            @pick="setKey(activeColumn.source.id, $event)"
            @reorder="(key, beforeKey) => store.reorderCatalogChart(activeColumn.board.platform, key, beforeKey)"
          />
        </div>
      </Transition>
    </div>

    <div class="tile-grid gap-4">
      <HeroCard
        v-for="column in columns"
        :key="`hero:${column.source.id}`"
        :board="column.board"
        :latest="column.latest"
      />
    </div>

    <div class="tile-grid mt-6 gap-8">
      <BoardColumn
        v-for="column in columns"
        :key="`list:${column.source.id}`"
        :board="column.board"
        :latest="column.latest"
        :show-hero="false"
        :picker-groups="groupsOf(store.catalog, column.board.platform)"
        @pick="setKey(column.source.id, $event)"
        @reorder="(key, beforeKey) => store.reorderCatalogChart(column.board.platform, key, beforeKey)"
      />
    </div>

    <div
      v-if="store.error"
      class="mt-6 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-600 ring-1 ring-zinc-200 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-500/20"
    >
      <div class="flex items-center justify-between gap-3">
        <p>{{ store.error }}</p>
        <button type="button" class="underline" @click="store.refreshAll()">重试</button>
      </div>
    </div>
  </div>
</template>
