import { computed, onMounted, ref, watch, type Ref } from "vue";
import { storeToRefs } from "pinia";
import { coverImageUrl } from "../lib/cover-image";
import { hslToRgb as toRgb, rgbToHsl, type RGB } from "../lib/morandi";
import { useThemeStore } from "../stores/theme";

export type CoverPalette = {
  bg: string;
  title: string;
  muted: string;
  chipBg: string;
  chipFg: string;
  overlay: string;
  hover: string;
  active: string;
};

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

function channel(n: number): number {
  return Math.round(clamp(n, 28, 232));
}

function rgb(r: number, g: number, b: number, a?: number): string {
  if (a == null) return `rgb(${channel(r)} ${channel(g)} ${channel(b)})`;
  return `rgb(${channel(r)} ${channel(g)} ${channel(b)} / ${a})`;
}

function hslToRgb(h: number, s: number, l: number): RGB {
  return toRgb(h, clamp(s, 0.1, 0.5), clamp(l, 0.16, 0.88));
}

function fallbackPalette(dark: boolean): CoverPalette {
  if (dark) {
    return {
      bg: "rgb(39 39 42)",
      title: "rgb(228 228 231)",
      muted: "rgb(161 161 170)",
      chipBg: "rgb(82 82 91)",
      chipFg: "rgb(228 228 231)",
      overlay: "rgb(39 39 42 / 0.48)",
      hover: "rgb(228 228 231 / 0.08)",
      active: "rgb(228 228 231 / 0.12)",
    };
  }
  return {
    bg: "rgb(228 228 231)",
    title: "rgb(63 63 70)",
    muted: "rgb(113 113 122)",
    chipBg: "rgb(82 82 91)",
    chipFg: "rgb(228 228 231)",
    overlay: "rgb(212 212 216 / 0.42)",
    hover: "rgb(63 63 70 / 0.07)",
    active: "rgb(63 63 70 / 0.11)",
  };
}

function paletteFromRgb(sample: RGB, dark: boolean): CoverPalette {
  const [h, s] = rgbToHsl(sample[0], sample[1], sample[2]);
  const sat = Math.max(0.16, s);
  const bgL = dark ? 0.2 : 0.84;
  const titleL = dark ? 0.85 : 0.26;
  const mutedL = dark ? 0.68 : 0.4;
  const chipBgL = dark ? 0.78 : 0.3;
  const chipFgL = dark ? 0.24 : 0.86;
  const bg = hslToRgb(h, sat * 0.34, bgL);
  const title = hslToRgb(h, sat * 0.3, titleL);
  const muted = hslToRgb(h, sat * 0.18, mutedL);
  const chipBg = hslToRgb(h, sat * 0.3, chipBgL);
  const chipFg = hslToRgb(h, sat * 0.16, chipFgL);
  return {
    bg: rgb(...bg),
    title: rgb(...title),
    muted: rgb(...muted),
    chipBg: rgb(...chipBg),
    chipFg: rgb(...chipFg),
    overlay: rgb(...bg, dark ? 0.56 : 0.62),
    hover: rgb(...title, 0.1),
    active: rgb(...title, 0.14),
  };
}

function samplePixels(data: Uint8ClampedArray): RGB | null {
  const buckets = new Map<number, { r: number; g: number; b: number; w: number }>();
  for (let i = 0; i < data.length; i += 4) {
    const a = data[i + 3] ?? 0;
    if (a < 180) continue;
    const pr = data[i] ?? 0;
    const pg = data[i + 1] ?? 0;
    const pb = data[i + 2] ?? 0;
    const [hue, sat, lit] = rgbToHsl(pr, pg, pb);
    if (sat < 0.08 || lit < 0.08 || lit > 0.92) continue;
    const weight = sat * sat * (1 - Math.abs(lit - 0.48) * 1.4);
    if (weight <= 0) continue;
    const key = Math.round(hue / 18) * 18;
    const slot = buckets.get(key) ?? { r: 0, g: 0, b: 0, w: 0 };
    slot.r += pr * weight;
    slot.g += pg * weight;
    slot.b += pb * weight;
    slot.w += weight;
    buckets.set(key, slot);
  }
  let best: { r: number; g: number; b: number; w: number } | null = null;
  for (const slot of buckets.values()) {
    if (!best || slot.w > best.w) best = slot;
  }
  if (!best || best.w < 0.001) return null;
  return [best.r / best.w, best.g / best.w, best.b / best.w];
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.referrerPolicy = "no-referrer";
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("cover"));
    image.src = src;
  });
}

function sourcesFor(url: string): string[] {
  const proxied = coverImageUrl(url, 150);
  return proxied ? [proxied] : [];
}

const rgbCache = new Map<string, RGB | null>();
const inflight = new Map<string, Promise<RGB | null>>();

export async function extractCoverRgb(url: string): Promise<RGB | null> {
  if (rgbCache.has(url)) return rgbCache.get(url) ?? null;
  const pending = inflight.get(url);
  if (pending) return pending;
  const task = (async () => {
    for (const src of sourcesFor(url)) {
      try {
        const image = await loadImage(src);
        const canvas = document.createElement("canvas");
        canvas.width = 32;
        canvas.height = 32;
        const ctx = canvas.getContext("2d");
        if (!ctx) continue;
        ctx.drawImage(image, 0, 0, 32, 32);
        const sampled = samplePixels(ctx.getImageData(0, 0, 32, 32).data);
        rgbCache.set(url, sampled);
        return sampled;
      } catch {
        continue;
      }
    }
    rgbCache.set(url, null);
    return null;
  })();
  inflight.set(url, task);
  try {
    return await task;
  } finally {
    inflight.delete(url);
  }
}

export function useCoverPalette(coverUrl: Ref<string | null | undefined>): Ref<CoverPalette> {
  const { dark } = storeToRefs(useThemeStore());
  const sampled = ref<RGB | null>(null);
  const palette = computed(() =>
    sampled.value ? paletteFromRgb(sampled.value, dark.value) : fallbackPalette(dark.value),
  );

  // 异步取色带代际编号：封面快速切换时丢弃过期请求的结果，避免旧封面颜色覆盖新封面。
  let generation = 0;
  async function extract(url: string): Promise<void> {
    const current = ++generation;
    const value = await extractCoverRgb(url);
    if (current === generation) {
      sampled.value = value;
    }
  }

  onMounted(() => {
    if (coverUrl.value) void extract(coverUrl.value);
  });
  watch(coverUrl, (url, previous) => {
    if (url === previous) return;
    sampled.value = null;
    if (url) void extract(url);
  });
  return palette;
}

export function useCoverTint(coverUrl: Ref<string | null | undefined>): Ref<string> {
  const palette = useCoverPalette(coverUrl);
  return computed(() => palette.value.bg);
}
