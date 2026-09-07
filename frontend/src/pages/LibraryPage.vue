<script setup lang="ts">
import { onMounted } from "vue";
import { RouterLink } from "vue-router";
import { useDownloadsStore } from "../stores/downloads";
import { usePlayerStore } from "../stores/player";
import type { RankItem } from "../types";

const downloads = useDownloadsStore();
const player = usePlayerStore();

function play(asset: (typeof downloads.assets)[number]) {
  const item: RankItem = {
    rank: 0,
    previous_rank: null,
    normalized_score: 0,
    raw_score: null,
    title: asset.title,
    artist: asset.artist,
    album: asset.album,
    cover_url: null,
    official_url: null,
    external_id: asset.track_id,
    platform: "library",
    preview_url: null,
    quality: null,
    expire_at: null,
    library_status: "ready",
    library_asset_id: asset.id,
  };
  player.play(item);
}

onMounted(async () => {
  await Promise.all([downloads.loadLibrary(), downloads.loadTasks(), downloads.refreshSummary()]);
});
</script>

<template>
  <section>
    <div class="mb-6 flex items-end justify-between gap-3">
      <div>
        <RouterLink to="/" class="inline-flex min-h-11 items-center text-sm text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-white">
          返回
        </RouterLink>
        <h1 class="mt-3 text-2xl font-semibold tracking-tight md:text-3xl">音乐库</h1>
        <p class="mt-2 text-sm text-zinc-500 dark:text-zinc-400">
          已下载文件、任务进度和失败记录
        </p>
      </div>
      <div class="text-right text-sm text-zinc-500 dark:text-zinc-400">
        {{ downloads.assets.length }} 首
      </div>
    </div>

    <div v-if="downloads.error" class="mb-4 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-600 dark:bg-rose-500/10 dark:text-rose-300">
      {{ downloads.error }}
    </div>

    <div class="divide-y divide-zinc-100 overflow-hidden rounded-2xl bg-white ring-1 ring-zinc-200/80 dark:divide-white/5 dark:bg-zinc-900 dark:ring-white/10">
      <div v-for="asset in downloads.assets" :key="asset.id" class="flex items-center gap-3 px-4 py-3">
        <div class="min-w-0 flex-1">
          <div class="truncate font-medium">{{ asset.title }}</div>
          <div class="truncate text-sm text-zinc-500 dark:text-zinc-400">
            {{ asset.artist }} · {{ asset.format.toUpperCase() }}
            <span v-if="asset.bit_depth"> · {{ asset.bit_depth }}bit</span>
            <span v-if="asset.sample_rate_hz"> · {{ asset.sample_rate_hz / 1000 }}kHz</span>
          </div>
        </div>
        <button type="button" class="grid h-10 w-10 place-items-center rounded-full bg-zinc-900 text-white dark:bg-white dark:text-zinc-900" aria-label="播放" title="播放" @click="play(asset)">
          ▶
        </button>
        <a :href="`/api/v1/library/${encodeURIComponent(asset.id)}/download`" class="grid h-10 w-10 place-items-center rounded-full ring-1 ring-zinc-300 dark:ring-white/15" aria-label="下载文件" title="下载文件">
          ↓
        </a>
        <button type="button" class="grid h-10 w-10 place-items-center rounded-full text-rose-500 ring-1 ring-rose-200 dark:ring-rose-500/30" aria-label="删除" title="删除" @click="downloads.remove(asset.id)">
          ×
        </button>
      </div>
      <div v-if="!downloads.assets.length" class="px-4 py-10 text-center text-sm text-zinc-500">
        暂无已下载歌曲
      </div>
    </div>

    <div class="mt-6">
      <h2 class="mb-3 text-lg font-semibold">下载任务</h2>
      <div class="divide-y divide-zinc-100 overflow-hidden rounded-2xl bg-white ring-1 ring-zinc-200/80 dark:divide-white/5 dark:bg-zinc-900 dark:ring-white/10">
        <div v-for="task in downloads.tasks" :key="task.id" class="flex items-center gap-3 px-4 py-3 text-sm">
          <div class="min-w-0 flex-1">
            <div class="truncate">{{ task.title || "未知歌曲" }} - {{ task.artist || "未知歌手" }}</div>
            <div class="text-xs text-zinc-500">{{ task.status }}<span v-if="task.last_error"> · {{ task.last_error }}</span></div>
          </div>
          <div v-if="task.progress != null" class="tabular text-xs text-zinc-500">{{ Math.round(task.progress * 100) }}%</div>
          <button v-if="task.status === 'failed'" type="button" class="rounded-full px-3 py-2 text-xs ring-1 ring-zinc-300 dark:ring-white/15" @click="downloads.retry(task.id)">重试</button>
          <a v-if="task.status === 'failed' && task.source_page_url" :href="task.source_page_url" target="_blank" rel="noreferrer" class="rounded-full px-3 py-2 text-xs ring-1 ring-zinc-300 dark:ring-white/15">去源网站</a>
        </div>
        <div v-if="!downloads.tasks.length" class="px-4 py-6 text-sm text-zinc-500">暂无任务记录</div>
      </div>
    </div>
  </section>
</template>
