<script setup lang="ts">
import { onMounted, ref } from "vue";
import AppIcon from "../components/AppIcon.vue";
import ConfirmDialog from "../components/ConfirmDialog.vue";
import PageHeader from "../components/PageHeader.vue";
import { downloadErrorLabel, downloadStatusLabel } from "../lib/status-labels";
import { useDownloadsStore } from "../stores/downloads";
import { usePlayerStore } from "../stores/player";
import type { LibraryAsset, RankItem } from "../types";

const downloads = useDownloadsStore();
const player = usePlayerStore();
const menuAssetId = ref("");
const confirmAsset = ref<LibraryAsset | null>(null);
const deletingId = ref("");
const retryingId = ref("");
const notice = ref("");

function play(asset: LibraryAsset) {
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

async function removeConfirmed() {
  const asset = confirmAsset.value;
  if (!asset || deletingId.value) return;
  deletingId.value = asset.id;
  notice.value = "";
  try {
    const removed = await downloads.remove(asset.id);
    if (!removed) {
      notice.value = downloads.actionError || "删除失败，请稍后重试";
      return;
    }
    notice.value = `已删除《${asset.title}》`;
    confirmAsset.value = null;
  } catch {
    notice.value = downloads.actionError || "删除失败，请稍后重试";
  } finally {
    deletingId.value = "";
  }
}

async function retry(taskId: string) {
  if (retryingId.value) return;
  retryingId.value = taskId;
  try {
    const started = await downloads.retry(taskId);
    if (!started) notice.value = downloads.actionError || "重试失败，请稍后再试";
  } catch {
    notice.value = downloads.actionError || "重试失败，请稍后再试";
  } finally {
    retryingId.value = "";
  }
}

onMounted(async () => {
  await Promise.allSettled([
    downloads.loadLibrary(),
    downloads.loadTasks(),
    downloads.refreshSummary(),
  ]);
});
</script>

<template>
  <section>
    <PageHeader
      title="音乐库"
      eyebrow="本地内容"
      description="管理已下载文件、任务进度和失败记录。"
      back-to="/"
    >
      <template #actions>
        <span class="text-sm text-secondary">{{ downloads.assets.length }} 首</span>
      </template>
    </PageHeader>

    <div
      v-if="downloads.error"
      role="alert"
      class="mb-4 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:bg-rose-500/10 dark:text-rose-300"
    >
      {{ downloads.error }}
    </div>
    <p v-if="notice" class="mb-4 text-sm text-secondary" aria-live="polite">{{ notice }}</p>

    <div class="divide-y divide-zinc-100 overflow-visible rounded-2xl bg-white ring-1 ring-zinc-200/80 dark:divide-white/5 dark:bg-zinc-900 dark:ring-white/10">
      <div
        v-for="asset in downloads.assets"
        :key="asset.id"
        class="relative flex min-h-16 items-center gap-3 px-4 py-2.5"
      >
        <div class="min-w-0 flex-1">
          <div class="truncate font-medium">{{ asset.title }}</div>
          <div class="truncate text-sm text-secondary">
            {{ asset.artist }} · {{ asset.format.toUpperCase() }}
            <span v-if="asset.bit_depth"> · {{ asset.bit_depth }}bit</span>
            <span v-if="asset.sample_rate_hz"> · {{ asset.sample_rate_hz / 1000 }}kHz</span>
          </div>
        </div>
        <button
          type="button"
          class="grid h-11 w-11 place-items-center rounded-full bg-zinc-900 text-white dark:bg-white dark:text-zinc-900"
          :aria-label="`播放 ${asset.title}`"
          @click="play(asset)"
        >
          <AppIcon name="play" :size="17" />
        </button>
        <a
          :href="`/api/v1/library/${encodeURIComponent(asset.id)}/download`"
          class="hidden h-11 w-11 place-items-center rounded-full ring-1 ring-zinc-300 sm:grid dark:ring-white/15"
          aria-label="下载文件"
        >
          <AppIcon name="download" :size="17" />
        </a>
        <button
          type="button"
          class="hidden h-11 w-11 place-items-center rounded-full text-rose-600 ring-1 ring-rose-200 sm:grid dark:text-rose-300 dark:ring-rose-500/30"
          aria-label="删除"
          @click="confirmAsset = asset"
        >
          <AppIcon name="trash" :size="17" />
        </button>
        <button
          type="button"
          class="grid h-11 w-11 place-items-center rounded-full ring-1 ring-zinc-300 sm:hidden dark:ring-white/15"
          :aria-expanded="menuAssetId === asset.id"
          aria-label="更多操作"
          @click="menuAssetId = menuAssetId === asset.id ? '' : asset.id"
        >
          <AppIcon name="more" :size="18" />
        </button>
        <div
          v-if="menuAssetId === asset.id"
          class="absolute right-4 top-[calc(100%-0.25rem)] z-20 w-40 rounded-xl bg-white p-1.5 ring-1 ring-zinc-200 dark:bg-zinc-800 dark:ring-white/10 sm:hidden"
        >
          <a
            :href="`/api/v1/library/${encodeURIComponent(asset.id)}/download`"
            class="flex h-11 items-center gap-2 rounded-lg px-3 text-sm hover:bg-zinc-100 dark:hover:bg-white/10"
            @click="menuAssetId = ''"
          >
            <AppIcon name="download" :size="16" /> 下载文件
          </a>
          <button
            type="button"
            class="flex h-11 w-full items-center gap-2 rounded-lg px-3 text-sm text-rose-600 hover:bg-rose-50 dark:text-rose-300 dark:hover:bg-rose-500/10"
            @click="menuAssetId = ''; confirmAsset = asset"
          >
            <AppIcon name="trash" :size="16" /> 删除
          </button>
        </div>
      </div>
      <div v-if="!downloads.assets.length && !downloads.libraryLoading" class="px-4 py-10 text-center text-sm text-secondary">
        暂无已下载歌曲
      </div>
      <div v-if="downloads.libraryLoading && !downloads.assets.length" class="space-y-3 px-4 py-5">
        <div v-for="n in 3" :key="n" class="skel h-11" />
      </div>
    </div>

    <div class="mt-6">
      <h2 class="mb-3 text-lg font-semibold">下载任务</h2>
      <div class="divide-y divide-zinc-100 overflow-hidden rounded-2xl bg-white ring-1 ring-zinc-200/80 dark:divide-white/5 dark:bg-zinc-900 dark:ring-white/10">
        <div
          v-for="task in downloads.tasks"
          :key="task.id"
          class="flex flex-wrap items-center gap-2 px-4 py-3 text-sm"
        >
          <div class="min-w-[12rem] flex-1">
            <div class="truncate">{{ task.title || "未知歌曲" }} · {{ task.artist || "未知歌手" }}</div>
            <div class="mt-0.5 text-xs text-secondary">
              {{ downloadStatusLabel(task.status) }}
              <span v-if="task.last_error"> · {{ downloadErrorLabel(task.last_error) }}</span>
            </div>
          </div>
          <div v-if="task.progress != null" class="tabular text-xs text-secondary">
            {{ Math.round(task.progress * 100) }}%
          </div>
          <button
            v-if="task.status === 'failed'"
            type="button"
            class="inline-flex h-11 items-center gap-1.5 rounded-full px-3 text-xs ring-1 ring-zinc-300 disabled:opacity-60 dark:ring-white/15"
            :disabled="Boolean(retryingId)"
            @click="retry(task.id)"
          >
            <AppIcon :name="retryingId === task.id ? 'spinner' : 'refresh'" :size="15" />
            重试
          </button>
          <a
            v-if="task.status === 'failed' && task.source_page_url"
            :href="task.source_page_url"
            target="_blank"
            rel="noreferrer"
            class="inline-flex h-11 items-center gap-1.5 rounded-full px-3 text-xs ring-1 ring-zinc-300 dark:ring-white/15"
          >
            <AppIcon name="external" :size="15" /> 查看来源
          </a>
        </div>
        <div v-if="!downloads.tasks.length && !downloads.tasksLoading" class="px-4 py-6 text-sm text-secondary">暂无任务记录</div>
      </div>
    </div>

    <ConfirmDialog
      id="delete-track"
      :open="Boolean(confirmAsset)"
      title="删除本地文件？"
      :description="confirmAsset ? `《${confirmAsset.title}》将从音乐库中永久删除。` : ''"
      confirm-label="删除"
      :busy="Boolean(deletingId)"
      @cancel="confirmAsset = null"
      @confirm="removeConfirmed"
    />
  </section>
</template>
