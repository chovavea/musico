<script setup lang="ts">
import { computed, onMounted, watch } from "vue";
import { RouterLink } from "vue-router";
import BoardColumn from "../components/BoardColumn.vue";
import { useStalePoll } from "../composables/useStalePoll";
import { boardTypeLabel } from "../lib/boards";
import { formatUpdatedAt, risingCount } from "../lib/format";
import { useChartsStore } from "../stores/charts";

const props = defineProps<{ board: string }>();
const store = useChartsStore();
useStalePoll();

const current = computed(() => store.boards.find((item) => item.id === props.board));
const latest = computed(() => store.latest[props.board]);
const items = computed(() => latest.value?.items ?? []);
const siblings = computed(() => {
  if (!current.value) return [];
  return store.boards.filter((item) => item.platform === current.value?.platform);
});

async function load() {
  await store.loadBoards();
  await store.refreshLatest(props.board);
}

onMounted(() => {
  void load();
});
watch(
  () => props.board,
  () => {
    void load();
  },
);
</script>

<template>
  <div>
    <section class="mb-6">
      <RouterLink
        to="/"
        class="inline-flex min-h-11 items-center text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-white"
      >
        ← 返回总览
      </RouterLink>
      <h1 class="mt-1 text-2xl font-semibold tracking-tight md:text-3xl">
        {{ current?.name ?? "榜单" }}
      </h1>
      <p class="mt-2 text-sm text-zinc-500">
        {{ items.length }} 首 · 升 {{ risingCount(items) }}
        · {{ formatUpdatedAt(latest?.fetched_at ?? latest?.updated_at) }}
        · 分数只在本榜内归一化
      </p>
      <div
        v-if="siblings.length > 1"
        class="mt-4 flex gap-1 overflow-x-auto rounded-full bg-zinc-200/80 p-1 dark:bg-zinc-800"
      >
        <RouterLink
          v-for="item in siblings"
          :key="item.id"
          :to="`/charts/${item.id}`"
          class="grid h-11 min-w-[4.5rem] flex-1 place-items-center whitespace-nowrap rounded-full px-3 text-sm"
          :class="
            item.id === props.board
              ? 'bg-white shadow-sm dark:bg-zinc-950'
              : 'text-zinc-500'
          "
        >
          {{ boardTypeLabel(item.type) }}
        </RouterLink>
      </div>
    </section>
    <BoardColumn
      v-if="current"
      :board="current"
      :latest="latest"
      :link-to-chart="false"
    />
    <p v-else class="rounded-2xl bg-white p-6 text-zinc-500 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-white/10">
      未找到该榜
    </p>
  </div>
</template>
