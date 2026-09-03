import { onUnmounted } from "vue";
import { storeToRefs } from "pinia";
import { useChartsStore } from "../stores/charts";

export function useStalePoll(intervalMs = 60_000): void {
  const store = useChartsStore();
  const { latest } = storeToRefs(store);
  const timer = window.setInterval(() => {
    const ids = new Set([
      ...store.boards.map((board) => board.id),
      ...Object.keys(latest.value),
    ]);
    for (const id of ids) {
      const board = latest.value[id];
      if (!board || board.staleness !== "fresh" || !board.items.length) {
        void store.refreshLatest(id);
      }
    }
  }, intervalMs);
  onUnmounted(() => window.clearInterval(timer));
}
