<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import type { CatalogChart, CatalogGroup } from "../types";

const props = defineProps<{
  name: string;
  chartKey: string;
  groups: CatalogGroup[];
}>();

const emit = defineEmits<{
  select: [key: string];
  reorder: [key: string, beforeKey: string | null];
}>();

/** Apple HIG: drag image after ~3pt. dnd-kit: mouse 5px, touch 200–250ms delay. */
const MOUSE_DISTANCE = 5;
const TOUCH_DELAY_MS = 220;
const TOUCH_TOLERANCE = 10;

const open = ref(false);
const query = ref("");
const root = ref<HTMLElement | null>(null);
const listEl = ref<HTMLElement | null>(null);
const draggingKey = ref("");
const insertAt = ref(-1);
const lifted = ref(false);
const moved = ref(false);
const ignoreClickUntil = ref(0);
const rowHeight = ref(44);
const ghost = ref({ top: 0, left: 0, width: 0, name: "", selected: false });
/** 乐观提交：拖放后到接口返回前，列表以该顺序展示。 */
const localKeys = ref<string[] | null>(null);
const saving = ref(false);

let pending: {
  key: string;
  pointerId: number;
  startX: number;
  startY: number;
  grabY: number;
  isTouch: boolean;
  timer: number;
} | null = null;

const canDrag = computed(() => !query.value.trim() && !saving.value);

function isSongChart(chart: CatalogChart): boolean {
  if (chart.playable === false) return false;
  const name = chart.name.toUpperCase();
  return !name.includes("MV") && !name.includes("视频榜") && !name.includes("专辑榜") && !name.includes("歌手榜");
}

const ordered = computed(() => {
  const byKey = new Map<string, CatalogChart>();
  const fallback: CatalogChart[] = [];
  for (const group of props.groups) {
    for (const chart of group.charts) {
      if (!isSongChart(chart)) continue;
      byKey.set(chart.key, chart);
      fallback.push(chart);
    }
  }
  if (localKeys.value) {
    const items: CatalogChart[] = [];
    for (const key of localKeys.value) {
      const chart = byKey.get(key);
      if (chart) items.push(chart);
    }
    for (const chart of fallback) {
      if (!localKeys.value.includes(chart.key)) items.push(chart);
    }
    return items;
  }
  fallback.sort((a, b) => (a.sort_order ?? 10_000) - (b.sort_order ?? 10_000));
  return fallback;
});

const groupLabelByKey = computed(() => {
  const map = new Map<string, string>();
  for (const group of props.groups) {
    for (const chart of group.charts) {
      if (isSongChart(chart)) map.set(chart.key, group.name);
    }
  }
  return map;
});

const visibleCharts = computed(() => {
  const needle = query.value.trim().toLowerCase();
  return ordered.value.filter((chart) => !needle || chart.name.toLowerCase().includes(needle));
});

type DisplayRow = { type: "ph" } | { type: "chart"; chart: CatalogChart };

const displayRows = computed<DisplayRow[]>(() => {
  if (!lifted.value || !draggingKey.value) {
    return visibleCharts.value.map((chart) => ({ type: "chart", chart }));
  }
  const rows: DisplayRow[] = visibleCharts.value
    .filter((chart) => chart.key !== draggingKey.value)
    .map((chart) => ({ type: "chart", chart }));
  const idx = Math.max(0, Math.min(insertAt.value, rows.length));
  rows.splice(idx, 0, { type: "ph" });
  return rows;
});

function onDocClick(event: MouseEvent) {
  if (lifted.value || Date.now() < ignoreClickUntil.value) return;
  if (!root.value?.contains(event.target as Node)) {
    open.value = false;
  }
}

function choose(key: string, playable: boolean) {
  if (!playable) return;
  if (lifted.value || moved.value || Date.now() < ignoreClickUntil.value) return;
  emit("select", key);
  open.value = false;
  query.value = "";
}

function isCurrent(key: string): boolean {
  return key === props.chartKey;
}

function layoutTop(el: HTMLElement): number {
  const transform = getComputedStyle(el).transform;
  let shift = 0;
  if (transform && transform !== "none") {
    try {
      shift = new DOMMatrixReadOnly(transform).m42;
    } catch {
      shift = 0;
    }
  }
  return el.getBoundingClientRect().top - shift;
}

