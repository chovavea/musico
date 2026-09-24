import { computed, ref, watch } from "vue";
import { lyrics } from "../api";
import { usePlayerStore } from "../stores/player";
import type { LyricLine } from "../types";

const CREDIT_LINE =
  /^(?:歌曲)?(?:词|曲|编曲|作词|作曲|制作(?:人|团队)?|吉他|贝斯|鼓|钢琴|和声|和音|合声|录音|混音|母带|监制|出品|策划|企划|统筹|弦乐|键盘|演唱|原唱|bass|guitar|drum|piano|keyboard|strings)\s*[:：]/i;

const OPENING_CREDIT =
  /^.{1,48}\s[-–—]\s.{1,48}(?:\([^)]*\))?$/;

export function isCreditLine(text: string, opening = false): boolean {
  const value = text.trim();
  if (CREDIT_LINE.test(value)) return true;
  return opening && OPENING_CREDIT.test(value) && !/[，。！？、]/.test(value);
}

const lines = ref<LyricLine[]>([]);
const synced = ref(false);
const status = ref<"idle" | "loading" | "ready" | "empty" | "error">("idle");
let requestId = 0;
let started = false;

async function load() {
  const player = usePlayerStore();
  const item = player.current;
  const id = ++requestId;
  if (!item) {
    lines.value = [];
    synced.value = false;
    status.value = "idle";
    return;
  }
  status.value = "loading";
  try {
    const response = await lyrics(item);
    if (id !== requestId) return;
    if (response.code !== 0) {
      lines.value = [];
      synced.value = false;
      status.value = "error";
      return;
    }
    lines.value = response.data.lines ?? [];
    synced.value = Boolean(response.data.synced);
    status.value = lines.value.length ? "ready" : "empty";
  } catch {
    if (id !== requestId) return;
    lines.value = [];
    synced.value = false;
    status.value = "error";
  }
}

export function useLyrics() {
  const player = usePlayerStore();
  if (!started) {
    started = true;
    watch(
      () =>
        player.current ? `${player.current.platform}:${player.current.external_id}` : "",
      () => {
        void load();
      },
      { immediate: true },
    );
  }

  const activeIndex = computed(() => {
    if (!synced.value || !lines.value.length) return -1;
    const ms = player.currentTime * 1000 + 180;
    let index = -1;
    lines.value.forEach((line, lineIndex) => {
      if (line.time_ms != null && line.time_ms <= ms) index = lineIndex;
    });
    return index;
  });

  const activeText = computed(() => {
    const index = activeIndex.value;
    if (index < 0) return "";
    for (let cursor = index; cursor >= 0; cursor -= 1) {
      const text = lines.value[cursor]?.text?.trim() ?? "";
      if (text && !isCreditLine(text, cursor === 0)) return text;
    }
    return "";
  });

  return { lines, synced, status, activeIndex, activeText, reload: load };
}
