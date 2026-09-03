import type { BoardInfo, PlatformInfo } from "../types";

const TYPE_ORDER = ["hot", "douyin", "new", "rising"];

const TYPE_LABELS: Record<string, string> = {
  hot: "热歌",
  douyin: "抖音",
  new: "新歌",
  rising: "飙升",
};

const PLATFORM_SHORT: Record<string, string> = {
  qqmusic: "QQ",
  netease: "网易",
};

const PLATFORM_LABEL: Record<string, string> = {
  qqmusic: "QQ音乐",
  netease: "网易云",
};

const NAME_PREFIXES = ["QQ音乐", "网易云音乐", "网易云"];

export function platformLabel(id: string): string {
  return PLATFORM_LABEL[id] ?? PLATFORM_SHORT[id] ?? id;
}

export function chartShortName(name: string): string {
  for (const prefix of NAME_PREFIXES) {
    if (name.startsWith(prefix)) {
      const short = name.slice(prefix.length).trim();
      return short || name;
    }
  }
  return name;
}

export function boardTypeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type;
}

export function platformShortName(id: string, platforms: PlatformInfo[]): string {
  if (PLATFORM_SHORT[id]) {
    return PLATFORM_SHORT[id];
  }
  return platforms.find((item) => item.id === id)?.name ?? id;
}

export function platformFullName(id: string, platforms: PlatformInfo[]): string {
  return platforms.find((item) => item.id === id)?.name ?? platformShortName(id, platforms);
}

export function uniquePlatformIds(boards: BoardInfo[]): string[] {
  return [...new Set(boards.map((item) => item.platform))];
}

export function uniqueBoardTypes(boards: BoardInfo[]): string[] {
  return [...new Set(boards.map((item) => item.type))].sort((a, b) => {
    const left = TYPE_ORDER.indexOf(a);
    const right = TYPE_ORDER.indexOf(b);
    return (left === -1 ? 99 : left) - (right === -1 ? 99 : right);
  });
}

export function findBoard(
  boards: BoardInfo[],
  platform: string,
  type: string,
): BoardInfo | undefined {
  return boards.find((item) => item.platform === platform && item.type === type);
}

export function defaultBoardForPlatform(boards: BoardInfo[], platform: string): BoardInfo | undefined {
  return (
    findBoard(boards, platform, "hot") ?? boards.find((item) => item.platform === platform)
  );
}

export function sortedBoards(boards: BoardInfo[]): BoardInfo[] {
  return boards
    .slice()
    .sort(
      (a, b) => (a.sort_order ?? 10_000) - (b.sort_order ?? 10_000) || a.id.localeCompare(b.id),
    );
}

export function groupBoardsByPlatform(boards: BoardInfo[]): { platform: string; boards: BoardInfo[] }[] {
  return uniquePlatformIds(boards).map((platform) => ({
    platform,
    boards: boards
      .filter((item) => item.platform === platform)
      .slice()
      .sort(
        (a, b) =>
          (a.sort_order ?? 10_000) - (b.sort_order ?? 10_000) || a.id.localeCompare(b.id),
      ),
  }));
}
