<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import AppIcon from "../components/AppIcon.vue";
import CoverImage from "../components/CoverImage.vue";
import PageHeader from "../components/PageHeader.vue";
import { useStalePoll } from "../composables/useStalePoll";
import { boardTypeLabel, platformLabel, sortedBoards } from "../lib/boards";
import { formatUpdatedAt } from "../lib/format";
import { useChartsStore } from "../stores/charts";
import type { BoardInfo } from "../types";

const store = useChartsStore();
useStalePoll();
const movingId = ref("");

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

async function move(id: string, direction: "up" | "down") {
  if (movingId.value) return;
  movingId.value = id;
  try {
    await store.moveBoard(id, direction);
  } finally {
    movingId.value = "";
  }
}

onMounted(() => {
  void store.refreshAll();
});
</script>

<template>
  <div>
    <PageHeader
      title="榜单管理"
      eyebrow="目录"
      description="调整榜单展示顺序，修改会自动保存。点击名称可进入单榜页面。"
      back-to="/"
    >
      <template #meta>
        <p class="mt-2 text-sm text-secondary">共 {{ boards.length }} 张</p>
      </template>
    </PageHeader>

    <p v-if="store.error" role="alert" class="mb-4 text-sm text-rose-600 dark:text-rose-300">{{ store.error }}</p>

    <div
      v-if="boards.length"
      class="overflow-hidden rounded-2xl bg-white ring-1 ring-zinc-200/80 dark:bg-zinc-900 dark:ring-white/10"
    >
      <div
        v-for="(board, index) in boards"
        :key="board.id"
        class="grid min-h-11 grid-cols-[2.75rem_minmax(0,1fr)_auto] items-center gap-3 border-t border-zinc-100 px-4 py-3 first:border-t-0 dark:border-white/5"
      >
        <CoverImage
          :src="coverOf(board) ?? ''"
          :size="150"
          :alt="board.name"
          class="h-11 w-11 rounded-xl object-cover"
        />
        <RouterLink :to="`/charts/${board.id}`" class="min-w-0 hover:underline">
          <p class="truncate font-semibold">{{ board.name }}</p>
          <p class="truncate text-xs text-secondary">
            {{ platformLabel(board.platform) }} · {{ boardTypeLabel(board.type) }} ·
            {{ countOf(board) }} 首 · {{ updatedOf(board) }}
          </p>
        </RouterLink>
        <div class="flex shrink-0 items-center gap-1">
          <button
            type="button"
            class="grid h-11 w-11 place-items-center rounded-full text-sm hover:bg-zinc-100 disabled:text-zinc-300 dark:hover:bg-white/10 dark:disabled:text-zinc-700"
            :disabled="index === 0 || Boolean(movingId)"
            aria-label="上移"
            @click="move(board.id, 'up')"
          >
            <AppIcon :name="movingId === board.id ? 'spinner' : 'chevron-up'" :size="18" />
          </button>
          <button
            type="button"
            class="grid h-11 w-11 place-items-center rounded-full text-sm hover:bg-zinc-100 disabled:text-zinc-300 dark:hover:bg-white/10 dark:disabled:text-zinc-700"
            :disabled="index === boards.length - 1 || Boolean(movingId)"
            aria-label="下移"
            @click="move(board.id, 'down')"
          >
            <AppIcon :name="movingId === board.id ? 'spinner' : 'chevron-down'" :size="18" />
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
