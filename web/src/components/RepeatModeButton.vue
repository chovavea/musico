<script setup lang="ts">
import { computed } from "vue";
import { useNoticeStore } from "../stores/notice";
import { usePlayerStore } from "../stores/player";
import AppIcon from "./AppIcon.vue";

withDefaults(
  defineProps<{
    compact?: boolean;
  }>(),
  { compact: false },
);

const player = usePlayerStore();
const notice = useNoticeStore();

const label = computed(() => {
  if (player.repeatMode === "one") return "单曲循环";
  if (player.repeatMode === "all") return "列表循环";
  return "顺序播放";
});

function cycle() {
  player.cycleRepeat();
  notice.show(label.value);
}
</script>

<template>
  <button
    type="button"
    class="repeat-mode"
    :class="[player.repeatMode === 'off' ? '' : 'is-on', compact ? 'is-compact' : '']"
    :data-mode="player.repeatMode"
    :aria-label="label"
    :aria-pressed="player.repeatMode !== 'off'"
    :title="label"
    @click="cycle()"
  >
    <AppIcon name="repeat" :size="18" />
    <span v-if="player.repeatMode === 'one'" class="repeat-mode-one">1</span>
    <span v-if="player.repeatMode !== 'off'" class="repeat-mode-dot" />
  </button>
</template>
