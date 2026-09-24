import { computed, onUnmounted, watch } from "vue";
import { useRoute } from "vue-router";
import { extractCoverRgb } from "./useCoverTint";
import { latestOfBoard } from "../lib/catalog-board";
import { coverImageUrl } from "../lib/cover-image";
import { DEFAULT_PAGE_AMBIENT, morandiPageBackground } from "../lib/morandi";
import { useChartsStore } from "../stores/charts";
import { usePlayerStore } from "../stores/player";
import { useThemeStore } from "../stores/theme";

const slotOrder: Record<string, number> = { left: 0, right: 1 };

function overviewBoards(charts: ReturnType<typeof useChartsStore>) {
  return [...charts.boards]
    .filter((item) => item.enabled)
    .sort(
      (a, b) =>
        (slotOrder[a.overview_slot ?? ""] ?? 2) - (slotOrder[b.overview_slot ?? ""] ?? 2) ||
        (a.sort_order ?? 10_000) - (b.sort_order ?? 10_000),
    )
    .filter(
      (item, index, items) =>
        items.findIndex((candidate) => candidate.platform === item.platform) === index,
    );
}

function topCoverOfBoard(
  charts: ReturnType<typeof useChartsStore>,
  boardId: string,
): string | null {
  const source = charts.boards.find((item) => item.id === boardId);
  if (!source) return null;
  const latest = latestOfBoard(charts.latest, charts.boards, source);
  return latest?.items[0]?.cover_url ?? null;
}

function defaultChartCover(charts: ReturnType<typeof useChartsStore>, boardId: string): string | null {
  if (boardId) {
    const fromRoute = topCoverOfBoard(charts, boardId);
    if (fromRoute) return fromRoute;
  }
  for (const source of overviewBoards(charts)) {
    const latest = latestOfBoard(charts.latest, charts.boards, source);
    const cover = latest?.items[0]?.cover_url;
    if (cover) return cover;
  }
  return null;
}

function applyAmbient(color: string | null): void {
  const root = document.documentElement;
  if (!color) {
    root.style.removeProperty("--page-ambient");
    return;
  }
  root.style.setProperty("--page-ambient", color);
}

function applyThemeColor(color: string | null, fallback: string): void {
  document
    .querySelector<HTMLMetaElement>('meta[name="theme-color"]')
    ?.setAttribute("content", color ?? fallback);
}

let coverSlot: "a" | "b" = "a";

function applyCover(source: string | null): void {
  const root = document.documentElement;
  const image = coverImageUrl(source, 500);
  if (!image) {
    root.style.setProperty("--page-cover-a-opacity", "0");
    root.style.setProperty("--page-cover-b-opacity", "0");
    return;
  }
  const next = coverSlot === "a" ? "b" : "a";
  root.style.setProperty(`--page-cover-${next}`, `url("${image}")`);
  root.style.setProperty(`--page-cover-${next}-opacity`, "0.32");
  root.style.setProperty(`--page-cover-${coverSlot}-opacity`, "0");
  coverSlot = next;
}

export function usePageAmbient(): void {
  const theme = useThemeStore();
  const player = usePlayerStore();
  const charts = useChartsStore();
  const route = useRoute();

  const enabled = computed(() => theme.isPulse && !theme.dark);
  const coverUrl = computed(() => {
    if (!enabled.value) return null;
    const playing = player.current?.cover_url?.trim();
    if (playing) return playing;
    const boardId = route.name === "chart" ? String(route.params.board ?? "") : "";
    return defaultChartCover(charts, boardId);
  });

  let generation = 0;
  let applied: string | null = null;

  async function sync(url: string | null): Promise<void> {
    const current = ++generation;
    if (!enabled.value) {
      if (applied) {
        applyAmbient(null);
        applyCover(null);
        applyThemeColor(null, theme.dark ? "#09090b" : "#fafafa");
        applied = null;
      }
      return;
    }
    if (!url) {
      applyAmbient(DEFAULT_PAGE_AMBIENT);
      applyCover(null);
      applyThemeColor(DEFAULT_PAGE_AMBIENT, DEFAULT_PAGE_AMBIENT);
      applied = DEFAULT_PAGE_AMBIENT;
      return;
    }
    const sample = await extractCoverRgb(url);
    if (current !== generation) return;
    const color = sample ? morandiPageBackground(sample) : DEFAULT_PAGE_AMBIENT;
    applyAmbient(color);
    applyCover(url);
    applyThemeColor(color, DEFAULT_PAGE_AMBIENT);
    applied = color;
  }

  watch([enabled, coverUrl], ([, url]) => {
    void sync(url);
  }, { immediate: true });

  onUnmounted(() => {
    generation += 1;
    applyAmbient(null);
    applyCover(null);
  });
}
