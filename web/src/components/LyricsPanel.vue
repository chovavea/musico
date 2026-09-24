<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { isCreditLine, useLyrics } from "../composables/useLyrics";
import { usePlayerStore } from "../stores/player";
import type { LyricLine } from "../types";
import AppIcon from "./AppIcon.vue";
import CoverImage from "./CoverImage.vue";

const emit = defineEmits<{ close: [] }>();

const player = usePlayerStore();
const { lines, status, activeIndex, reload } = useLyrics();
const view = ref<HTMLElement | null>(null);
const track = ref<HTMLElement | null>(null);
const offset = ref(0);
const follow = ref(true);
let resumeTimer = 0;
let resizeObserver: ResizeObserver | null = null;

const message = () => {
  if (status.value === "loading") return "正在加载歌词";
  if (status.value === "error") return "歌词暂时获取失败";
  if (status.value === "empty") return "暂无歌词";
  return "";
};

function tone(index: number): string {
  const credit = isCreditLine(lines.value[index]?.text ?? "", index === 0);
  const current = activeIndex.value;
  let distanceClass = "is-far";
  if (current < 0) distanceClass = index === 0 ? "is-now" : "is-far";
  else {
    const distance = Math.abs(index - current);
    distanceClass = distance === 0 ? "is-now" : distance === 1 ? "is-near" : "is-far";
  }
  return credit ? `${distanceClass} is-credit` : distanceClass;
}

async function align() {
  if (!follow.value) return;
  await nextTick();
  const viewport = view.value;
  const column = track.value;
  if (!viewport || !column) return;
  const focus = activeIndex.value < 0 ? 0 : activeIndex.value;
  const line = column.querySelector<HTMLElement>(`[data-line="${focus}"]`);
  if (!line) return;
  const anchor = viewport.clientHeight * 0.38;
  const center = line.offsetTop + line.offsetHeight / 2;
  offset.value = anchor - center;
}

function pauseFollow() {
  follow.value = false;
  window.clearTimeout(resumeTimer);
}

function resumeFollowSoon() {
  window.clearTimeout(resumeTimer);
  resumeTimer = window.setTimeout(() => {
    follow.value = true;
    void align();
  }, 4000);
}

function seekLine(line: LyricLine) {
  if (line.time_ms == null || !player.duration) return;
  player.seek(line.time_ms / 1000 / player.duration);
  follow.value = true;
  window.clearTimeout(resumeTimer);
  void align();
}

watch(activeIndex, () => {
  void align();
});
watch(lines, () => {
  offset.value = 0;
  void align();
});

onMounted(() => {
  void align();
  if (typeof ResizeObserver === "undefined" || !view.value) return;
  resizeObserver = new ResizeObserver(() => {
    void align();
  });
  resizeObserver.observe(view.value);
});

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  window.clearTimeout(resumeTimer);
});
</script>

<template>
  <div v-if="player.current" class="lyric-stage">
    <div class="lyric-side">
      <CoverImage
        :src="player.current.cover_url"
        :size="500"
        :alt="player.current.title"
        class="lyric-cover"
      />
      <div class="min-w-0">
        <div class="truncate text-[0.95rem] font-semibold leading-tight">
          {{ player.current.title }}
        </div>
        <div class="mt-0.5 truncate text-xs text-white/80">
          {{ player.current.artist }}
        </div>
      </div>
    </div>
    <div
      ref="view"
      class="lyric-view"
      @pointerdown="pauseFollow"
      @pointerup="resumeFollowSoon"
      @pointercancel="resumeFollowSoon"
    >
      <p
        v-if="message()"
        class="absolute inset-0 grid place-items-center px-6 text-center text-sm text-white/75"
      >
        <span>
          {{ message() }}
          <button
            v-if="status === 'error'"
            type="button"
            class="mt-2 block w-full underline"
            @click="reload()"
          >
            重试
          </button>
        </span>
      </p>
      <div
        v-else
        ref="track"
        class="lyric-track"
        :style="{ transform: `translate3d(0, ${offset}px, 0)` }"
      >
        <button
          v-for="(line, index) in lines"
          :key="`${line.time_ms ?? 'plain'}-${index}`"
          type="button"
          class="lyric-line"
          :class="tone(index)"
          :data-line="index"
          :disabled="line.time_ms == null || !player.duration"
          @click="seekLine(line)"
        >
          <span class="block">{{ line.text }}</span>
          <span v-if="line.translation" class="lyric-trans">{{ line.translation }}</span>
        </button>
      </div>
    </div>
    <button type="button" class="lyric-close" aria-label="关闭歌词" @click="emit('close')">
      <AppIcon name="close" :size="16" />
    </button>
  </div>
