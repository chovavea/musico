<script setup lang="ts">
import { computed } from "vue";
import { useCoverPalette } from "../composables/useCoverTint";
import { chartShortName, platformLabel } from "../lib/boards";
import { usePlayerStore } from "../stores/player";
import type { BoardInfo, LatestBoard, RankItem } from "../types";
import CoverImage from "./CoverImage.vue";
import TrackDownloadAction from "./TrackDownloadAction.vue";

const props = defineProps<{ board: BoardInfo; latest?: LatestBoard }>();
const player = usePlayerStore();

const topFive = computed(() => props.latest?.items.slice(0, 5) ?? []);
const top = computed(() => topFive.value[0]);
const coverUrl = computed(() => top.value?.cover_url ?? null);
const palette = useCoverPalette(coverUrl);

function rankKlass(rank: number): string {
  if (rank === 1) return "text-amber-800 dark:text-amber-300";
  if (rank === 2) return "text-zinc-700 dark:text-zinc-300";
  if (rank === 3) return "text-amber-700 dark:text-amber-400";
  return "text-zinc-600 dark:text-zinc-300";
}

function isCurrent(item: RankItem): boolean {
  return (
    player.current?.platform === item.platform &&
    player.current?.external_id === item.external_id
  );
}

function onPlay(item?: RankItem) {
  if (item) {
    player.play(item, props.latest?.items ?? topFive.value);
  }
}

</script>

<template>
  <article
    class="relative overflow-hidden rounded-2xl"
    :style="{
      backgroundColor: palette.bg,
      '--hero-hover': palette.hover,
      '--hero-active': palette.active,
    }"
  >
    <div aria-hidden="true" class="pointer-events-none absolute inset-0">
      <CoverImage
        v-if="coverUrl"
        :src="coverUrl"
        :size="500"
        eager
        alt=""
        class="h-full w-full scale-[1.8] object-cover blur-3xl saturate-125"
      />
      <div class="absolute inset-0" :style="{ backgroundColor: palette.overlay }" />
    </div>
    <div class="relative flex flex-row gap-3 p-4 sm:gap-4">
      <button
        type="button"
        class="relative h-24 w-24 shrink-0 overflow-hidden rounded-xl sm:h-32 sm:w-32 sm:rounded-2xl md:h-36 md:w-36"
        :style="{ backgroundColor: palette.bg }"
        :disabled="!top"
        :aria-label="top ? `播放 ${top.title} · ${top.artist}` : undefined"
        @click="onPlay(top)"
      >
        <CoverImage
          v-if="top"
          :src="top.cover_url"
          :size="500"
          eager
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
          <span class="truncate text-zinc-700 dark:text-zinc-300">{{ chartShortName(board.name) }}</span>
          <span class="shrink-0 text-zinc-700 dark:text-zinc-300">Top 5</span>
          <span
            v-if="latest?.staleness === 'stale'"
            class="rounded-full bg-amber-400/20 px-2 py-0.5 text-amber-700 dark:text-amber-300"
          >
            可能过期
          </span>
        </div>
        <ol v-if="topFive.length" class="mt-3 space-y-1">
          <li v-for="item in topFive" :key="item.external_id">
            <div
              class="group relative grid min-h-11 w-full grid-cols-[1.5rem_minmax(0,1fr)_auto] items-center gap-2 rounded-xl px-1.5 py-1.5 text-left hover:bg-[var(--hero-hover)]"
              :class="isCurrent(item) ? 'bg-[var(--hero-active)]' : ''"
            >
              <button
                type="button"
                class="absolute inset-0 z-0 rounded-xl focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-zinc-400 dark:focus-visible:outline-zinc-600"
                :aria-label="`播放 ${item.title} · ${item.artist}`"
                @click="onPlay(item)"
              />
              <span class="pointer-events-none tabular text-right text-sm font-semibold" :class="rankKlass(item.rank)">
                {{ item.rank }}
              </span>
              <span class="pointer-events-none min-w-0">
                <span class="block truncate text-sm font-medium">{{ item.title }}</span>
                <span class="block truncate text-xs text-zinc-700 dark:text-zinc-300">
                  {{ item.artist }}
                </span>
              </span>
              <span class="relative z-10 pointer-events-auto">
                <TrackDownloadAction :item="item" subtle />
              </span>
            </div>
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
      </div>
    </div>
  </article>
</template>