function insertIndexFromY(clientY: number): number {
  if (!listEl.value) return 0;
  const others = [...listEl.value.querySelectorAll<HTMLElement>("[data-chart-key]")];
  for (let i = 0; i < others.length; i += 1) {
    const top = layoutTop(others[i]);
    if (clientY < top + rowHeight.value / 2) return i;
  }
  return others.length;
}

function autoScroll(clientY: number) {
  const box = listEl.value;
  if (!box) return;
  const rect = box.getBoundingClientRect();
  if (clientY < rect.top + 36) box.scrollTop -= 14;
  if (clientY > rect.bottom - 36) box.scrollTop += 14;
}

function bindWindow() {
  window.addEventListener("pointermove", onWindowMove, { passive: false, capture: true });
  window.addEventListener("pointerup", onWindowUp, { capture: true });
  window.addEventListener("pointercancel", onWindowUp, { capture: true });
}

function unbindWindow() {
  window.removeEventListener("pointermove", onWindowMove, true);
  window.removeEventListener("pointerup", onWindowUp, true);
  window.removeEventListener("pointercancel", onWindowUp, true);
}

function activateLift(chart: CatalogChart, clientY: number) {
  if (!pending) return;
  lifted.value = true;
  draggingKey.value = chart.key;
  insertAt.value = visibleCharts.value.findIndex((item) => item.key === chart.key);
  moved.value = false;
  ghost.value = {
    ...ghost.value,
    top: clientY - pending.grabY,
    name: chart.name,
    selected: isCurrent(chart.key),
  };
  try {
    navigator.vibrate?.(12);
  } catch {
    /* ignore */
  }
  if (listEl.value) listEl.value.classList.add("touch-none");
}

function onRowDown(chart: CatalogChart, event: PointerEvent) {
  if (!canDrag.value || !chart.playable) return;
  if ((event.target as HTMLElement).closest("input")) return;
  const row = event.currentTarget as HTMLElement;
  const rect = row.getBoundingClientRect();
  rowHeight.value = rect.height;
  pending = {
    key: chart.key,
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    grabY: event.clientY - rect.top,
    isTouch: event.pointerType === "touch",
    timer: 0,
  };
  ghost.value = {
    top: rect.top,
    left: rect.left,
    width: rect.width,
    name: chart.name,
    selected: isCurrent(chart.key),
  };
  bindWindow();
  if (pending.isTouch) {
    pending.timer = window.setTimeout(() => {
      if (!pending || pending.key !== chart.key) return;
      activateLift(chart, pending.startY);
    }, TOUCH_DELAY_MS);
  }
}

function onWindowMove(event: PointerEvent) {
  if (!pending || event.pointerId !== pending.pointerId) return;
  const dx = event.clientX - pending.startX;
  const dy = event.clientY - pending.startY;
  const dist = Math.hypot(dx, dy);

  if (!lifted.value) {
    if (pending.isTouch) {
      if (dist > TOUCH_TOLERANCE) {
        window.clearTimeout(pending.timer);
        unbindWindow();
        pending = null;
      }
      return;
    }
    if (dist >= MOUSE_DISTANCE) {
      const chart = visibleCharts.value.find((item) => item.key === pending?.key);
      if (chart) activateLift(chart, event.clientY);
    }
    return;
  }

  event.preventDefault();
  ghost.value = { ...ghost.value, top: event.clientY - pending.grabY };
  autoScroll(event.clientY);
  const next = insertIndexFromY(event.clientY);
  if (next !== insertAt.value) {
    insertAt.value = next;
    moved.value = true;
  } else if (Math.abs(dy) > MOUSE_DISTANCE) {
    moved.value = true;
  }
}

function onWindowUp(event: PointerEvent) {
  if (!pending || event.pointerId !== pending.pointerId) return;
  window.clearTimeout(pending.timer);
  unbindWindow();
  listEl.value?.classList.remove("touch-none");
  const key = draggingKey.value;
  const index = insertAt.value;
  const didLift = lifted.value;
  const didMove = moved.value;
  pending = null;
  lifted.value = false;
  draggingKey.value = "";
  insertAt.value = -1;
  moved.value = false;
  if (!didLift) return;
  ignoreClickUntil.value = Date.now() + 400;
  if (!didMove || index < 0 || !key) return;
  const from = ordered.value.findIndex((chart) => chart.key === key);
  if (index === from) return;
  const rest = ordered.value.filter((chart) => chart.key !== key);
  const commitIndex = Math.max(0, Math.min(index, rest.length));
  const next = rest[commitIndex];
  // 乐观提交：先把本地顺序落到拖放位置，接口确认后由 watch(groups) 接管。
  localKeys.value = [
    ...rest.slice(0, commitIndex).map((chart) => chart.key),
    key,
    ...rest.slice(commitIndex).map((chart) => chart.key),
  ];
  saving.value = true;
  emit("reorder", key, next ? next.key : null);
}

