import type { DownloadStatus } from "../types";

const DOWNLOAD_STATUS_LABELS: Record<DownloadStatus, string> = {
  resolving: "正在查找音源",
  queued: "等待下载",
  downloading: "正在下载",
  retrying: "正在重试",
  completed: "已完成",
  failed: "下载失败",
  missing: "文件缺失",
};

export function downloadStatusLabel(status: DownloadStatus): string {
  return DOWNLOAD_STATUS_LABELS[status] ?? "状态未知";
}

export function downloadErrorLabel(error: string | null | undefined): string {
  if (!error) return "";
  const normalized = error.toLowerCase();
  if (
    normalized.includes("no matching download source") ||
    normalized.includes("no download source matches")
  ) {
    return "暂时没有符合音质要求的下载源";
  }
  if (normalized.includes("timeout")) return "连接下载源超时，请稍后重试";
  if (normalized.includes("not found") || normalized.includes("404")) {
    return "下载源已失效";
  }
  return "下载未完成，可稍后重试";
}
