import { useNoticeStore } from "../stores/notice";

export function comingSoon(feature?: string): void {
  useNoticeStore().comingSoon(feature);
}
