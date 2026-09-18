<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { getApiToken, setApiToken } from "../api";
import { downloadErrorLabel } from "../lib/status-labels";
import { useHealthStore } from "../stores/health";
import { useThemeStore, type StyleThemeId } from "../stores/theme";
import { useDownloadsStore } from "../stores/downloads";
import AppIcon from "./AppIcon.vue";

withDefaults(
  defineProps<{
    variant?: "menu" | "avatar";
  }>(),
  { variant: "menu" },
);

const theme = useThemeStore();
const health = useHealthStore();
const downloads = useDownloadsStore();
const route = useRoute();
const open = ref(false);
const root = ref<HTMLElement | null>(null);
const trigger = ref<HTMLButtonElement | null>(null);
const apiToken = ref("");
const tokenSaved = ref(false);
let tokenSavedTimer = 0;

const statusLabel = computed(() => {
  if (health.error) return "异常";
  const status = health.payload?.status;
  if (status === "ready") return "就绪";
  if (status === "degraded") return "降级";
  if (status === "starting") return "启动中";
  return "读取中";
});

const styleIndicator = computed(() => {
  const count = theme.styleThemes.length;
  const index = theme.styleThemes.findIndex((item) => item.id === theme.styleTheme);
  return {
    left: `calc(3px + ${Math.max(index, 0)} * ((100% - 6px) / ${count}))`,
    width: `calc((100% - 6px) / ${count})`,
  };
});

function onDocClick(event: MouseEvent) {
  if (!root.value?.contains(event.target as Node)) {
    open.value = false;
  }
}

function onDocKey(event: KeyboardEvent) {
  if (event.key === "Escape" && open.value) {
    open.value = false;
    trigger.value?.focus();
  }
}

function choose(mode: "system" | "light" | "dark") {
  if (mode === "system") {
    theme.followSystem();
  } else {
    theme.setDark(mode === "dark");
  }
}

function chooseStyle(id: StyleThemeId) {
  theme.setStyleTheme(id);
}

function loadApiToken() {
  apiToken.value = getApiToken();
}

function saveApiToken() {
  setApiToken(apiToken.value);
  apiToken.value = getApiToken();
  tokenSaved.value = true;
  window.clearTimeout(tokenSavedTimer);
  tokenSavedTimer = window.setTimeout(() => {
    tokenSaved.value = false;
  }, 2000);
}

function toggle() {
  open.value = !open.value;
  if (open.value) {
    loadApiToken();
    // 空闲时轮询已停止；打开菜单时刷新一次任务/曲库计数。
    void downloads.refreshSummary();
    if (!downloads.libraryLoaded) void downloads.loadLibrary();
  }
}

onMounted(() => {
  document.addEventListener("click", onDocClick);
  document.addEventListener("keydown", onDocKey);
  loadApiToken();
  void downloads.refreshSummary();
  if (!downloads.libraryLoaded) void downloads.loadLibrary();
  downloads.startPolling();
});
onUnmounted(() => {
  document.removeEventListener("click", onDocClick);
  document.removeEventListener("keydown", onDocKey);
  window.clearTimeout(tokenSavedTimer);
  downloads.stopPolling();
});
</script>

