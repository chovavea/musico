import type { RankItem } from "../types";
import { downloadErrorLabel } from "../lib/status-labels";
import { useDownloadsStore } from "../stores/downloads";
import { useNoticeStore } from "../stores/notice";

export type DownloadActionState = "ready" | "queued" | "idle";

function trackKey(item: RankItem): string {
  return `${item.platform}:${item.external_id}`;
}

export function useTrackDownload() {
  const downloads = useDownloadsStore();
  const notice = useNoticeStore();

  function state(item: RankItem): DownloadActionState {
    const local = downloads.localStates[trackKey(item)];
    if (local) {
      if (
        local.status === "ready" &&
        local.assetId &&
        downloads.deletedAssetIds[local.assetId]
      ) {
        return "idle";
      }
      return local.status;
    }
    if (item.library_asset_id && downloads.deletedAssetIds[item.library_asset_id]) {
      return "idle";
    }
    if (item.library_status === "ready") return "ready";
    if (item.active_download_id) return "queued";
    return "idle";
  }

  async function enqueue(item: RankItem): Promise<void> {
    const key = trackKey(item);
    if (state(item) !== "idle") return;
    downloads.markLocalQueued(key);
    downloads.clearActionError();
    try {
      const result = await downloads.enqueue({
        platform: item.platform,
        external_id: item.external_id,
        title: item.title,
        artist: item.artist,
        album: item.album,
        duration_ms: item.duration_ms,
        isrc: item.isrc,
        version: item.version,
      });
      if (result.state === "ready") {
        downloads.markLocalReady(key, result.asset?.id, result.asset?.track_id);
        notice.show("已在音乐库中");
      } else if (["resolving", "queued", "downloading", "retrying"].includes(result.state)) {
        downloads.markLocalQueued(key, result.task?.id);
        notice.show("已加入下载队列");
      } else {
        downloads.clearLocalState(key);
        // enqueue() already stored response.msg / transport errors on failed.
        if (result.state !== "failed" || !downloads.actionError) {
          downloads.setActionError(
            result.task?.last_error || "下载任务未进入可执行状态",
          );
        }
        notice.show(
          downloadErrorLabel(downloads.actionError || result.task?.last_error) ||
            "下载未开始",
        );
      }
    } catch (error) {
      downloads.clearLocalState(key);
      downloads.setActionError(
        error instanceof Error ? error.message : "下载任务创建失败",
      );
      notice.show("下载任务创建失败");
    }
  }

  return { enqueue, state };
}
