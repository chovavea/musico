export function formatUpdatedAt(iso?: string | null): string {
  if (!iso) {
    return "尚未更新";
  }
  const stamp = Date.parse(iso);
  if (Number.isNaN(stamp)) {
    return "尚未更新";
  }
  const mins = Math.round((Date.now() - stamp) / 60_000);
  if (mins < 1) {
    return "刚刚更新";
  }
  if (mins < 60) {
    return `${mins} 分钟前更新`;
  }
  const hours = Math.round(mins / 60);
  if (hours < 24) {
    return `${hours} 小时前更新`;
  }
  return new Date(stamp).toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatClock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return "0:00";
  }
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

export function todayLabel(): string {
  return new Date().toLocaleDateString("zh-CN", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

export function risingCount(items: { previous_rank: number | null; rank: number }[]): number {
  return items.filter((item) => item.previous_rank != null && item.previous_rank > item.rank).length;
}
