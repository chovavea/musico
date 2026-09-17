<script setup lang="ts">
import { computed } from "vue";
import type { OverviewColumn } from "../composables/useOverviewColumns";
import { chartShortName, platformLabel } from "../lib/boards";
import { usePlayerStore } from "../stores/player";
import type { RankItem } from "../types";
import AppIcon from "./AppIcon.vue";
import CoverImage from "./CoverImage.vue";

const props = defineProps<{ columns: OverviewColumn[] }>();
const player = usePlayerStore();

const slides = computed(() =>
  props.columns
    .map((column) => {
      const items = column.latest?.items ?? [];
      const top = items[0];
      return {
        id: column.board.id,
        title: "热门榜单",
        kicker: "每日推荐",
        subtitle: "发现更多好音乐",
        cover: top?.cover_url ?? null,
        count: items.length,
        items,
        top,
        boardName: `${platformLabel(column.board.platform)}${chartShortName(column.board.name)}`,
      };
    })
    .filter((slide) => slide.top),
);

function playSlide(items: RankItem[], top?: RankItem) {
  if (top) player.play(top, items);
}
</script>

<template>
  <div v-if="slides.length" class="gz-hero-scroller">
    <article v-for="(slide, slideIndex) in slides" :key="slide.id" class="gz-hero">
      <CoverImage
        v-if="slide.cover"
        :src="slide.cover"
        :size="500"
        eager
        :alt="slide.top?.title ?? slide.title"
        class="gz-hero-cover"
      />
      <div v-else class="gz-hero-cover skel" />
      <div class="gz-hero-scrim" aria-hidden="true" />
      <div class="gz-hero-body">
        <div>
          <p class="gz-kicker">{{ slide.kicker }}</p>
          <h2 class="gz-hero-title">{{ slide.title }}</h2>
          <p class="gz-hero-sub">{{ slide.subtitle }}</p>
        </div>
        <button
          type="button"
          class="gz-play-pill"
          :aria-label="`立即播放 ${slide.boardName}`"
          :disabled="!slide.top"
          @click="playSlide(slide.items, slide.top)"
        >
          <span class="gz-play-circle">
            <AppIcon name="play" :size="14" />
          </span>
          立即播放
        </button>
      </div>
      <span class="gz-hero-meta">
        <template v-if="slide.count">共 {{ slide.count }} 首 · </template>
        {{ slideIndex + 1 }}/{{ slides.length }}
      </span>
    </article>
  </div>
  <div v-else class="gz-hero skel mt-3 w-full" style="flex-basis: 100%" />
</template>
