<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { useHealthStore } from "../stores/health";
import { useThemeStore } from "../stores/theme";

const theme = useThemeStore();
const health = useHealthStore();
const route = useRoute();
const open = ref(false);
const root = ref<HTMLElement | null>(null);

const statusLabel = computed(() => {
  if (health.error) return "异常";
  const status = health.payload?.status;
  if (status === "ready") return "就绪";
  if (status === "degraded") return "降级";
  if (status === "starting") return "启动中";
  return "读取中";
});

function onDocClick(event: MouseEvent) {
  if (!root.value?.contains(event.target as Node)) {
    open.value = false;
  }
}

function onDocKey(event: KeyboardEvent) {
  if (event.key === "Escape") open.value = false;
}

function choose(dark: boolean) {
  theme.setDark(dark);
}

onMounted(() => {
  document.addEventListener("click", onDocClick);
  document.addEventListener("keydown", onDocKey);
});
onUnmounted(() => {
  document.removeEventListener("click", onDocClick);
  document.removeEventListener("keydown", onDocKey);
});
</script>

<template>
  <div ref="root" class="relative">
    <button
      type="button"
      class="grid h-11 w-11 place-items-center rounded-full text-zinc-500 ring-1 ring-zinc-300 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:ring-white/15 dark:hover:bg-white/10 dark:hover:text-white"
      :class="open ? 'bg-zinc-100 text-zinc-900 dark:bg-white/10 dark:text-white' : ''"
      :aria-expanded="open"
      aria-haspopup="dialog"
      aria-label="配置"
      @click.stop="open = !open"
    >
      <svg viewBox="0 0 24 24" class="h-5 w-5" fill="currentColor" aria-hidden="true">
        <rect x="4" y="6" width="16" height="2.2" rx="1.1" />
        <rect x="4" y="11" width="16" height="2.2" rx="1.1" />
        <rect x="4" y="16" width="16" height="2.2" rx="1.1" />
      </svg>
    </button>
    <div
      v-if="open"
      class="menu-popover absolute right-0 top-full z-30 mt-1.5 w-60 rounded-2xl bg-white p-1.5 shadow-lg ring-1 ring-zinc-200/80 dark:bg-zinc-900 dark:ring-white/10"
      role="dialog"
      aria-label="配置"
    >
      <div class="flex h-11 items-center gap-2 px-2">
        <span class="shrink-0 text-sm">外观</span>
        <div
          class="relative ml-auto grid min-w-0 grid-cols-2 rounded-full bg-zinc-100 p-[3px] dark:bg-zinc-800"
          role="group"
          aria-label="外观"
        >
          <span
            class="pointer-events-none absolute top-[3px] bottom-[3px] w-[calc(50%-3px)] rounded-full bg-white shadow-sm ring-1 ring-black/[0.04] transition-[left] duration-200 ease-[cubic-bezier(0.2,0.8,0.2,1)] dark:bg-zinc-600 dark:ring-white/10"
            :style="{ left: theme.dark ? '50%' : '3px' }"
          />
          <button
            type="button"
            class="relative z-10 h-8 min-w-[3.25rem] rounded-full px-2.5 text-sm"
            :class="!theme.dark ? 'font-medium text-zinc-900 dark:text-white' : 'text-zinc-500 dark:text-zinc-400'"
            :aria-pressed="!theme.dark"
            @click="choose(false)"
          >
            浅色
          </button>
          <button
            type="button"
            class="relative z-10 h-8 min-w-[3.25rem] rounded-full px-2.5 text-sm"
            :class="theme.dark ? 'font-medium text-zinc-900 dark:text-white' : 'text-zinc-500 dark:text-zinc-400'"
            :aria-pressed="theme.dark"
            @click="choose(true)"
          >
            深色
          </button>
        </div>
      </div>
      <div class="mx-2 h-px bg-zinc-100 dark:bg-white/10" role="separator" />
      <RouterLink
        to="/health"
        class="flex h-11 items-center gap-2 rounded-xl px-2 text-sm hover:bg-zinc-100 dark:hover:bg-white/10"
        :class="route.name === 'health' ? 'bg-zinc-100 dark:bg-white/10' : ''"
        @click="open = false"
      >
        <span class="shrink-0">状态</span>
        <span class="ml-auto flex items-center gap-1.5">
          <span
            class="status-glow h-2 w-2 shrink-0"
            :style="{ '--status-glow': health.glowColor }"
            aria-hidden="true"
          />
          <span class="text-sm text-zinc-500 dark:text-zinc-400">{{ statusLabel }}</span>
        </span>
        <svg viewBox="0 0 16 16" class="h-3.5 w-3.5 shrink-0 text-zinc-400" fill="none" aria-hidden="true">
          <path d="M6 3.5 10.5 8 6 12.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </RouterLink>
    </div>
  </div>
</template>
