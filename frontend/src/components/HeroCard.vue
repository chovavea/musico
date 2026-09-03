<script setup lang="ts">
import { computed } from "vue";
import { useCoverPalette } from "../composables/useCoverTint";
import { chartShortName, platformLabel } from "../lib/boards";
import { formatUpdatedAt } from "../lib/format";
import { usePlayerStore } from "../stores/player";
import type { BoardInfo, LatestBoard, RankItem } from "../types";

const props = defineProps<{ board: BoardInfo; latest?: LatestBoard }>();
const player = usePlayerStore();

const topFive = computed(() => props.latest?.items.slice(0, 5) ?? []);
const top = computed(() => topFive.value[0]);
const coverUrl = computed(() => top.value?.cover_url ?? null);
const palette = useCoverPalette(coverUrl);

function rankKlass(rank: number): string {
  if (rank === 1) return "text-amber-500";
  if (rank === 2) return "text-zinc-400";
  if (rank === 3) return "text-amber-700 dark:text-amber-600";
  return "text-zinc-500";
}

function onPlay(item?: RankItem) {
  if (item) {
    player.play(item, props.latest?.items ?? topFive.value);
  }
}
</script>

<template>
  <article
    class="relative overflow-hidden rounded-3xl"
    :style="{
      backgroundColor: palette.bg,
      '--hero-hover': palette.hover,
      '--hero-active': palette.active,
    }"
  >
    <div aria-hidden="true" class="pointer-events-none absolute inset-0">
      <img
        v-if="coverUrl"
        :src="coverUrl"
        alt=""
        referrerpolicy="no-referrer"
        class="h-full w-full scale-[1.8] object-cover blur-3xl saturate-125"
      />
      <div class="absolute inset-0" :style="{ backgroundColor: palette.overlay }" />
    </div>
    <div class="relative flex flex-row gap-3 p-4 sm:gap-4 sm:p-6">
      <button
        type="button"
        class="relative h-28 w-28 shrink-0 overflow-hidden rounded-2xl shadow-lg sm:h-36 sm:w-36 sm:rounded-3xl md:h-44 md:w-44"
        :style="{ backgroundColor: palette.bg }"
        :disabled="!top"
        @click="onPlay(top)"
      >
        <img
          v-if="top?.cover_url"
          :src="top.cover_url"
          class="h-full w-full object-cover transition duration-200 hover:-translate-y-0.5"
          :alt="top.title"
        />
        <div v-else class="skel h-full w-full" />
      </button>
      <div class="flex min-w-0 flex-1 flex-col">
        <div class="flex flex-wrap items-center gap-2 text-xs">
          <span
            class="rounded-full px-2 py-0.5 font-medium"
            :style="{ backgroundColor: palette.chipBg, color: palette.chipFg }"
          >
            {{ platformLabel(board.platform) }}
          </span>
          <span class="truncate text-zinc-600 dark:text-zinc-400">{{ chartShortName(board.name) }}</span>
          <span class="shrink-0 text-zinc-600 dark:text-zinc-400">Top 5</span>
          <span
            v-if="latest?.staleness === 'stale'"
            class="rounded-full bg-amber-400/20 px-2 py-0.5 text-amber-700 dark:text-amber-300"
          >
            可能过期
          </span>
        </div>
        <ol v-if="topFive.length" class="mt-3 space-y-1">
          <li v-for="item in topFive" :key="item.external_id">
            <button
              type="button"
              class="grid min-h-11 w-full grid-cols-[1.5rem_minmax(0,1fr)_auto] items-center gap-2 rounded-xl px-1.5 py-1.5 text-left hover:bg-[var(--hero-hover)]"
              :class="
                player.current?.platform === item.platform &&
                player.current?.external_id === item.external_id
                  ? 'bg-[var(--hero-active)]'
                  : ''
              "
              @click="onPlay(item)"
            >
              <span class="tabular text-right text-sm font-semibold" :class="rankKlass(item.rank)">
                {{ item.rank }}
              </span>
              <span class="min-w-0">
                <span class="block truncate text-sm font-medium">{{ item.title }}</span>
                <span class="block truncate text-xs text-zinc-500 dark:text-zinc-400">
                  {{ item.artist }}
                </span>
              </span>
              <span class="text-xs text-zinc-500">试听</span>
            </button>
          </li>
        </ol>
        <div v-else class="mt-3 space-y-2">
          <div v-for="n in 5" :key="n" class="flex items-center gap-2">
            <div class="skel h-3 w-4" />
            <div class="flex-1 space-y-1">
              <div class="skel h-3 w-3/4" />
              <div class="skel h-2 w-1/3" />
            </div>
          </div>
        </div>
        <p class="mt-3 text-xs text-zinc-500">
          {{ formatUpdatedAt(latest?.fetched_at ?? latest?.updated_at) }}
          · {{ latest?.items.length ?? 0 }} 首
        </p>
      </div>
    </div>
  </article>
</template>
