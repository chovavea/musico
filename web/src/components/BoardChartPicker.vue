<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, useId, watch } from "vue";
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

/** Mouse: 5px to lift (whole row). Touch: drag only from the handle, follow immediately. */
const MOUSE_DISTANCE = 5;

const open = ref(false);
const query = ref("");
const root = ref<HTMLElement | null>(null);
const triggerEl = ref<HTMLButtonElement | null>(null);
const searchEl = ref<HTMLInputElement | null>(null);
const listEl = ref<HTMLElement | null>(null);
const listboxId = `board-chart-picker-${useId()}`;
const activeKey = ref("");
const draggingKey = ref("");
const insertAt = ref(-1);
const lifted = ref(false);
const moved = ref(false);
const ignoreClickUntil = ref(0);
const pressingKey = ref("");
const rowHeight = ref(44);
const ghostEl = ref<HTMLElement | null>(null);
const ghost = ref({ left: 0, width: 0, name: "", selected: false });
const coarsePointer = ref(false);
/** 乐观提交：拖放后到接口返回前，列表以该顺序展示。 */
const localKeys = ref<string[] | null>(null);
const saving = ref(false);

let pending: {
  key: string;
  pointerId: number;
  identifier: number;
  startX: number;
  startY: number;
  lastX: number;
  lastY: number;
  grabY: number;
  isTouch: boolean;
  claimed: boolean;
  row: HTMLElement;
} | null = null;
let dragRaf = 0;
let ghostY = 0;

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

const enabledVisibleCharts = computed(() => visibleCharts.value.filter((chart) => chart.playable));
const activeChart = computed(
  () =>
    visibleCharts.value.find((chart) => chart.key === activeKey.value) ??
    visibleCharts.value.find((chart) => isCurrent(chart.key)) ??
    null,
);

function listRect(): DOMRect | null {
  return listEl.value?.getBoundingClientRect() ?? null;
}

function clampInsertY(clientY: number): number {
  const box = listRect();
  if (!box) return clientY;
  return Math.max(box.top + 1, Math.min(box.bottom - 1, clientY));
}

function clampGhostTop(y: number): number {
  const box = listRect();
  if (!box) return y;
  return Math.max(box.top, Math.min(box.bottom - rowHeight.value, y));
}

function rowDragStyle(chart: CatalogChart): Record<string, string> | undefined {
  if (!lifted.value || !draggingKey.value) return undefined;
  const charts = visibleCharts.value;
  const from = charts.findIndex((item) => item.key === draggingKey.value);
  const i = charts.findIndex((item) => item.key === chart.key);
  if (from < 0 || i < 0) return undefined;
  const to = Math.max(0, Math.min(insertAt.value, charts.length - 1));
  const h = rowHeight.value;
  const style: Record<string, string> = {};
  if (i === from) {
    style.opacity = "0";
    style.pointerEvents = "none";
  }
  let y = 0;
  if (i === from) y = (to - from) * h;
  else if (from < to && i > from && i <= to) y = -h;
  else if (from > to && i >= to && i < from) y = h;
  if (y) style.transform = `translate3d(0, ${y}px, 0)`;
  return Object.keys(style).length ? style : undefined;
}

function onDocClick(event: MouseEvent) {
  if (lifted.value || Date.now() < ignoreClickUntil.value) return;
  if (!root.value?.contains(event.target as Node)) {
    void closePicker();
  }
}

function optionElement(key: string): HTMLElement | null {
  const options = listEl.value?.querySelectorAll<HTMLElement>("[data-option-key]") ?? [];
  return [...options].find((option) => option.dataset.optionKey === key) ?? null;
}

function preferredKey(edge: "first" | "last" | "current" = "current"): string {
  const charts = enabledVisibleCharts.value;
  if (!charts.length) return "";
  if (edge === "first") return charts[0].key;
  if (edge === "last") return charts[charts.length - 1].key;
  return charts.find((chart) => isCurrent(chart.key))?.key ?? charts[0].key;
}

