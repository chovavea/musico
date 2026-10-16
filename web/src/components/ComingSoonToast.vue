<script setup lang="ts">
import { useNoticeStore } from "../stores/notice";
import { useThemeStore } from "../stores/theme";

const notice = useNoticeStore();
const theme = useThemeStore();
</script>

<template>
  <div
    v-if="notice.visible"
    role="status"
    aria-live="polite"
    :class="
      theme.isGlaze
        ? 'gz-toast'
        : 'fixed bottom-[calc(var(--player-bar-h,5.5rem)+0.75rem)] left-1/2 z-[60] -translate-x-1/2 rounded-full bg-zinc-900 px-4 py-2.5 text-sm text-white shadow-lg dark:bg-white dark:text-zinc-900'
    "
  >
    {{ notice.text }}
  </div>
</template>
