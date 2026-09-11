<script setup lang="ts">
import { computed } from "vue";
import type { RankItem } from "../types";
import { rowGridClass } from "../lib/list-grid";
import { usePlayerStore } from "../stores/player";
import AppIcon from "./AppIcon.vue";
import CoverImage from "./CoverImage.vue";
import TrackDownloadAction from "./TrackDownloadAction.vue";

const props = defineProps<{ item: RankItem; queue?: RankItem[] }>();
const player = usePlayerStore();

const delta = computed(() => {
  if (props.item.previous_rank == null) {
    return { text: "新", klass: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300" };
  }
  const diff = props.item.previous_rank - props.item.rank;
  if (diff > 0) {
    return {
      text: `+${diff}`,
      klass: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
    };
  }
  if (diff < 0) {
    return {
      text: `−${Math.abs(diff)}`,
      klass: "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
    };
  }
  return { text: "持平", klass: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300" };
});

const rankKlass = computed(() => {
  if (props.item.rank === 1) return "text-xl text-amber-800 dark:text-amber-300";
  if (props.item.rank === 2) return "text-lg text-zinc-700 dark:text-zinc-300";
  if (props.item.rank === 3) return "text-lg text-amber-700 dark:text-amber-400";
  return "text-zinc-600 dark:text-zinc-300";
});

const active = computed(
  () =>
    player.current?.platform === props.item.platform &&
    player.current?.external_id === props.item.external_id,
);

function onPlay() {
  player.play(props.item, props.queue);
}

</script>

<template>
  <div
    class="group relative grid min-h-[52px] w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-zinc-50 dark:hover:bg-white/5"
    :class="[rowGridClass, active ? 'bg-zinc-50 dark:bg-white/5' : '']"
  >
    <button
      type="button"
      class="absolute inset-0 z-0 rounded-2xl focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-zinc-400 dark:focus-visible:outline-zinc-600"
      :aria-label="`播放 ${item.title} · ${item.artist}`"
      @click="onPlay"
    />
    <div class="pointer-events-none tabular text-right font-semibold" :class="rankKlass">
      {{ String(item.rank).padStart(2, "0") }}
    </div>
    <div class="pointer-events-none relative h-11 w-11 overflow-hidden rounded-lg">
      <CoverImage
        :src="item.cover_url"
        :size="150"
        :alt="item.title"
        class="h-full w-full object-cover transition duration-200 group-hover:-translate-y-0.5"
      />
      <span
        class="absolute inset-0 hidden place-items-center bg-zinc-950/45 text-xs text-white md:grid md:opacity-0 md:group-hover:opacity-100"
      >
        <AppIcon name="play" :size="16" />
      </span>
    </div>
    <div class="pointer-events-none min-w-0">
      <div class="truncate font-medium" :class="active ? 'text-emerald-600 dark:text-emerald-300' : ''">
        {{ item.title }}
      </div>
      <div class="truncate text-sm text-zinc-500 dark:text-zinc-400">{{ item.artist }}</div>
    </div>
    <div class="flex items-center justify-self-end gap-2 text-sm">
      <span class="pointer-events-none tabular hidden w-8 shrink-0 text-right text-zinc-600 sm:inline dark:text-zinc-300">{{ Math.round(item.normalized_score) }}</span>
      <span class="pointer-events-none hidden rounded-full px-2 py-0.5 text-xs sm:inline-flex" :class="delta.klass">{{ delta.text }}</span>
      <span class="relative z-10 pointer-events-auto">
        <TrackDownloadAction :item="item" />
      </span>
    </div>
  </div>
</template>
