<script setup lang="ts">
import { computed, onMounted } from "vue";
import { RouterLink } from "vue-router";
import { useStalePoll } from "../composables/useStalePoll";
import { boardTypeLabel, platformLabel, sortedBoards } from "../lib/boards";
import { formatUpdatedAt } from "../lib/format";
import { useChartsStore } from "../stores/charts";
import type { BoardInfo } from "../types";

const store = useChartsStore();
useStalePoll();

const boards = computed(() => sortedBoards(store.boards));

function coverOf(board: BoardInfo): string | null {
  return store.latest[board.id]?.items[0]?.cover_url ?? null;
}

function countOf(board: BoardInfo): number {
  return store.latest[board.id]?.items.length ?? 0;
}

function updatedOf(board: BoardInfo): string {
  const latest = store.latest[board.id];
  return formatUpdatedAt(latest?.fetched_at ?? latest?.updated_at);
}

function move(id: string, direction: "up" | "down") {
  void store.moveBoard(id, direction);
}

onMounted(() => {
  void store.refreshAll();
});
</script>

<template>
  <div>
    <section class="mb-6">
      <p class="text-sm text-zinc-500">目录</p>
      <h1 class="mt-1 text-2xl font-semibold tracking-tight md:text-3xl">榜单</h1>
      <p class="mt-2 max-w-xl text-sm text-zinc-500">
        右侧上移下移调整顺序，会保存到数据库。点名称仍进入单榜页。
      </p>
      <p class="mt-2 text-sm text-zinc-500">共 {{ boards.length }} 张</p>
    </section>

    <p v-if="store.error" class="mb-4 text-sm text-rose-500">{{ store.error }}</p>

    <div
      v-if="boards.length"
      class="overflow-hidden rounded-2xl bg-white ring-1 ring-zinc-200/80 dark:bg-zinc-900 dark:ring-white/10"
    >
      <div
        v-for="(board, index) in boards"
        :key="board.id"
        class="grid min-h-11 grid-cols-[2.75rem_minmax(0,1fr)_auto] items-center gap-3 border-t border-zinc-100 px-4 py-3 first:border-t-0 dark:border-white/5"
      >
        <img
          v-if="coverOf(board)"
          :src="coverOf(board) ?? ''"
          :alt="board.name"
          class="h-11 w-11 rounded-xl object-cover"
        />
        <div v-else class="skel h-11 w-11 rounded-xl" />
        <RouterLink :to="`/charts/${board.id}`" class="min-w-0 hover:underline">
          <p class="truncate font-semibold">{{ board.name }}</p>
          <p class="truncate text-xs text-zinc-500">
            {{ platformLabel(board.platform) }} · {{ boardTypeLabel(board.type) }} ·
            {{ countOf(board) }} 首 · {{ updatedOf(board) }}
          </p>
        </RouterLink>
        <div class="flex shrink-0 items-center gap-1">
          <button
            type="button"
            class="grid h-11 w-11 place-items-center rounded-full text-sm hover:bg-zinc-100 disabled:text-zinc-300 dark:hover:bg-white/10 dark:disabled:text-zinc-700"
            :disabled="index === 0"
            aria-label="上移"
            @click="move(board.id, 'up')"
          >
            ↑
          </button>
          <button
            type="button"
            class="grid h-11 w-11 place-items-center rounded-full text-sm hover:bg-zinc-100 disabled:text-zinc-300 dark:hover:bg-white/10 dark:disabled:text-zinc-700"
            :disabled="index === boards.length - 1"
            aria-label="下移"
            @click="move(board.id, 'down')"
          >
            ↓
          </button>
        </div>
      </div>
    </div>

    <div
      v-if="store.loading && !boards.length"
      class="overflow-hidden rounded-2xl bg-white p-4 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-white/10"
    >
      <div v-for="n in 4" :key="n" class="flex items-center gap-3 py-2">
        <div class="skel h-11 w-11 rounded-xl" />
        <div class="flex-1 space-y-2">
          <div class="skel h-3 w-1/3" />
          <div class="skel h-3 w-1/2" />
        </div>
      </div>
    </div>
  </div>
</template>
