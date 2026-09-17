<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { comingSoon } from "../lib/coming-soon";
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
const menuOpen = ref(false);
const root = ref<HTMLElement | null>(null);

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
  menuOpen.value = false;
  player.play(props.item, props.queue);
}

function onDownload() {
  if (downloadState.value !== "idle") return;
  menuOpen.value = false;
  void download.enqueue(props.item);
}

function onDoc(event: PointerEvent) {
  if (!root.value?.contains(event.target as Node)) menuOpen.value = false;
}

onMounted(() => document.addEventListener("pointerdown", onDoc));
onUnmounted(() => document.removeEventListener("pointerdown", onDoc));
</script>

<template>
  <div ref="root" class="gz-row" :class="{ 'is-hit': hit || active }">
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
      <button type="button" class="gz-ghost" :aria-label="`播放 ${item.title}`" @click.stop="play">
        <AppIcon name="play-outline" :size="20" />
      </button>
      <button
        type="button"
        class="gz-ghost"
        :aria-expanded="menuOpen"
        :aria-label="`${item.title} 更多操作`"
        @click.stop="menuOpen = !menuOpen"
      >
        <AppIcon
          :name="downloadState === 'ready' ? 'check' : downloadState === 'queued' ? 'spinner' : 'more'"
          :size="18"
        />
      </button>
      <div v-if="menuOpen" class="gz-sheet" role="menu">
        <button type="button" role="menuitem" :disabled="downloadState !== 'idle'" @click.stop="onDownload">
          <AppIcon :name="downloadState === 'ready' ? 'check' : downloadState === 'queued' ? 'spinner' : 'download'" :size="15" />
          {{ downloadLabel }}
        </button>
        <button type="button" role="menuitem" @click.stop="comingSoon('下一首播放')">下一首播放</button>
        <button type="button" role="menuitem" @click.stop="comingSoon('加入歌单')">加入歌单</button>
      </div>
    </div>
  </div>
</template>
