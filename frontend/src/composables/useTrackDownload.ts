import type { RankItem } from "../types";
import { useDownloadsStore } from "../stores/downloads";

export type DownloadActionState = "ready" | "queued" | "idle";

export function downloadActionState(item: RankItem): DownloadActionState {
  if (item.library_status === "ready") return "ready";
  if (item.active_download_id) return "queued";
  return "idle";
}

export function useTrackDownload() {
  const downloads = useDownloadsStore();

  async function enqueue(item: RankItem): Promise<void> {
    if (downloadActionState(item) !== "idle") return;
    try {
      await downloads.enqueue({
        platform: item.platform,
        external_id: item.external_id,
        title: item.title,
        artist: item.artist,
        album: item.album,
        duration_ms: item.duration_ms,
        isrc: item.isrc,
        version: item.version,
      });
    } catch {
      // 创建失败不打断页面，任务页/轮询会反映真实状态
    }
  }

  return { enqueue };
}
