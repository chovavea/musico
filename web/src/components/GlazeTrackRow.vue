<script setup lang="ts">
import { computed } from "vue";
import { useTrackDownload } from "../composables/useTrackDownload";
import { usePlayerStore } from "../stores/player";
import type { RankItem } from "../types";
import AppIcon from "./AppIcon.vue";
import CoverImage from "./CoverImage.vue";

const props = defineProps<{
  item: RankItem;
  queue?: RankItem[];
  hit?: boolean;
}>();

const player = usePlayerStore();
const download = useTrackDownload();

const active = computed(
  () =>
    player.current?.platform === props.item.platform &&
    player.current?.external_id === props.item.external_id,
);
const downloadState = computed(() => download.state(props.item));
const downloadLabel = computed(() => {
  if (downloadState.value === "ready") return "已下载";
  if (downloadState.value === "queued") return "下载中";
  return "下载";
});

const rankKlass = computed(() => {
  if (props.item.rank === 1) return "is-1";
  if (props.item.rank === 3) return "is-3";
  return "";
});

function play() {
  player.play(props.item, props.queue);
}

function onDownload() {
  if (downloadState.value !== "idle") return;
  void download.enqueue(props.item);
}
</script>

<template>
  <div class="gz-row" :class="{ 'is-hit': hit || active }">
    <button
      type="button"
      class="absolute inset-0 z-0 rounded-[18px] focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-zinc-400 dark:focus-visible:outline-zinc-600"
      :aria-label="`播放 ${item.title} · ${item.artist}`"
      @click="play"
    />
    <div class="gz-rank pointer-events-none" :class="rankKlass">
      {{ String(item.rank).padStart(2, "0") }}
    </div>
    <div class="gz-cover pointer-events-none">
      <CoverImage :src="item.cover_url" :size="150" :alt="item.title" class="h-full w-full object-cover" />
    </div>
    <div class="pointer-events-none min-w-0">
      <div class="gz-title">{{ item.title }}</div>
      <div class="gz-artist">{{ item.artist }}</div>
    </div>
    <div class="gz-row-actions relative z-10">
      <button
        type="button"
        class="gz-ghost"
        :aria-label="downloadLabel"
        :title="downloadLabel"
        :disabled="downloadState !== 'idle'"
        @click.stop="onDownload"
      >
        <AppIcon
          :name="downloadState === 'ready' ? 'check' : downloadState === 'queued' ? 'spinner' : 'download'"
          :size="16"
        />
      </button>
    </div>
  </div>
</template>
