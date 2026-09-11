<script setup lang="ts">
import { computed } from "vue";
import { useTrackDownload } from "../composables/useTrackDownload";
import type { RankItem } from "../types";
import AppIcon from "./AppIcon.vue";

const props = withDefaults(
  defineProps<{
    item: RankItem;
    showLabel?: boolean;
    subtle?: boolean;
  }>(),
  {
    showLabel: false,
    subtle: false,
  },
);

const download = useTrackDownload();
const state = computed(() => download.state(props.item));
const label = computed(() => {
  if (state.value === "ready") return "已下载";
  if (state.value === "queued") return "队列中";
  return "下载";
});
const klass = computed(() => {
  if (state.value === "ready") {
    return "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300";
  }
  if (state.value === "queued") {
    return "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300";
  }
  if (props.subtle) {
    return "bg-black/5 text-secondary hover:bg-black/10 dark:bg-white/10 dark:hover:bg-white/15";
  }
  return "bg-zinc-900 text-white hover:bg-zinc-700 dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-200";
});

function enqueue() {
  if (state.value === "idle") void download.enqueue(props.item);
}
</script>

<template>
  <button
    type="button"
    class="relative z-10 inline-flex h-11 min-w-11 shrink-0 items-center justify-center gap-1.5 rounded-full px-3 text-xs font-medium transition active:scale-95 disabled:cursor-default"
    :class="klass"
    :aria-label="label"
    :title="label"
    :disabled="state !== 'idle'"
    @click.stop="enqueue"
  >
    <AppIcon
      :name="state === 'ready' ? 'check' : state === 'queued' ? 'spinner' : 'download'"
      :size="16"
    />
    <span v-if="showLabel">{{ label }}</span>
  </button>
</template>
