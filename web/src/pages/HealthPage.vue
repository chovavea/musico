<script setup lang="ts">
import { computed, onMounted } from "vue";
import { storeToRefs } from "pinia";
import AppIcon from "../components/AppIcon.vue";
import PageHeader from "../components/PageHeader.vue";
import { platformLabel } from "../lib/boards";
import { formatUpdatedAt } from "../lib/format";
import { useHealthStore } from "../stores/health";

const healthStore = useHealthStore();
const { payload, error, loading, lastRefreshedAt } = storeToRefs(healthStore);
const statusLabel = computed(() => {
  const status = payload.value?.status;
  if (status === "ready") return { text: "就绪", klass: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300" };
  if (status === "degraded") return { text: "降级", klass: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300" };
  if (status === "starting") return { text: "启动中", klass: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300" };
  return { text: "读取中", klass: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300" };
});

onMounted(async () => {
  await healthStore.refresh();
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
        <div class="text-xs text-secondary">过期阈值</div>
        <div class="mt-1 text-xl">{{ payload?.staleness_multiplier ?? "-" }}</div>
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
  </section>
</template>
