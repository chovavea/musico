<script setup lang="ts">
import { computed } from "vue";
import { useTrackDownload } from "../composables/useTrackDownload";
import type { RankItem } from "../types";
import AppIcon from "./AppIcon.vue";

const props = withDefaults(
  defineProps<{
    item: RankItem;
    showLabel?: boolean;
  }>(),
  {
    showLabel: false,
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
  return "bg-transparent text-zinc-500 ring-1 ring-zinc-200 hover:bg-zinc-100 dark:text-zinc-300 dark:ring-white/15 dark:hover:bg-white/10";
});

function enqueue() {
  if (state.value === "idle") void download.enqueue(props.item);
}
</script>

<template>
  <button
    type="button"
    class="relative z-10 inline-flex h-9 min-w-9 shrink-0 items-center justify-center gap-1.5 rounded-full text-xs font-medium transition active:scale-95 disabled:cursor-default"
    :class="[klass, showLabel ? 'px-3' : 'w-9']"
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
