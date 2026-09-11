<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { health } from "../api";
import { formatUpdatedAt } from "../lib/format";
import type { HealthPayload } from "../types";

const payload = ref<HealthPayload | null>(null);
const error = ref("");

const statusLabel = computed(() => {
  const status = payload.value?.status;
  if (status === "ready") return { text: "就绪", klass: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300" };
  if (status === "degraded") return { text: "降级", klass: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300" };
  if (status === "starting") return { text: "启动中", klass: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300" };
  return { text: "读取中", klass: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300" };
});

onMounted(async () => {
  try {
    const res = await health();
    if (res.code === 0) {
      payload.value = res.data;
    } else {
      error.value = res.msg || "健康检查失败";
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : "健康检查失败";
  }
});
</script>

<template>
  <section>
    <div class="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight md:text-3xl">源状态</h1>
        <p class="mt-2 max-w-xl text-sm text-zinc-500">
          就绪表示各榜至少有过一次成功快照，过期请看 staleness，不把服务打回未就绪。
        </p>
      </div>
      <span class="rounded-full px-3 py-1 text-sm" :class="statusLabel.klass">
        {{ statusLabel.text }}
      </span>
    </div>

    <div class="mb-6 grid gap-3 sm:grid-cols-3">
      <article class="rounded-2xl bg-white p-4 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-white/10">
        <div class="text-xs text-zinc-500">状态</div>
        <div class="mt-1 font-mono text-xl">{{ payload?.status ?? "..." }}</div>
      </article>
      <article class="rounded-2xl bg-white p-4 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-white/10">
        <div class="text-xs text-zinc-500">数据源</div>
        <div class="mt-1 text-xl">{{ payload?.sources.length ?? 0 }}</div>
      </article>
      <article class="rounded-2xl bg-white p-4 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-white/10">
        <div class="text-xs text-zinc-500">过期倍率</div>
        <div class="mt-1 text-xl">{{ payload?.staleness_multiplier ?? "-" }}</div>
      </article>
    </div>

    <p v-if="error" class="mb-4 text-sm text-rose-500">{{ error }}</p>

    <div class="grid gap-3 md:grid-cols-2">
      <article
        v-for="source in payload?.sources ?? []"
        :key="source.board_id"
        class="rounded-2xl bg-white p-4 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-white/10"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="font-medium">{{ source.name }}</div>
          <span class="text-xs text-zinc-500">{{ source.platform }}</span>
        </div>
        <dl class="mt-3 grid grid-cols-3 gap-2 text-sm">
          <div>
            <dt class="text-xs text-zinc-500">连续失败</dt>
            <dd>{{ source.consecutive_failures }}</dd>
          </div>
          <div>
            <dt class="text-xs text-zinc-500">延迟</dt>
            <dd>{{ source.last_latency_ms ?? "-" }} ms</dd>
          </div>
          <div>
            <dt class="text-xs text-zinc-500">条数</dt>
            <dd>{{ source.last_item_count ?? "-" }}</dd>
          </div>
        </dl>
        <div v-if="source.last_error" class="mt-3 text-sm text-rose-500">
          {{ source.last_error }}
        </div>
        <div class="mt-3 text-xs text-zinc-500">
          上次成功 {{ formatUpdatedAt(source.last_success_at) }}
        </div>
      </article>
      <article
        v-if="!payload?.sources.length"
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
