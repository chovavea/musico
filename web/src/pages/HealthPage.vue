<script setup lang="ts">
import { computed, onMounted, watch } from "vue";
import { storeToRefs } from "pinia";
import AppIcon from "../components/AppIcon.vue";
import PageHeader from "../components/PageHeader.vue";
import { platformLabel } from "../lib/boards";
import { formatUpdatedAt } from "../lib/format";
import { downloadErrorLabel } from "../lib/status-labels";
import { useHealthStore } from "../stores/health";
import { usePreviewFailureStore } from "../stores/previewFailures";

const healthStore = useHealthStore();
const previewFailures = usePreviewFailureStore();
const { payload, error, loading, lastRefreshedAt } = storeToRefs(healthStore);
const { entries: previewFailureEntries, unseenCount: previewFailureCount } = storeToRefs(previewFailures);

// 下载兜底目前只读展示：它记录下载失败与兜底跳转结果，但不参与 healthScore。
// TODO(health-score): 后续把兜底当成一个“源”纳入评分（见 ../lib/healthScore.ts）。
const fallback = computed(() => payload.value?.fallback ?? null);
const downloadSources = computed(() => payload.value?.download_sources ?? []);
const fallbackSuccessCount = computed(
  () => fallback.value?.counts["fallback_request:jumped"] ?? 0,
);
const fallbackLastFailure = computed(() =>
  fallback.value?.last_failure_at ? eventTime(fallback.value.last_failure_at) : "无记录",
);
const OUTCOME_LABELS: Record<string, string> = {
  jumped: "已跳转网盘",
  no_wav: "无 WAV 音质",
  not_found: "站点无此曲",
  unreachable: "站点不可达",
  no_share_link: "未取到分享链接",
  disabled: "兜底未启用",
  not_failed: "任务未失败",
  failed: "下载失败",
};

function outcomeLabel(outcome: string): string {
  return OUTCOME_LABELS[outcome] ?? outcome;
}

function outcomeClass(outcome: string): string {
  return outcome === "jumped" ? "text-emerald-600 dark:text-emerald-400" : "text-rose-500";
}