</template>

<style scoped>
.lyric-stage {
  position: relative;
  color: #fff;
  display: grid;
  grid-template-columns: 1fr;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 8px;
  height: min(46vh, 24rem);
  min-height: 13rem;
  padding: 12px 16px 4px;
}

.lyric-side {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
  padding-right: 2rem;
}

.lyric-cover {
  height: 2.75rem;
  width: 2.75rem;
  flex-shrink: 0;
  border-radius: 0.8rem;
  object-fit: cover;
}

.lyric-view {
  position: relative;
  min-height: 0;
  overflow: hidden;
  -webkit-mask-image: linear-gradient(
    to bottom,
    transparent 0%,
    #000 16%,
    #000 76%,
    transparent 100%
  );
  mask-image: linear-gradient(to bottom, transparent 0%, #000 16%, #000 76%, transparent 100%);
}

.lyric-track {
  transition: transform 520ms cubic-bezier(0.22, 1, 0.36, 1);
  will-change: transform;
}

.lyric-line {
  display: block;
  width: 100%;
  border: 0;
  background: none;
  padding: 0.42rem 0.25rem;
  text-align: center;
  color: #fff;
  font-size: 0.92rem;
  line-height: 1.45;
  opacity: 0.58;
  transition: opacity 280ms ease, font-size 280ms ease;
}

.lyric-line.is-near {
  opacity: 0.8;
}

.lyric-line.is-now {
  opacity: 1;
  font-size: 1.22rem;
  font-weight: 650;
  line-height: 1.35;
}

.lyric-line.is-credit {
  font-size: 0.78rem;
  font-weight: 450;
  opacity: 0.7;
}

.lyric-line.is-credit.is-now {
  font-size: 0.86rem;
  font-weight: 550;
  opacity: 0.72;
}

.lyric-line:disabled {
  cursor: default;
}

.lyric-trans {
  display: block;
  margin-top: 0.15rem;
  font-size: 0.75rem;
  font-weight: 400;
  line-height: 1.35;
  opacity: 0.72;
}

.lyric-close {
  position: absolute;
  top: 8px;
  right: 8px;
  display: grid;
  height: 2rem;
  width: 2rem;
  place-items: center;
  border-radius: 999px;
  color: inherit;
  opacity: 0.7;
}

.lyric-close:hover {
  background: rgb(127 127 127 / 0.16);
  opacity: 1;
}

@media (min-width: 720px) {
  .lyric-stage {
    grid-template-columns: 8.5rem minmax(0, 1fr);
    grid-template-rows: minmax(0, 1fr);
    align-items: stretch;
    height: min(40vh, 20rem);
    padding: 16px 18px 8px;
  }

  .lyric-side {
    flex-direction: column;
    align-items: flex-start;
    justify-content: flex-end;
    gap: 12px;
    padding: 0 0 12% 0;
  }

  .lyric-cover {
    height: 7.5rem;
    width: 7.5rem;
    border-radius: 1.1rem;
  }

  .lyric-line {
    text-align: left;
    padding-left: 0.15rem;
  }
}
</style>
