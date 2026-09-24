<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { lyrics } from "../api";
import { usePlayerStore } from "../stores/player";
import { useThemeStore } from "../stores/theme";
import type { LyricLine } from "../types";
import AppIcon from "./AppIcon.vue";

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();

const player = usePlayerStore();
const theme = useThemeStore();
const lines = ref<LyricLine[]>([]);
const synced = ref(false);
const status = ref<"idle" | "loading" | "ready" | "empty" | "error">("idle");
const scroller = ref<HTMLElement | null>(null);
let requestId = 0;

const activeIndex = computed(() => {
  if (!synced.value) return -1;
  const ms = player.currentTime * 1000 + 150;
  let index = -1;
  lines.value.forEach((line, lineIndex) => {
    if (line.time_ms != null && line.time_ms <= ms) index = lineIndex;
  });
  return index;
});

const message = computed(() => {
  if (status.value === "loading") return "正在加载歌词";
  if (status.value === "error") return "歌词暂时获取失败";
  if (status.value === "empty") return "暂无歌词";
  return "";
});

async function load() {
  const item = player.current;
  const id = ++requestId;
  if (!item) {
    lines.value = [];
    status.value = "idle";
    return;
  }
  status.value = "loading";
  try {
    const response = await lyrics(item);
    if (id !== requestId) return;
    if (response.code !== 0) {
      lines.value = [];
      status.value = "error";
      return;
    }
    lines.value = response.data.lines ?? [];
    synced.value = Boolean(response.data.synced);
    status.value = lines.value.length ? "ready" : "empty";
  } catch {
    if (id !== requestId) return;
    lines.value = [];
    status.value = "error";
  }
}

function seekLine(line: LyricLine) {
  if (line.time_ms == null || !player.duration) return;
  player.seek(line.time_ms / 1000 / player.duration);
}

watch(
  () => [props.open, player.current?.platform, player.current?.external_id] as const,
  ([open]) => {
    if (open) void load();
  },
);

watch(activeIndex, async (index) => {
  if (!props.open || index < 0) return;
  await nextTick();
  const root = scroller.value;
  const line = root?.querySelector<HTMLElement>(`[data-line="${index}"]`);
  if (!root || !line) return;
  const top = line.offsetTop - root.clientHeight / 2 + line.clientHeight / 2;
  root.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
});
</script>

<template>
  <section
    v-if="open && player.current"
    class="absolute inset-x-0 bottom-full z-20 mb-2 flex max-h-[min(46vh,28rem)] flex-col overflow-hidden rounded-2xl shadow-lg"
    :class="
      theme.isGlaze
        ? 'bg-[var(--gz-player)] text-[color:var(--gz-text)] ring-1 ring-[color:var(--gz-line)]'
        : 'bg-white/95 text-zinc-900 ring-1 ring-zinc-200 backdrop-blur-md dark:bg-zinc-950/95 dark:text-zinc-100 dark:ring-white/10'
    "
    aria-label="歌词"
  >
    <header class="flex items-center gap-3 px-4 pb-1 pt-3">
      <div class="min-w-0 flex-1">
        <div class="truncate text-sm font-semibold">{{ player.current.title }}</div>
        <div
          class="truncate text-xs"
          :class="theme.isGlaze ? 'text-[color:var(--gz-muted)]' : 'text-secondary'"
        >
          {{ player.current.artist }}
        </div>
      </div>
      <button
        type="button"
        class="grid h-9 w-9 shrink-0 place-items-center rounded-full hover:bg-black/5 dark:hover:bg-white/10"
        aria-label="关闭歌词"
        @click="emit('close')"
      >
        <AppIcon name="close" :size="16" />
      </button>
    </header>
    <div
      v-if="message"
      class="grid min-h-36 flex-1 place-items-center px-6 pb-8 text-sm"
      :class="theme.isGlaze ? 'text-[color:var(--gz-muted)]' : 'text-secondary'"
    >
      <div class="text-center">
        <p>{{ message }}</p>
        <button
          v-if="status === 'error'"
          type="button"
          class="mt-3 underline"
          @click="load()"
        >
          重试
        </button>
      </div>
    </div>
    <div v-else ref="scroller" class="min-h-0 flex-1 overflow-y-auto px-6 pb-8">
      <div class="h-[38%]" aria-hidden="true" />
      <button
        v-for="(line, index) in lines"
        :key="`${line.time_ms ?? 'plain'}-${index}`"
        type="button"
        class="mx-auto block w-full max-w-lg py-2 text-center transition-colors"
        :class="
          activeIndex === index
            ? 'text-[1.15rem] font-semibold'
            : theme.isGlaze
              ? 'text-sm text-[color:var(--gz-muted)]'
              : 'text-sm text-zinc-400 dark:text-zinc-500'
        "
        :data-line="index"
        :data-active="activeIndex === index ? 'true' : 'false'"
        :disabled="line.time_ms == null || !player.duration"
        @click="seekLine(line)"
      >
        <span class="block leading-snug">{{ line.text }}</span>
        <span
          v-if="line.translation"
          class="mt-1 block text-xs font-normal leading-snug opacity-70"
        >
          {{ line.translation }}
        </span>
      </button>
      <div class="h-[38%]" aria-hidden="true" />
    </div>
  </section>
</template>
