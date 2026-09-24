import { defineStore } from "pinia";
import type { RankItem } from "../types";

export interface PreviewFailure {
  id: string;
  title: string;
  artist: string;
  platform: string;
  externalId: string;
  reason: string;
  createdAt: string;
  seen: boolean;
}

const STORAGE_KEY = "musico.preview-failures";
const MAX_ENTRIES = 50;

function loadEntries(): PreviewFailure[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isPreviewFailure).slice(0, MAX_ENTRIES);
  } catch {
    return [];
  }
}

function saveEntries(entries: PreviewFailure[]) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // Private mode or a full quota should not block playback.
  }
}

function isPreviewFailure(value: unknown): value is PreviewFailure {
  if (!value || typeof value !== "object") return false;
  const entry = value as Partial<PreviewFailure>;
  return (
    typeof entry.id === "string" &&
    typeof entry.title === "string" &&
    typeof entry.artist === "string" &&
    typeof entry.platform === "string" &&
    typeof entry.externalId === "string" &&
    typeof entry.reason === "string" &&
    typeof entry.createdAt === "string" &&
    typeof entry.seen === "boolean"
  );
}

export const usePreviewFailureStore = defineStore("previewFailures", {
  state: () => ({
    entries: loadEntries(),
  }),
  getters: {
    unseenCount: (state) => state.entries.filter((entry) => !entry.seen).length,
  },
  actions: {
    record(item: RankItem, reason = "整段试听失败") {
      const entry: PreviewFailure = {
        id: `${Date.now().toString(36)}-${item.platform}-${item.external_id}`,
        title: item.title,
        artist: item.artist,
        platform: item.platform,
        externalId: item.external_id,
        reason,
        createdAt: new Date().toISOString(),
        seen: false,
      };
      this.entries = [entry, ...this.entries].slice(0, MAX_ENTRIES);
      saveEntries(this.entries);
    },
    markSeen() {
      if (this.entries.every((entry) => entry.seen)) return;
      this.entries = this.entries.map((entry) => ({ ...entry, seen: true }));
      saveEntries(this.entries);
    },
  },
});
