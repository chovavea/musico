<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
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

let pending: {
  key: string;
  pointerId: number;
  startX: number;
  startY: number;
  grabY: number;
  isTouch: boolean;
  timer: number;
} | null = null;

const canDrag = computed(() => !query.value.trim());

function isSongChart(chart: CatalogChart): boolean {
  if (chart.playable === false) return false;
  const name = chart.name.toUpperCase();
  return !name.includes("MV") && !name.includes("视频榜") && !name.includes("专辑榜") && !name.includes("歌手榜");
}

const ordered = computed(() => {
  const items: CatalogChart[] = [];
  for (const group of props.groups) {
    for (const chart of group.charts) {
      if (isSongChart(chart)) items.push(chart);
    }
  }
  items.sort((a, b) => (a.sort_order ?? 10_000) - (b.sort_order ?? 10_000));
  return items;
});

const filtered = computed(() => {
  const needle = query.value.trim().toLowerCase();
  return props.groups
    .map((group) => ({
      ...group,
      charts: group.charts
        .filter((chart) => isSongChart(chart) && (!needle || chart.name.toLowerCase().includes(needle)))
        .slice()
        .sort((a, b) => (a.sort_order ?? 10_000) - (b.sort_order ?? 10_000)),
    }))
    .filter((group) => group.charts.length);
});

function groupOf(key: string): CatalogGroup | undefined {
  return filtered.value.find((group) => group.charts.some((chart) => chart.key === key));
}

function originalIndex(group: CatalogGroup, key: string): number {
  return group.charts.findIndex((chart) => chart.key === key);
}

type DisplayRow = { type: "ph" } | { type: "chart"; chart: CatalogChart };

function displayRows(group: CatalogGroup): DisplayRow[] {
  if (!lifted.value || !draggingKey.value || groupOf(draggingKey.value)?.name !== group.name) {
    return group.charts.map((chart) => ({ type: "chart", chart }));
  }
  const rows: DisplayRow[] = group.charts
    .filter((chart) => chart.key !== draggingKey.value)
    .map((chart) => ({ type: "chart", chart }));
  const idx = Math.max(0, Math.min(insertAt.value, rows.length));
  rows.splice(idx, 0, { type: "ph" });
  return rows;
}

function beforeKeyForDrop(group: CatalogGroup, movingKey: string, index: number): string | null {
  const rest = group.charts.filter((chart) => chart.key !== movingKey);
  const nextInGroup = rest[index];
  if (nextInGroup) return nextInGroup.key;
  const remaining = ordered.value.map((chart) => chart.key).filter((key) => key !== movingKey);
  if (!rest.length) {
    const current = ordered.value.findIndex((chart) => chart.key === movingKey);
    return ordered.value[current + 1]?.key ?? null;
  }
  const last = rest[rest.length - 1].key;
  const lastPos = remaining.indexOf(last);
  return lastPos >= 0 ? remaining[lastPos + 1] ?? null : null;
}

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

function insertIndexFromY(group: CatalogGroup, clientY: number): number {
  if (!listEl.value) return 0;
  const others = [
    ...listEl.value.querySelectorAll<HTMLElement>(
      `[data-group-name="${CSS.escape(group.name)}"][data-chart-key]`,
    ),
  ];
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
  const group = groupOf(chart.key);
  if (!group) return;
  lifted.value = true;
  draggingKey.value = chart.key;
  insertAt.value = originalIndex(group, chart.key);
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
      const chart = ordered.value.find((item) => item.key === pending?.key);
      if (chart) activateLift(chart, event.clientY);
    }
    return;
  }

  event.preventDefault();
  ghost.value = { ...ghost.value, top: event.clientY - pending.grabY };
  const group = groupOf(draggingKey.value);
  if (!group) return;
  autoScroll(event.clientY);
  const next = insertIndexFromY(group, event.clientY);
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
  const group = groupOf(draggingKey.value);
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
  if (!group || !didMove || index < 0) return;
  const from = originalIndex(group, key);
  if (index === from) return;
  emit("reorder", key, beforeKeyForDrop(group, key, index));
}

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
        class="max-h-80 overflow-y-auto py-1"
        :class="lifted ? 'select-none' : ''"
      >
        <div v-for="group in filtered" :key="group.name" class="px-1 py-1">
          <p class="px-3 py-1 text-xs text-zinc-400">{{ group.name }}</p>
          <TransitionGroup name="chart-sort" tag="div">
            <div
              v-for="row in displayRows(group)"
              :key="row.type === 'ph' ? `ph-${group.name}` : row.chart.key"
              class="flex min-h-11 items-center rounded-xl px-3 text-sm"
              :data-group-name="row.type === 'chart' ? group.name : undefined"
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
                <span class="truncate">{{ row.chart.name }}</span>
                <span v-if="!row.chart.playable" class="ml-auto shrink-0 text-xs">非歌曲</span>
              </template>
            </div>
          </TransitionGroup>
        </div>
        <p v-if="!filtered.length" class="px-3 py-6 text-center text-sm text-zinc-500">没有匹配的榜</p>
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
