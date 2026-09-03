import { computed, onMounted, ref, watch, type Ref } from "vue";
import { storeToRefs } from "pinia";
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

type RGB = [number, number, number];

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

function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  r /= 255;
  g /= 255;
  b /= 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  const d = max - min;
  if (d === 0) return [0, 0, l];
  const s = d / (1 - Math.abs(2 * l - 1));
  let h = 0;
  if (max === r) h = ((g - b) / d) % 6;
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  h *= 60;
  if (h < 0) h += 360;
  return [h, s, l];
}

function hslToRgb(h: number, s: number, l: number): RGB {
  s = clamp(s, 0.18, 0.62);
  l = clamp(l, 0.16, 0.88);
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  let rp = 0;
  let gp = 0;
  let bp = 0;
  if (h < 60) [rp, gp, bp] = [c, x, 0];
  else if (h < 120) [rp, gp, bp] = [x, c, 0];
  else if (h < 180) [rp, gp, bp] = [0, c, x];
  else if (h < 240) [rp, gp, bp] = [0, x, c];
  else if (h < 300) [rp, gp, bp] = [x, 0, c];
  else [rp, gp, bp] = [c, 0, x];
  return [(rp + m) * 255, (gp + m) * 255, (bp + m) * 255];
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
  const sat = Math.max(0.22, s);
  const bgL = dark ? 0.22 : 0.86;
  const titleL = dark ? 0.82 : 0.28;
  const mutedL = dark ? 0.64 : 0.42;
  const chipBgL = dark ? 0.78 : 0.3;
  const chipFgL = dark ? 0.24 : 0.86;
  const bg = hslToRgb(h, sat * 0.45, bgL);
  const title = hslToRgb(h, sat * 0.38, titleL);
  const muted = hslToRgb(h, sat * 0.22, mutedL);
  const chipBg = hslToRgb(h, sat * 0.32, chipBgL);
  const chipFg = hslToRgb(h, sat * 0.18, chipFgL);
  return {
    bg: rgb(...bg),
    title: rgb(...title),
    muted: rgb(...muted),
    chipBg: rgb(...chipBg),
    chipFg: rgb(...chipFg),
    overlay: rgb(...bg, dark ? 0.52 : 0.58),
    hover: rgb(...title, 0.1),
    active: rgb(...title, 0.14),
  };
}

function samplePixels(data: Uint8ClampedArray): RGB | null {
  let r = 0;
  let g = 0;
  let b = 0;
  let w = 0;
  for (let i = 0; i < data.length; i += 4) {
    const a = data[i + 3] ?? 0;
    if (a < 180) continue;
    const pr = data[i] ?? 0;
    const pg = data[i + 1] ?? 0;
    const pb = data[i + 2] ?? 0;
    const [, sat, lit] = rgbToHsl(pr, pg, pb);
    if (sat < 0.08 || lit < 0.08 || lit > 0.92) continue;
    const weight = sat * sat * (1 - Math.abs(lit - 0.48) * 1.4);
    if (weight <= 0) continue;
    r += pr * weight;
    g += pg * weight;
    b += pb * weight;
    w += weight;
  }
  if (w < 0.001) return null;
  return [r / w, g / w, b / w];
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
  const encoded = encodeURIComponent(url);
  return [`/cover-proxy?url=${encoded}`, `/api/v1/cover-image?url=${encoded}`, url];
}

async function extractRgb(url: string): Promise<RGB | null> {
  for (const src of sourcesFor(url)) {
    try {
      const image = await loadImage(src);
      const canvas = document.createElement("canvas");
      canvas.width = 32;
      canvas.height = 32;
      const ctx = canvas.getContext("2d");
      if (!ctx) return null;
      ctx.drawImage(image, 0, 0, 32, 32);
      return samplePixels(ctx.getImageData(0, 0, 32, 32).data);
    } catch {
      continue;
    }
  }
  return null;
}

export function useCoverPalette(coverUrl: Ref<string | null | undefined>): Ref<CoverPalette> {
  const { dark } = storeToRefs(useThemeStore());
  const sampled = ref<RGB | null>(null);
  const palette = computed(() =>
    sampled.value ? paletteFromRgb(sampled.value, dark.value) : fallbackPalette(dark.value),
  );

  async function extract(url: string): Promise<void> {
    sampled.value = await extractRgb(url);
  }

  onMounted(() => {
    if (coverUrl.value) void extract(coverUrl.value);
  });
  watch(coverUrl, (url) => {
    sampled.value = null;
    if (url) void extract(url);
  });
  return palette;
}

export function useCoverTint(coverUrl: Ref<string | null | undefined>): Ref<string> {
  const palette = useCoverPalette(coverUrl);
  return computed(() => palette.value.bg);
}