<template>
  <div ref="root" class="relative">
    <button
      ref="trigger"
      type="button"
      :class="
        variant === 'avatar'
          ? 'gz-avatar grid place-items-center'
          : [
              'grid h-11 w-11 place-items-center rounded-full text-zinc-500 ring-1 ring-zinc-300 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:ring-white/15 dark:hover:bg-white/10 dark:hover:text-white',
              open ? 'bg-zinc-100 text-zinc-900 dark:bg-white/10 dark:text-white' : '',
            ]
      "
      :aria-expanded="open"
      aria-controls="settings-menu"
      aria-haspopup="dialog"
      aria-label="配置"
      @click.stop="toggle()"
    >
      <svg
        v-if="variant === 'avatar' && !downloads.active"
        viewBox="0 0 40 40"
        class="h-full w-full"
        aria-hidden="true"
      >
        <defs>
          <linearGradient id="gz-avatar-bg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#f5d0c5" />
            <stop offset="100%" stop-color="#d4b5a0" />
          </linearGradient>
        </defs>
        <rect width="40" height="40" fill="url(#gz-avatar-bg)" />
        <ellipse cx="20" cy="24" rx="11" ry="10" fill="#c4a484" />
        <circle cx="12" cy="14" r="5.2" fill="#b08968" />
        <circle cx="28" cy="14" r="5.2" fill="#b08968" />
        <circle cx="20" cy="22" r="8.5" fill="#e7c7a8" />
        <ellipse cx="16.2" cy="22.2" rx="1.1" ry="1.5" fill="#3f2a1d" />
        <ellipse cx="23.8" cy="22.2" rx="1.1" ry="1.5" fill="#3f2a1d" />
        <path d="M18.4 26.2c1.2 1.1 2.2 1.1 3.2 0" stroke="#a1624a" stroke-width="1.2" stroke-linecap="round" />
        <path d="M20 23.4v2.1" stroke="#c08457" stroke-width="1.1" stroke-linecap="round" />
      </svg>
      <AppIcon v-else-if="!downloads.active" name="menu" :size="20" />
      <svg v-else viewBox="0 0 36 36" class="h-7 w-7 -rotate-90" aria-hidden="true">
        <circle cx="18" cy="18" r="14" fill="none" stroke="currentColor" stroke-opacity=".18" stroke-width="3" />
        <circle cx="18" cy="18" r="14" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" :stroke-dasharray="`${downloads.percent * 0.8796} 87.96`" />
      </svg>
    </button>
    <div
      v-if="downloads.failureNotice || downloads.actionError"
      class="absolute right-0 top-full z-40 mt-2 w-72 space-y-3 rounded-xl bg-rose-50 p-3 text-sm text-rose-700 shadow-lg ring-1 ring-rose-200 dark:bg-rose-950 dark:text-rose-200 dark:ring-rose-500/30"
      role="alert"
    >
      <div v-if="downloads.actionError" class="flex items-start gap-2">
        <div class="min-w-0 flex-1">
          <div class="font-medium">下载操作失败</div>
          <div class="mt-1 break-words text-xs">{{ downloadErrorLabel(downloads.actionError) || downloads.actionError }}</div>
        </div>
        <button
          type="button"
          class="grid h-7 w-7 shrink-0 place-items-center rounded-full hover:bg-rose-100 dark:hover:bg-rose-900"
          aria-label="关闭提示"
          title="关闭提示"
          @click="downloads.clearActionError()"
        >
          <AppIcon name="close" :size="15" />
        </button>
      </div>
      <div v-if="downloads.failureNotice" class="flex items-start gap-2">
        <div class="min-w-0 flex-1">
          <div class="font-medium">下载失败</div>
          <div class="mt-1 truncate text-xs">{{ downloads.failureNotice.title || "未知歌曲" }}</div>
          <div
            v-if="downloads.fallbackPending[downloads.failureNotice.id]"
            class="mt-1 text-xs"
            aria-live="polite"
          >
            正在查找网盘链接…
          </div>
          <a
            v-if="downloads.failureNotice.source_page_url"
            :href="downloads.failureNotice.source_page_url"
            target="_blank"
            rel="noreferrer"
            class="mt-2 inline-flex text-xs underline"
          >去源网站</a>
        </div>
        <button
          type="button"
          class="grid h-7 w-7 shrink-0 place-items-center rounded-full hover:bg-rose-100 dark:hover:bg-rose-900"
          aria-label="关闭提示"
          title="关闭提示"
          @click="downloads.failureNotice = null"
        >
          <AppIcon name="close" :size="15" />
        </button>
      </div>
    </div>
    <div
      v-if="open"
      id="settings-menu"
      class="menu-popover absolute right-0 top-full z-30 mt-1.5 w-72 rounded-2xl bg-white p-1.5 shadow-lg ring-1 ring-zinc-200/80 dark:bg-zinc-900 dark:ring-white/10"
      role="dialog"
      aria-label="配置"
    >
      <div class="flex h-11 items-center gap-2 px-2">
        <span class="shrink-0 text-sm">外观</span>
        <div
          class="relative ml-auto grid min-w-0 grid-cols-3 rounded-full bg-zinc-100 p-[3px] dark:bg-zinc-800"
          role="group"
          aria-label="外观"
        >
          <span
            class="pointer-events-none absolute top-[3px] bottom-[3px] w-[calc(33.333%-2px)] rounded-full bg-white ring-1 ring-black/[0.04] transition-[left] duration-200 ease-[cubic-bezier(0.2,0.8,0.2,1)] dark:bg-zinc-600 dark:ring-white/10"
            :style="{ left: theme.preference === 'system' ? '3px' : theme.preference === 'light' ? '33.333%' : '66.666%' }"
          />
          <button
            type="button"
            class="relative z-10 h-8 min-w-[3rem] rounded-full px-2 text-xs"
            :class="theme.preference === 'system' ? 'font-medium text-zinc-900 dark:text-white' : 'text-zinc-500 dark:text-zinc-400'"
            :aria-pressed="theme.preference === 'system'"
            @click="choose('system')"
          >
            跟随
          </button>
          <button
            type="button"
            class="relative z-10 h-8 min-w-[3rem] rounded-full px-2 text-xs"
            :class="theme.preference === 'light' ? 'font-medium text-zinc-900 dark:text-white' : 'text-zinc-500 dark:text-zinc-400'"
            :aria-pressed="theme.preference === 'light'"
            @click="choose('light')"
          >
            浅色
          </button>
          <button
            type="button"
            class="relative z-10 h-8 min-w-[3rem] rounded-full px-2 text-xs"
            :class="theme.preference === 'dark' ? 'font-medium text-zinc-900 dark:text-white' : 'text-zinc-500 dark:text-zinc-400'"
            :aria-pressed="theme.preference === 'dark'"
            @click="choose('dark')"
          >
            深色
          </button>
        </div>
      </div>
      <div class="flex h-11 items-center gap-2 px-2">
        <span class="shrink-0 text-sm">主题</span>
        <div
          class="relative ml-auto grid min-w-0 rounded-full bg-zinc-100 p-[3px] dark:bg-zinc-800"
          :style="{ gridTemplateColumns: `repeat(${theme.styleThemes.length}, minmax(0, 1fr))` }"
          role="group"
          aria-label="页面样式主题"
        >
          <span
            class="pointer-events-none absolute top-[3px] bottom-[3px] rounded-full bg-white ring-1 ring-black/[0.04] transition-[left] duration-200 ease-[cubic-bezier(0.2,0.8,0.2,1)] dark:bg-zinc-600 dark:ring-white/10"
            :style="styleIndicator"
          />
          <button
            v-for="item in theme.styleThemes"
            :key="item.id"
            type="button"
            class="relative z-10 h-8 min-w-[3rem] rounded-full px-2 text-xs"
            :class="theme.styleTheme === item.id ? 'font-medium text-zinc-900 dark:text-white' : 'text-zinc-500 dark:text-zinc-400'"
            :aria-pressed="theme.styleTheme === item.id"
            @click="chooseStyle(item.id)"
          >
            {{ item.name }}
          </button>
        </div>
      </div>
      <div class="flex h-11 items-center gap-2 px-2">
        <label class="shrink-0 text-sm" for="settings-api-token">令牌</label>
        <input
          id="settings-api-token"
          v-model="apiToken"
          type="password"
          class="ml-auto h-8 w-28 min-w-0 rounded-lg bg-zinc-100 px-2 text-xs outline-none focus:ring-1 focus:ring-zinc-400 dark:bg-zinc-800 dark:text-zinc-100 dark:focus:ring-white/20"
          placeholder="API_TOKEN"
          autocomplete="off"
          title="与 .env 里的 API_TOKEN 相同：写操作、曲库与下载记录都需要它"
          @keydown.enter.prevent="saveApiToken()"
        />
        <button
          type="button"
          class="h-8 shrink-0 rounded-lg bg-zinc-100 px-2 text-xs hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700"
          :aria-label="tokenSaved ? '已保存 API Token' : '保存 API Token'"
          @click="saveApiToken()"
        >
          {{ tokenSaved ? "已保存" : "保存" }}
        </button>
      </div>
      <div class="mx-2 h-px bg-zinc-100 dark:bg-white/10" role="separator" />
      <RouterLink
        to="/library"
        class="flex h-11 items-center gap-2 rounded-xl px-2 text-sm hover:bg-zinc-100 dark:hover:bg-white/10"
        :class="route.name === 'library' ? 'bg-zinc-100 dark:bg-white/10' : ''"
        @click="open = false"
      >
        <span class="shrink-0">音乐库</span>
        <span class="ml-auto text-xs text-zinc-500 dark:text-zinc-400">
          {{ downloads.active ? `${downloads.percent}%` : `${downloads.assetCount} 首` }}
        </span>
        <AppIcon name="chevron-right" :size="15" class="text-zinc-500" />
      </RouterLink>
      <RouterLink
        to="/boards"
        class="flex h-11 items-center gap-2 rounded-xl px-2 text-sm hover:bg-zinc-100 dark:hover:bg-white/10"
        :class="route.name === 'boards' ? 'bg-zinc-100 dark:bg-white/10' : ''"
        @click="open = false"
      >
        <span class="shrink-0">榜单管理</span>
        <AppIcon name="chevron-right" :size="15" class="ml-auto text-zinc-500" />
      </RouterLink>
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
        <AppIcon name="chevron-right" :size="15" class="text-zinc-500" />
      </RouterLink>
    </div>
  </div>
</template>