async function focusOption(key: string) {
  if (!key) return;
  activeKey.value = key;
  await nextTick();
  const option = optionElement(key);
  option?.focus();
  option?.scrollIntoView({ block: "nearest" });
}

async function openPicker(focus: "search" | "first" | "last" | "current" = "search") {
  open.value = true;
  activeKey.value = preferredKey(focus === "search" ? "current" : focus);
  await nextTick();
  if (focus === "search" && !coarsePointer.value) {
    searchEl.value && focusQuiet(searchEl.value);
  } else if (focus !== "search") {
    await focusOption(activeKey.value);
  }
}

// keyboard：键盘激活的选项目前与鼠标点击走同一条路径（都回到 trigger），
// 参数保留以标注调用意图，尚未影响行为。
async function closePicker(restoreTrigger = false, _keyboard = false) {
  cancelDrag();
  open.value = false;
  query.value = "";
  activeKey.value = "";
  if (restoreTrigger) {
    await nextTick();
    focusQuiet(triggerEl.value);
  }
}

function togglePicker() {
  if (open.value) {
    void closePicker();
  } else {
    void openPicker("search");
  }
}

function onTriggerKeydown(event: KeyboardEvent) {
  if (event.key === "ArrowDown" || event.key === "Home") {
    event.preventDefault();
    void openPicker("first");
  } else if (event.key === "ArrowUp" || event.key === "End") {
    event.preventDefault();
    void openPicker("last");
  } else if (event.key === "Escape" && open.value) {
    event.preventDefault();
    void closePicker(true, true);
  }
}

function onSearchKeydown(event: KeyboardEvent) {
  if (event.key === "ArrowDown") {
    event.preventDefault();
    void focusOption(preferredKey("current"));
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    void focusOption(preferredKey("last"));
  }
}

function onPopupKeydown(event: KeyboardEvent) {
  if (event.key !== "Escape") return;
  event.preventDefault();
  event.stopPropagation();
  void closePicker(true, true);
}

function choose(key: string, playable: boolean, keyboard = false) {
  if (!playable) return;
  if (lifted.value || moved.value || Date.now() < ignoreClickUntil.value) return;
  emit("select", key);
  void closePicker(true, keyboard);
}

function isCurrent(key: string): boolean {
  return key === props.chartKey;
}

function onOptionFocus(chart: CatalogChart) {
  activeKey.value = chart.key;
}

function optionTabindex(chart: CatalogChart): 0 | -1 {
  if (!chart.playable) return -1;
  if (activeKey.value) return activeKey.value === chart.key ? 0 : -1;
  return preferredKey("current") === chart.key ? 0 : -1;
}

function onOptionKeydown(chart: CatalogChart, event: KeyboardEvent) {
  if (event.altKey && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
    event.preventDefault();
    moveChart(chart.key, event.key === "ArrowUp" ? -1 : 1);
    return;
  }

  const charts = enabledVisibleCharts.value;
  if (!charts.length) return;
  const currentIndex = Math.max(
    0,
    charts.findIndex((item) => item.key === chart.key),
  );
  let nextKey = "";
  if (event.key === "ArrowDown") {
    nextKey = charts[Math.min(currentIndex + 1, charts.length - 1)].key;
  } else if (event.key === "ArrowUp") {
    nextKey = charts[Math.max(currentIndex - 1, 0)].key;
  } else if (event.key === "Home") {
    nextKey = charts[0].key;
  } else if (event.key === "End") {
    nextKey = charts[charts.length - 1].key;
  } else if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    choose(chart.key, chart.playable, true);
    return;
  } else {
    return;
  }
  event.preventDefault();
  void focusOption(nextKey);
}

function insertIndexFromY(clientY: number): number {
  if (!listEl.value) return 0;
  const y = clampInsertY(clientY);
  const others = [...listEl.value.querySelectorAll<HTMLElement>("[data-chart-key]")].filter(
    (el) => el.dataset.chartKey !== draggingKey.value,
  );
  for (let i = 0; i < others.length; i += 1) {
    const rect = others[i].getBoundingClientRect();
    if (y < rect.top + rect.height / 2) return i;
  }
  return others.length;
}

