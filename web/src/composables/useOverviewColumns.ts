import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { groupsOf, latestOfBoard, resolveCatalogBoard } from "../lib/catalog-board";
import { useChartsStore } from "../stores/charts";
import { useStalePoll } from "./useStalePoll";
import type { BoardInfo, LatestBoard } from "../types";

export type OverviewColumn = {
  source: BoardInfo;
  board: BoardInfo;
  latest?: LatestBoard;
};

export function useOverviewColumns() {
  const store = useChartsStore();
  useStalePoll();

  const tab = ref(0);
  const keys = ref<Record<string, string>>({});
  const slotOrder: Record<string, number> = { left: 0, right: 1 };

  const overviewSources = computed(() =>
    [...store.boards]
      .filter((item) => item.enabled)
      .sort(
        (a, b) =>
          (slotOrder[a.overview_slot ?? ""] ?? 2) - (slotOrder[b.overview_slot ?? ""] ?? 2) ||
          (a.sort_order ?? 10_000) - (b.sort_order ?? 10_000),
      )
      .filter(
        (item, index, items) =>
          items.findIndex((candidate) => candidate.platform === item.platform) === index,
      ),
  );

  const columns = computed<OverviewColumn[]>(() =>
    overviewSources.value.map((source) => {
      const key = keys.value[source.id] || source.chart_key || "";
      const board = key
        ? resolveCatalogBoard(store.catalog, store.boards, source.platform, key)
        : source;
      return {
        source,
        board,
        latest: latestOfBoard(store.latest, store.boards, board),
      };
    }),
  );

  function applyDefaults() {
    const next = { ...keys.value };
    for (const source of overviewSources.value) {
      if (source.chart_key && !next[source.id]) next[source.id] = source.chart_key;
    }
    keys.value = next;
    if (tab.value >= overviewSources.value.length) tab.value = 0;
  }

  function setKey(sourceId: string, key: string) {
    keys.value = { ...keys.value, [sourceId]: key };
  }

  watch(
    () => store.boards.map((item) => `${item.id}:${item.chart_key}:${item.sort_order}`).join(),
    applyDefaults,
  );
  watch(
    () => columns.value.map((item) => item.board.id).join(),
    () => {
      for (const column of columns.value) void store.ensureLatest(column.board);
    },
  );

  let retryTimer = 0;
  onMounted(() => {
    void store.refreshAll().then(() => {
      applyDefaults();
      if (columns.value.some((column) => !column.latest?.items.length)) {
        retryTimer = window.setTimeout(() => void store.refreshAll().then(applyDefaults), 2000);
      }
    });
  });
  onUnmounted(() => window.clearTimeout(retryTimer));

  return {
    store,
    tab,
    columns,
    setKey,
    groupsOf,
  };
}