// 兜底事件是「失败记录」而不是榜单更新，用绝对时间更贴切。
function eventTime(iso: string): string {
  const stamp = Date.parse(iso);
  if (Number.isNaN(stamp)) return "-";
  return new Date(stamp).toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const statusLabel = computed(() => {
  const status = payload.value?.status;
  if (status === "ready") return { text: "就绪", klass: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300" };
  if (status === "degraded") return { text: "降级", klass: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300" };
  if (status === "starting") return { text: "启动中", klass: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300" };
  return { text: "读取中", klass: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300" };
});

onMounted(async () => {
  previewFailures.markSeen();
  await healthStore.refresh();
});

watch(previewFailureCount, (count) => {
  if (count > 0) previewFailures.markSeen();
});
</script>

<template>
  <section>
    <PageHeader
      title="源状态"
      eyebrow="系统"
      description="就绪表示所有榜单都曾成功更新；个别数据过期时，服务仍可继续使用。"
    >
      <template #actions>
        <span v-if="lastRefreshedAt" class="text-xs text-secondary">
          {{ formatUpdatedAt(lastRefreshedAt) }}
        </span>
        <span class="rounded-full px-3 py-1 text-sm" :class="statusLabel.klass">
          {{ statusLabel.text }}
        </span>
        <button
          type="button"
          class="grid h-11 w-11 place-items-center rounded-full ring-1 ring-zinc-300 hover:bg-zinc-100 disabled:opacity-60 dark:ring-white/15 dark:hover:bg-white/10"
          :disabled="loading"
          aria-label="刷新状态"
          @click="healthStore.refresh()"
        >
          <AppIcon :name="loading ? 'spinner' : 'refresh'" :size="18" />
        </button>
      </template>
    </PageHeader>

    <div class="mb-6 grid gap-3 sm:grid-cols-3">
      <article class="rounded-2xl bg-white p-4 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-white/10">
        <div class="text-xs text-secondary">状态</div>
        <div class="mt-1 text-xl">{{ statusLabel.text }}</div>
      </article>
      <article class="rounded-2xl bg-white p-4 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-white/10">
        <div class="text-xs text-secondary">数据源</div>
        <div class="mt-1 text-xl">{{ payload?.sources.length ?? 0 }}</div>
      </article>
      <article class="rounded-2xl bg-white p-4 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-white/10">
        <div class="text-xs text-secondary">下载源</div>
        <div class="mt-1 text-xl">{{ downloadSources.length }}</div>
        <div class="mt-1 truncate text-xs text-secondary">
          {{ downloadSources.length ? downloadSources.map((item) => item.name).join("、") : "未加载" }}
        </div>
      </article>
    </div>

    <div v-if="error" role="alert" class="mb-4 flex items-center justify-between gap-3 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:bg-rose-500/10 dark:text-rose-300">
      <span>{{ error }}</span>
      <button type="button" class="shrink-0 underline" @click="healthStore.refresh()">重试</button>
    </div>

    <div class="grid gap-3 md:grid-cols-2">
      <article
        v-for="source in payload?.sources ?? []"
        :key="source.board_id"
        class="rounded-2xl bg-white p-4 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-white/10"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="font-medium">{{ source.name }}</div>
          <span class="text-xs text-secondary">{{ platformLabel(source.platform) }}</span>
        </div>
        <dl class="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt class="text-xs text-secondary">连续失败</dt>
            <dd>{{ source.consecutive_failures }}</dd>
          </div>
          <div>
            <dt class="text-xs text-secondary">延迟</dt>
            <dd>{{ source.last_latency_ms ?? "-" }} ms</dd>
          </div>
          <div>
            <dt class="text-xs text-secondary">条数</dt>
            <dd>{{ source.last_item_count ?? "-" }}</dd>
          </div>
        </dl>
        <div v-if="source.last_error" class="mt-3 text-sm text-rose-500">
          {{ source.last_error }}
        </div>
        <div class="mt-3 text-xs text-secondary">
          上次成功 {{ formatUpdatedAt(source.last_success_at) }}
        </div>
      </article>
      <article
        v-if="loading && !payload?.sources.length"
        class="rounded-2xl bg-white p-6 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-white/10 md:col-span-2"
      >
        <div class="skel mb-3 h-5 w-32" />
        <div class="grid grid-cols-3 gap-3">
          <div class="skel h-10" />
          <div class="skel h-10" />
          <div class="skel h-10" />
        </div>
        <p class="mt-4 text-sm text-zinc-500">正在读取各榜健康状态</p>
      </article>
    </div>

    <article class="mt-6 rounded-2xl bg-white p-4 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-white/10">
      <div class="font-medium">试听失败</div>
      <p class="mt-1 text-xs text-secondary">
        播放整榜时，整段试听失败会自动换下一首。点某一首失败则停在当前这首。
      </p>
      <ul v-if="previewFailureEntries.length" class="mt-3 space-y-2">
        <li
          v-for="entry in previewFailureEntries"
          :key="entry.id"
          class="flex items-start justify-between gap-3 rounded-xl bg-zinc-50 px-3 py-2 dark:bg-white/5"
        >
          <div class="min-w-0">
            <div class="truncate text-sm">
              {{ entry.title || "未知歌曲" }}
              <span v-if="entry.artist" class="text-secondary">· {{ entry.artist }}</span>
            </div>
            <div class="mt-0.5 truncate text-xs text-secondary">
              {{ platformLabel(entry.platform) }} · {{ entry.reason }}
            </div>
          </div>
          <div class="shrink-0 text-xs text-secondary">{{ eventTime(entry.createdAt) }}</div>
        </li>
      </ul>
      <p v-else class="mt-3 text-sm text-secondary">还没有试听失败记录</p>
    </article>

    <!-- 下载兜底只读视图：只展示失败与跳转结果。
         TODO(health-score): 后续把兜底当成一个“源”纳入 healthScore 评分。 -->
    <article
      v-if="fallback"
      class="mt-6 rounded-2xl bg-white p-4 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-white/10"
    >
      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0">
          <div class="font-medium">下载兜底</div>
          <div class="mt-1 text-xs text-secondary">
            {{ fallback.source_name }}：下载失败时跳到外部网盘分享页，由用户自行下载
          </div>
        </div>
        <span
          class="shrink-0 rounded-full px-3 py-1 text-xs"
          :class="
            fallback.enabled
              ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'
              : 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300'
          "
        >
          {{ fallback.enabled ? "已启用" : "未启用" }}
        </span>
      </div>
      <dl class="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div>
          <dt class="text-xs text-secondary">下载失败</dt>
          <dd>{{ fallback.download_failed_total }}</dd>
        </div>
        <div>
          <dt class="text-xs text-secondary">兜底成功</dt>
          <dd>{{ fallbackSuccessCount }}</dd>
        </div>
        <div>
          <dt class="text-xs text-secondary">连续失败</dt>
          <dd>{{ fallback.consecutive_failures }}</dd>
        </div>
        <div>
          <dt class="text-xs text-secondary">最近失败</dt>
          <dd>{{ fallbackLastFailure }}</dd>
        </div>
      </dl>
      <ul v-if="fallback.events.length" class="mt-3 space-y-2">
        <li
          v-for="event in fallback.events"
          :key="event.id"
          class="flex items-start justify-between gap-3 rounded-xl bg-zinc-50 px-3 py-2 dark:bg-white/5"
        >
          <div class="min-w-0">
            <div class="truncate text-sm">
              {{ event.title || "未知歌曲" }}
              <span v-if="event.artist" class="text-secondary">· {{ event.artist }}</span>
            </div>
            <div class="mt-0.5 truncate text-xs text-secondary">
              {{ downloadErrorLabel(event.detail) || event.detail || event.trigger }}
            </div>
          </div>
          <div class="shrink-0 text-right">
            <div class="text-sm" :class="outcomeClass(event.outcome)">
              {{ outcomeLabel(event.outcome) }}
            </div>
            <div class="mt-0.5 text-xs text-secondary">{{ eventTime(event.created_at) }}</div>
          </div>
        </li>
      </ul>
      <p v-else class="mt-3 text-sm text-secondary">还没有兜底记录</p>
    </article>
  </section>
</template>