function focusQuiet(el: HTMLElement | null) {
  if (!el) return;
  try {
    el.focus({ preventScroll: true });
  } catch {
    el.focus();
  }
}

function preventIfPossible(event: Event) {
  if (event.cancelable) event.preventDefault();
}

function paintGhost(y: number) {
  ghostY = clampGhostTop(y);
  const el = ghostEl.value;
  if (el) el.style.transform = `translate3d(0, ${ghostY}px, 0) scale(1.03)`;
}

function autoScroll(clientY: number) {
  const box = listEl.value;
  if (!box) return;
  const rect = box.getBoundingClientRect();
  const edge = 48;
  if (clientY < rect.top + edge) box.scrollTop -= Math.max(8, (rect.top + edge - clientY) / 3);
  if (clientY > rect.bottom - edge) box.scrollTop += Math.max(8, (clientY - (rect.bottom - edge)) / 3);
}

function bindPointerWindow() {
  window.addEventListener("pointermove", onWindowMove, { passive: false, capture: true });
  window.addEventListener("pointerup", onWindowUp, { capture: true });
  window.addEventListener("pointercancel", onWindowUp, { capture: true });
}

function unbindPointerWindow() {
  window.removeEventListener("pointermove", onWindowMove, true);
  window.removeEventListener("pointerup", onWindowUp, true);
  window.removeEventListener("pointercancel", onWindowUp, true);
}

function onHandleTouchStart(event: TouchEvent) {
  if (!open.value || !canDrag.value || event.touches.length !== 1) return;
  const handle = (event.target as HTMLElement).closest<HTMLElement>("[data-drag-handle]");
  if (!handle || !root.value?.contains(handle)) return;
  const row = handle.closest<HTMLElement>("[data-option-key]");
  if (!row) return;
  const chart = visibleCharts.value.find((item) => item.key === row.dataset.optionKey);
  if (!chart?.playable) return;
  const touch = event.touches[0];
  preventIfPossible(event);
  const active = pending;
  if (active) {
    active.identifier = touch.identifier;
    return;
  }
  beginPending(chart, row, touch.clientX, touch.clientY, true, -1, touch.identifier);
  const started = pending;
  if (started) started.row = handle;
}

function bindTouchWindow() {
  window.addEventListener("touchstart", onHandleTouchStart, { passive: false, capture: true });
  window.addEventListener("touchmove", onTouchMove, { passive: false, capture: true });
  window.addEventListener("touchend", onTouchEnd, { capture: true });
  window.addEventListener("touchcancel", onTouchCancel, { capture: true });
}

function unbindTouchWindow() {
  window.removeEventListener("touchstart", onHandleTouchStart, true);
  window.removeEventListener("touchmove", onTouchMove, true);
  window.removeEventListener("touchend", onTouchEnd, true);
  window.removeEventListener("touchcancel", onTouchCancel, true);
}

function capturePointer(el: HTMLElement, pointerId: number) {
  try {
    el.setPointerCapture(pointerId);
  } catch {
    /* pointer already gone */
  }
}

function releasePointer(el: HTMLElement | null, pointerId: number) {
  if (!el || pointerId < 0) return;
  try {
    if (el.hasPointerCapture(pointerId)) el.releasePointerCapture(pointerId);
  } catch {
    /* ignore */
  }
}

function activateLift(chart: CatalogChart, clientY: number) {
  if (!pending) return;
  pending.claimed = true;
  lifted.value = true;
  pressingKey.value = chart.key;
  draggingKey.value = chart.key;
  insertAt.value = visibleCharts.value.findIndex((item) => item.key === chart.key);
  moved.value = false;
  paintGhost(clientY - pending.grabY);
  void nextTick(() => {
    if (pending) paintGhost(clientY - pending.grabY);
  });
  try {
    navigator.vibrate?.(12);
  } catch {
    /* ignore */
  }
}

