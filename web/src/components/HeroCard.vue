<script setup lang="ts">
import { computed } from "vue";
import { useCoverPalette } from "../composables/useCoverTint";
import { chartShortName, platformLabel } from "../lib/boards";
import { usePlayerStore } from "../stores/player";
import { useThemeStore } from "../stores/theme";
import type { BoardInfo, LatestBoard, RankItem } from "../types";
import CoverImage from "./CoverImage.vue";
import TrackDownloadAction from "./TrackDownloadAction.vue";

const props = defineProps<{ board: BoardInfo; latest?: LatestBoard }>();
const player = usePlayerStore();
const theme = useThemeStore();

const topFive = computed(() => props.latest?.items.slice(0, 5) ?? []);
const top = computed(() => topFive.value[0]);
const followAmbient = computed(() => theme.isPulse && !theme.dark);
const washCoverUrl = computed(() => {
  if (followAmbient.value) {
    const playing = player.current?.cover_url?.trim();
    if (playing) return playing;
  }
  return top.value?.cover_url ?? null;
});
const featured = computed(() => {
  if (!followAmbient.value) return top.value;
  const current = player.current;
  if (
    current &&
    topFive.value.some(
      (item) => item.platform === current.platform && item.external_id === current.external_id,
    )
  ) {
    return current;
  }
  return top.value;
});
const palette = useCoverPalette(washCoverUrl);
const heroBg = computed(() => (followAmbient.value ? "var(--surface)" : palette.value.bg));
const heroHover = computed(() =>
  followAmbient.value ? "rgb(24 24 27 / 0.06)" : palette.value.hover,
);
const heroActive = computed(() =>
  followAmbient.value ? "rgb(24 24 27 / 0.1)" : palette.value.active,
);

function rankKlass(rank: number): string {
  if (rank === 1) return "text-[1.1rem] font-bold text-primary";
  if (rank <= 3) return "text-[0.95rem] font-semibold text-primary";
  return "text-[0.95rem] font-medium text-tertiary";
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
    class="relative overflow-hidden rounded-2xl ring-1"
    :class="followAmbient ? 'ring-zinc-200/80' : 'ring-black/[0.06] dark:ring-white/[0.06]'"
    :style="{
      backgroundColor: heroBg,
      '--hero-hover': heroHover,
      '--hero-active': heroActive,
    }"
  >
    <div v-if="!followAmbient" aria-hidden="true" class="pointer-events-none absolute inset-0">
      <CoverImage
        v-if="washCoverUrl"
        :src="washCoverUrl"
        :size="500"
        eager
        alt=""
        class="h-full w-full scale-[1.8] object-cover blur-3xl saturate-105"
      />
      <div class="absolute inset-0" :style="{ backgroundColor: palette.overlay }" />
    </div>
    <div class="relative flex flex-row gap-3 p-4 sm:gap-4">
      <button
        type="button"
        class="relative h-24 w-24 shrink-0 overflow-hidden rounded-xl sm:h-32 sm:w-32 sm:rounded-2xl md:h-36 md:w-36"
        :style="{ backgroundColor: heroBg }"
        :disabled="!featured"
        :aria-label="featured ? `播放 ${featured.title} · ${featured.artist}` : undefined"
        @click="onPlay(featured)"
      >
        <CoverImage
          v-if="featured"
          :src="featured.cover_url"
          :size="500"
          eager
          class="h-full w-full object-cover transition duration-200 hover:-translate-y-0.5"
          :alt="featured.title"
        />
        <div v-else class="skel h-full w-full" />
      </button>
      <div class="flex min-w-0 flex-1 flex-col">
        <div class="flex flex-wrap items-center gap-2 text-xs">
          <span
            class="rounded-full px-2 py-0.5 font-medium"
            :class="followAmbient ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900' : ''"
            :style="
              followAmbient
                ? undefined
                : { backgroundColor: palette.chipBg, color: palette.chipFg }
            "
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
              <span class="pointer-events-none tabular text-right" :class="rankKlass(item.rank)">
                {{ item.rank }}
              </span>
              <span class="pointer-events-none min-w-0">
                <span class="type-title block truncate">{{ item.title }}</span>
                <span class="block truncate text-[0.74rem] text-artist">
                  {{ item.artist }}
                </span>
              </span>
              <span class="relative z-10 pointer-events-auto">
                <TrackDownloadAction :item="item" />
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
