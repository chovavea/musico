import type { BoardInfo, CatalogGroup, CatalogPlatform, LatestBoard } from "../types";

export function groupsOf(catalog: CatalogPlatform[], platform: string): CatalogGroup[] {
  return catalog.find((item) => item.id === platform)?.groups ?? [];
}

export function chartName(
  catalog: CatalogPlatform[],
  boards: BoardInfo[],
  platform: string,
  key: string,
): string {
  for (const group of groupsOf(catalog, platform)) {
    const chart = group.charts.find((item) => item.key === key);
    if (chart) return chart.name;
  }
  return boards.find((item) => item.platform === platform && item.chart_key === key)?.name ?? key;
}

export function resolveCatalogBoard(
  catalog: CatalogPlatform[],
  boards: BoardInfo[],
  platform: string,
  key: string,
): BoardInfo {
  const yaml = boards.find((item) => item.platform === platform && item.chart_key === key);
  if (yaml) return yaml;
  const prefix = platform === "qqmusic" ? "QQ音乐" : "网易云";
  const label = chartName(catalog, boards, platform, key);
  return {
    id: `catalog:${platform}:${key}`,
    platform,
    name: label.includes("榜") ? label : `${prefix}${label}`,
    type: "catalog",
    enabled: true,
    interval_sec: 3600,
    chart_key: key,
  };
}

export function latestOfBoard(
  latest: Record<string, LatestBoard>,
  boards: BoardInfo[],
  board: BoardInfo,
): LatestBoard | undefined {
  const direct = latest[board.id];
  if (direct?.items.length) return direct;
  const yaml = boards.find(
    (item) => item.platform === board.platform && item.chart_key === board.chart_key,
  );
  if (yaml && latest[yaml.id]?.items.length) return latest[yaml.id];
  if (board.chart_key) {
    const catalogId = `catalog:${board.platform}:${board.chart_key}`;
    if (latest[catalogId]?.items.length) return latest[catalogId];
  }
  return direct;
}
