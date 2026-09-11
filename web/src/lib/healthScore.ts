import type { HealthPayload } from "../types";

/** 0 红 → 1 绿。未拉取完返回 -1。 */
export function healthScore(payload: HealthPayload | null, error: string): number {
  if (error) return 0;
  if (!payload) return -1;
  const sources = payload.sources;
  if (payload.status === "starting") {
    if (!sources.length) return 0.32;
    const ok = sources.filter((item) => item.consecutive_failures === 0 && item.last_success_at).length;
    return 0.18 + (ok / sources.length) * 0.38;
  }
  if (!sources.length) {
    return payload.status === "ready" ? 1 : 0.2;
  }
  let fail = 0;
  for (const item of sources) {
    if (item.consecutive_failures > 0) {
      fail += Math.min(item.consecutive_failures / 5, 1);
    }
  }
  const ratio = 1 - fail / sources.length;
  if (payload.status === "ready" && fail === 0) return 1;
  return Math.max(0.08, ratio * 0.92);
}

export function scoreToGlow(score: number): string {
  if (score < 0) return "hsl(220 8% 62%)";
  const hue = Math.round(score * 142);
  const light = 50 - score * 6;
  return `hsl(${hue} 95% ${light}%)`;
}