function cancelDrag() {
  if (dragRaf) {
    cancelAnimationFrame(dragRaf);
    dragRaf = 0;
  }
  if (pending) releasePointer(pending.row, pending.pointerId);
  unbindPointerWindow();
  pending = null;
  pressingKey.value = "";
  lifted.value = false;
  draggingKey.value = "";
  insertAt.value = -1;
  moved.value = false;
}

function applyDrag(clientX: number, clientY: number) {
  if (!pending || !lifted.value) return;
  pending.lastX = clientX;
  pending.lastY = clientY;
  if (!dragRaf) dragRaf = requestAnimationFrame(flushDrag);
}

function flushDrag() {
  dragRaf = 0;
  if (!pending || !lifted.value) return;
  paintGhost(pending.lastY - pending.grabY);
  autoScroll(clampInsertY(pending.lastY));
  const next = insertIndexFromY(pending.lastY);
  const dy = pending.lastY - pending.startY;
  if (next !== insertAt.value) {
    insertAt.value = next;
    moved.value = true;
  } else if (Math.abs(dy) > MOUSE_DISTANCE) {
    moved.value = true;
  }
}

function beginPending(
  chart: CatalogChart,
  row: HTMLElement,
  clientX: number,
  clientY: number,
  isTouch: boolean,
  pointerId: number,
  identifier: number,
) {
  if (pending || lifted.value) cancelDrag();
  const rect = row.getBoundingClientRect();
  rowHeight.value = rect.height;
  pending = {
    key: chart.key,
    pointerId,
    identifier,
    startX: clientX,
    startY: clientY,
    lastX: clientX,
    lastY: clientY,
    grabY: clientY - rect.top,
    isTouch,
    claimed: false,
    row,
  };
  const box = listRect();
  ghost.value = {
    left: box ? box.left + 4 : rect.left,
    width: box ? box.width - 8 : rect.width,
    name: chart.name,
    selected: isCurrent(chart.key),
  };
  paintGhost(rect.top);
}

function onRowDown(chart: CatalogChart, event: PointerEvent) {
  const isTouch = event.pointerType === "touch" || event.pointerType === "pen";
  if (isTouch && !(event.target as HTMLElement).closest("[data-drag-handle]")) return;
  if (!canDrag.value || !chart.playable) return;
  if ((event.target as HTMLElement).closest("input, [data-no-drag]")) return;
  const row = event.currentTarget as HTMLElement;
  const handle = (event.target as HTMLElement).closest<HTMLElement>("[data-drag-handle]");
  const captureEl = isTouch && handle ? handle : row;
  if (pending && pending.key === chart.key && pending.isTouch && isTouch) {
    pending.pointerId = event.pointerId;
    pending.row = captureEl;
    capturePointer(captureEl, event.pointerId);
    bindPointerWindow();
    preventIfPossible(event);
    return;
  }
  beginPending(chart, row, event.clientX, event.clientY, isTouch, event.pointerId, pending?.identifier ?? -1);
  if (pending) pending.row = captureEl;
  capturePointer(captureEl, event.pointerId);
  bindPointerWindow();
  if (isTouch) preventIfPossible(event);
}

function onWindowMove(event: PointerEvent) {
  if (!pending || event.pointerId !== pending.pointerId) return;
  const dist = Math.hypot(event.clientX - pending.startX, event.clientY - pending.startY);
  if (!lifted.value) {
    if (dist < MOUSE_DISTANCE) return;
    const chart = visibleCharts.value.find((item) => item.key === pending?.key);
    if (chart) activateLift(chart, event.clientY);
    return;
  }
  preventIfPossible(event);
  applyDrag(event.clientX, event.clientY);
}

function matchingTouch(event: TouchEvent): Touch | undefined {
  if (!pending) return undefined;
  const points = event.touches.length ? event.touches : event.changedTouches;
  if (pending.identifier >= 0) {
    return [...points].find((touch) => touch.identifier === pending?.identifier);
  }
  return points[0];
}

