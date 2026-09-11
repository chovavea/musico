import { defineStore } from "pinia";
import { health } from "../api";
import { healthScore, scoreToGlow } from "../lib/healthScore";
import type { HealthPayload } from "../types";

export const useHealthStore = defineStore("health", {
  state: () => ({
    payload: null as HealthPayload | null,
    error: "",
    loading: false,
  }),
  getters: {
    score(state): number {
      return healthScore(state.payload, state.error);
    },
    glowColor(): string {
      return scoreToGlow(this.score);
    },
  },
  actions: {
    async refresh() {
      this.loading = true;
      try {
        const res = await health();
        if (res.code === 0) {
          this.payload = res.data;
          this.error = "";
        } else {
          this.error = res.msg || "状态检查失败";
        }
      } catch (err) {
        this.error = err instanceof Error ? err.message : "状态检查失败";
      } finally {
        this.loading = false;
      }
    },
  },
});
