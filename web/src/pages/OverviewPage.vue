<script setup lang="ts">
import { computed, ref } from "vue";
import BoardColumn from "../components/BoardColumn.vue";
import HeroCard from "../components/HeroCard.vue";
import GlazeHome from "./GlazeHome.vue";
import { useOverviewColumns } from "../composables/useOverviewColumns";
import { useSlidingPill } from "../composables/useSlidingPill";
import { platformShortName } from "../lib/boards";
import { todayLabel } from "../lib/format";
import { useThemeStore } from "../stores/theme";

const theme = useThemeStore();
const { store, tab, columns, setKey, groupsOf } = useOverviewColumns();
const tabNav = ref<HTMLElement | null>(null);
const activeColumn = computed(() => columns.value[tab.value]);
const tabPill = useSlidingPill(tabNav, () => [tab.value, columns.value.length]);
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
      <p class="text-[0.72rem] tracking-[0.08em] text-secondary">{{ todayLabel() }}</p>
      <h1 data-page-heading tabindex="-1" class="mt-1 text-[1.35rem] font-extrabold leading-[1.15] tracking-[0.02em] outline-none md:text-[1.5rem]">今日榜单</h1>
    </section>

    <div
      ref="tabNav"
      class="relative mb-4 flex gap-1 overflow-x-auto rounded-full bg-zinc-200/80 p-1 md:hidden dark:bg-zinc-800"
    >
      <span class="nav-pill nav-pill-surface" :style="tabPill" aria-hidden="true" />
      <button
        v-for="(column, index) in columns"
        :key="column.source.id"
        type="button"
        class="type-title relative z-10 grid h-11 min-w-24 flex-1 place-items-center rounded-full px-3"
        :data-nav-on="tab === index"
        :aria-pressed="tab === index"
        @click="tab = index"
      >
        {{ platformShortName(column.board.platform, store.platforms) }}
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

    <div class="hidden gap-4 md:grid md:grid-cols-2 lg:grid-cols-3">
      <HeroCard
        v-for="column in columns"
        :key="`hero:${column.source.id}`"
        :board="column.board"
        :latest="column.latest"
      />
    </div>

    <div class="mt-6 hidden gap-8 md:grid md:grid-cols-2 lg:grid-cols-3">
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