function onTouchMove(event: TouchEvent) {
  if (!pending?.isTouch) return;
  const touch = matchingTouch(event) ?? event.touches[0];
  if (!touch) return;
  if (!lifted.value && pending.isTouch) {
    const dist = Math.hypot(touch.clientX - pending.startX, touch.clientY - pending.startY);
    if (dist >= MOUSE_DISTANCE) {
      const chart = visibleCharts.value.find((item) => item.key === pending?.key);
      if (chart) activateLift(chart, touch.clientY);
    } else {
      preventIfPossible(event);
      return;
    }
  }
  if (!lifted.value) return;
  pending.claimed = true;
  preventIfPossible(event);
  applyDrag(touch.clientX, touch.clientY);
}

function onTouchEnd(event: TouchEvent) {
  if (!pending?.isTouch) return;
  const touch = matchingTouch(event);
  if (touch) {
    pending.lastX = touch.clientX;
    pending.lastY = touch.clientY;
  }
  if (!lifted.value) {
    cancelDrag();
    return;
  }
  finishDrag();
}

function onTouchCancel() {
  if (!pending?.isTouch) return;
  // Safari often cancels right after lift, before the first move frame.
  // Keep the gesture and drop on touchend/pointerup.
  if (lifted.value) return;
  cancelDrag();
}

function onWindowUp(event: PointerEvent) {
  if (!pending || event.pointerId !== pending.pointerId) return;
  pending.lastX = event.clientX;
  pending.lastY = event.clientY;
  if (event.type === "pointercancel") {
    if (lifted.value) return;
    cancelDrag();
    return;
  }
  if (!lifted.value) {
    cancelDrag();
    return;
  }
  finishDrag();
}

function finishDrag() {
  if (!pending) return;
  if (lifted.value) {
    const next = insertIndexFromY(pending.lastY);
    insertAt.value = next;
    if (next !== visibleCharts.value.findIndex((item) => item.key === pending?.key)) {
      moved.value = true;
    } else if (Math.abs(pending.lastY - pending.startY) > MOUSE_DISTANCE) {
      moved.value = true;
    }
  }
  const key = draggingKey.value;
  const index = insertAt.value;
  const didLift = lifted.value;
  const origin = visibleCharts.value.findIndex((item) => item.key === key);
  const didMove = didLift && index >= 0 && index !== origin;
  cancelDrag();
  if (!didLift) return;
  ignoreClickUntil.value = Date.now() + 400;
  if (!didMove || index < 0 || !key) return;
  commitReorder(key, index);
}