watch(
  () => props.groups,
  () => {
    localKeys.value = null;
    saving.value = false;
  },
);

onMounted(() => document.addEventListener("click", onDocClick));
onUnmounted(() => {
  document.removeEventListener("click", onDocClick);
  unbindWindow();
  if (pending) window.clearTimeout(pending.timer);
});
</script>

<template>
  <div ref="root" class="relative min-w-0">
    <button
      type="button"
      class="inline-flex min-h-11 max-w-full items-center gap-1 rounded-full px-1 text-left text-lg font-semibold hover:bg-zinc-100 dark:hover:bg-white/10"
      :aria-expanded="open"
      @click="open = !open"
    >
      <span class="truncate">{{ name }}</span>
      <span class="text-sm text-zinc-400" aria-hidden="true">▾</span>
    </button>
    <div
      v-if="open"
      class="absolute left-0 top-full z-30 mt-1 w-[min(100vw-2rem,22rem)] overflow-hidden rounded-2xl bg-white shadow-xl ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-white/10"
    >
      <div class="border-b border-zinc-100 p-2 dark:border-white/10">
        <input
          v-model="query"
          type="search"
          placeholder="搜索榜单"
          class="h-11 w-full rounded-full bg-zinc-100 px-3 text-sm outline-none dark:bg-zinc-800"
        />
      </div>
      <div
        ref="listEl"
        class="max-h-80 overflow-y-auto px-1 py-1"
        :class="lifted ? 'select-none' : ''"
      >
        <TransitionGroup name="chart-sort" tag="div">
          <div
            v-for="row in displayRows"
            :key="row.type === 'ph' ? 'ph' : row.chart.key"
            class="flex min-h-11 items-center gap-2 rounded-xl px-3 text-sm"
            :data-chart-key="row.type === 'chart' ? row.chart.key : undefined"
            :class="
              row.type === 'ph'
                ? 'bg-zinc-100 dark:bg-white/10'
                : [
                    'chart-sort-row',
                    isCurrent(row.chart.key)
                      ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900'
                      : 'hover:bg-zinc-100 dark:hover:bg-white/10',
                    canDrag && row.chart.playable ? 'cursor-grab' : '',
                    lifted ? 'cursor-grabbing' : '',
                    !row.chart.playable ? 'cursor-not-allowed text-zinc-400' : '',
                  ]
            "
            :style="row.type === 'ph' ? { height: `${rowHeight}px` } : undefined"
            @pointerdown="row.type === 'chart' && onRowDown(row.chart, $event)"
            @click="row.type === 'chart' && choose(row.chart.key, row.chart.playable)"
          >
            <template v-if="row.type === 'chart'">
              <span class="min-w-0 truncate">{{ row.chart.name }}</span>
              <span
                class="ml-auto shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium leading-4 ring-1 ring-inset"
                :class="
                  isCurrent(row.chart.key)
                    ? 'bg-white/10 text-zinc-300 ring-white/20 dark:bg-zinc-900/10 dark:text-zinc-500 dark:ring-zinc-900/20'
                    : 'bg-zinc-100 text-zinc-500 ring-zinc-200/70 dark:bg-white/5 dark:text-zinc-400 dark:ring-white/10'
                "
              >
                {{ groupLabelByKey.get(row.chart.key) ?? '' }}
              </span>
            </template>
          </div>
        </TransitionGroup>
        <p v-if="!visibleCharts.length" class="px-3 py-6 text-center text-sm text-zinc-500">没有匹配的榜</p>
      </div>
    </div>
    <Teleport to="body">
      <div
        v-if="lifted"
        class="pointer-events-none fixed z-[80] flex min-h-11 items-center rounded-xl px-3 text-sm shadow-2xl ring-1 ring-black/10 dark:ring-white/15"
        :class="
          ghost.selected
            ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900'
            : 'bg-white text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100'
        "
        :style="{
          top: `${ghost.top}px`,
          left: `${ghost.left}px`,
          width: `${ghost.width}px`,
          transform: 'scale(1.04)',
          opacity: 0.88,
        }"
      >
        <span class="truncate">{{ ghost.name }}</span>
      </div>
    </Teleport>
  </div>
</template>