function commitReorder(key: string, index: number) {
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

function moveChart(key: string, direction: -1 | 1) {
  if (!canDrag.value) return;
  const from = ordered.value.findIndex((chart) => chart.key === key);
  if (from < 0) return;
  const target = from + direction;
  if (target < 0 || target >= ordered.value.length) return;
  commitReorder(key, target);
  void nextTick(() => focusOption(key));
}

function canMove(chart: CatalogChart, direction: -1 | 1): boolean {
  if (!canDrag.value || !chart.playable) return false;
  const index = ordered.value.findIndex((item) => item.key === chart.key);
  return direction < 0 ? index > 0 : index >= 0 && index < ordered.value.length - 1;
}

function moveActiveChart(direction: -1 | 1) {
  if (activeChart.value) moveChart(activeChart.value.key, direction);
}

function canMoveActiveChart(direction: -1 | 1): boolean {
  return activeChart.value ? canMove(activeChart.value, direction) : false;
}

watch(
  () => props.groups,
  () => {
    localKeys.value = null;
    saving.value = false;
  },
);

watch(query, () => {
  if (!enabledVisibleCharts.value.some((chart) => chart.key === activeKey.value)) {
    activeKey.value = preferredKey("current");
  }
});

let bindGen = 0;

onMounted(() => {
  coarsePointer.value =
    window.matchMedia("(pointer: coarse)").matches ||
    /iPhone|iPod|iPad/i.test(navigator.userAgent) ||
    (navigator.maxTouchPoints > 0 && window.matchMedia("(hover: none)").matches);
  document.addEventListener("click", onDocClick);
});
onUnmounted(() => {
  bindGen += 1;
  document.removeEventListener("click", onDocClick);
  unbindTouchWindow();
  cancelDrag();
});

watch(open, async (isOpen) => {
  bindGen += 1;
  const gen = bindGen;
  if (!isOpen) {
    unbindTouchWindow();
    cancelDrag();
    return;
  }
  await nextTick();
  if (gen !== bindGen || !open.value) return;
  // Bind before the gesture so Safari treats touchmove as cancelable (WebKit 184250).
  bindTouchWindow();
});
</script>

<template>
  <div ref="root" class="relative min-w-0">
    <button
      ref="triggerEl"
      type="button"
      class="chart-title-trigger inline-flex min-h-11 max-w-full items-center gap-1 rounded-full px-1 text-left text-[1.05rem] font-bold hover:bg-zinc-100 dark:hover:bg-white/10"
      :aria-expanded="open"
      :aria-controls="listboxId"
      aria-haspopup="listbox"
      @click="togglePicker"
      @keydown="onTriggerKeydown"
    >
      <span class="truncate">{{ name }}</span>
      <svg
        class="h-4 w-4 shrink-0 text-zinc-400"
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden="true"
      >
        <path d="m4 6 4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>
    <div
      v-if="open"
      class="absolute left-0 top-full z-30 mt-1 w-[min(100vw-2rem,22rem)] overflow-hidden rounded-2xl bg-white shadow-xl ring-1 ring-zinc-200 dark:bg-zinc-900 dark:ring-white/10"
      @keydown="onPopupKeydown"
    >
      <div class="border-b border-zinc-100 p-2 dark:border-white/10">
        <input
          ref="searchEl"
          v-model="query"
          type="search"
          placeholder="搜索榜单"
          aria-label="搜索榜单"
          :aria-controls="listboxId"
          class="chart-picker-search h-11 w-full appearance-none rounded-full bg-zinc-100 px-3 text-[16px] outline-none ring-1 ring-transparent transition focus:bg-white focus:ring-zinc-300 dark:bg-zinc-800 dark:focus:bg-zinc-800 dark:focus:ring-white/20"
          @keydown="onSearchKeydown"
        />
      </div>
      <div
        :id="listboxId"
        ref="listEl"
        role="listbox"
        aria-label="榜单"
        :aria-busy="saving"
        class="chart-picker-list max-h-[min(70dvh,28rem)] overflow-y-auto overscroll-contain px-1 py-1"
        :class="lifted ? 'select-none touch-none' : ''"
      >
        <TransitionGroup name="chart-sort" :css="!lifted" tag="div">
          <div
            v-for="chart in visibleCharts"
            :key="chart.key"
            class="group flex min-h-11 items-center rounded-xl text-sm chart-sort-row outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-sky-500"
            :data-chart-key="chart.key"
            :data-option-key="chart.key"
            role="option"
            :aria-selected="isCurrent(chart.key)"
            :aria-disabled="!chart.playable"
            aria-keyshortcuts="Alt+ArrowUp Alt+ArrowDown"
            :tabindex="optionTabindex(chart)"
            :class="[
              isCurrent(chart.key)
                ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900'
                : 'hover:bg-zinc-100 dark:hover:bg-white/10',
              canDrag && chart.playable ? 'cursor-grab' : '',
              lifted ? 'cursor-grabbing' : '',
              draggingKey === chart.key ? 'is-drag-source' : '',
              !chart.playable ? 'cursor-not-allowed text-zinc-400' : '',
            ]"
            :style="rowDragStyle(chart)"
            @pointerdown="onRowDown(chart, $event)"
            @click="choose(chart.key, chart.playable)"
            @focus="onOptionFocus(chart)"
            @keydown="onOptionKeydown(chart, $event)"
            @contextmenu.prevent
          >
            <span class="flex min-h-11 min-w-0 flex-1 items-center gap-2 rounded-xl py-0 pr-3 pl-1 text-left">
              <span class="chart-sort-handle" data-drag-handle aria-hidden="true" @click.stop>
                <svg viewBox="0 0 16 16" class="h-4 w-4" fill="currentColor" draggable="false">
                  <circle cx="5" cy="4" r="1.15" />
                  <circle cx="11" cy="4" r="1.15" />
                  <circle cx="5" cy="8" r="1.15" />
                  <circle cx="11" cy="8" r="1.15" />
                  <circle cx="5" cy="12" r="1.15" />
                  <circle cx="11" cy="12" r="1.15" />
                </svg>
              </span>
              <span class="min-w-0 truncate">{{ chart.name }}</span>
              <span
                class="ml-auto shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium leading-4 ring-1 ring-inset"
                :class="
                  isCurrent(chart.key)
                    ? 'bg-white/10 text-zinc-300 ring-white/20 dark:bg-zinc-900/10 dark:text-zinc-500 dark:ring-zinc-900/20'
                    : 'bg-zinc-100 text-zinc-500 ring-zinc-200/70 dark:bg-white/5 dark:text-zinc-400 dark:ring-white/10'
                "
              >
                {{ groupLabelByKey.get(chart.key) ?? '' }}
              </span>
            </span>
          </div>
        </TransitionGroup>
        <p v-if="!visibleCharts.length" class="px-3 py-6 text-center text-sm text-zinc-500">没有匹配的榜</p>
      </div>
      <div
        v-if="visibleCharts.length"
        role="toolbar"
        class="flex items-center justify-end gap-1 border-t border-zinc-100 px-2 py-1 dark:border-white/10"
        aria-label="榜单排序"
      >
        <span class="mr-auto truncate px-1 text-xs text-zinc-500">
          {{
            coarsePointer
              ? "拖动手柄排序"
              : activeChart
                ? `排序：${activeChart.name}`
                : "选择榜单后排序"
          }}
        </span>
        <button
          type="button"
          class="rounded-lg p-2 text-zinc-500 outline-none hover:bg-zinc-100 focus-visible:ring-2 focus-visible:ring-sky-500 disabled:cursor-not-allowed disabled:opacity-30 dark:hover:bg-white/10"
          :disabled="!canMoveActiveChart(-1)"
          :aria-label="activeChart ? `上移 ${activeChart.name}` : '上移榜单'"
          @click="moveActiveChart(-1)"
        >
          <svg class="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="m4 10 4-4 4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
        <button
          type="button"
          class="rounded-lg p-2 text-zinc-500 outline-none hover:bg-zinc-100 focus-visible:ring-2 focus-visible:ring-sky-500 disabled:cursor-not-allowed disabled:opacity-30 dark:hover:bg-white/10"
          :disabled="!canMoveActiveChart(1)"
          :aria-label="activeChart ? `下移 ${activeChart.name}` : '下移榜单'"
          @click="moveActiveChart(1)"
        >
          <svg class="h-3.5 w-3.5" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="m4 6 4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
      </div>
    </div>
    <p class="sr-only" aria-live="polite" aria-atomic="true">
      {{ saving ? "正在保存榜单顺序" : "" }}
    </p>
    <Teleport to="body">
      <div
        v-if="lifted"
        ref="ghostEl"
        class="chart-drag-ghost pointer-events-none fixed top-0 z-[80] flex min-h-11 items-center rounded-xl px-3 text-sm shadow-2xl ring-1 ring-black/10 dark:ring-white/15"
        :class="
          ghost.selected
            ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900'
            : 'bg-white text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100'
        "
        :style="{
          left: `${ghost.left}px`,
          width: `${ghost.width}px`,
        }"
      >
        <span class="truncate">{{ ghost.name }}</span>
      </div>
    </Teleport>
  </div>
</template>
