export type RGB = [number, number, number];

export const PAGE_TEXT_PRIMARY: RGB = [24, 24, 27];
export const PAGE_TEXT_SECONDARY: RGB = [63, 63, 70];
export const DEFAULT_PAGE_AMBIENT = "rgb(250 250 250)";

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

export function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
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

export function hslToRgb(h: number, s: number, l: number): RGB {
  s = clamp(s, 0, 1);
  l = clamp(l, 0, 1);
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

function channel(n: number): number {
  return Math.round(clamp(n, 0, 255));
}

function srgbToLin(value: number): number {
  const c = clamp(value, 0, 255) / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function relativeLuminance(color: RGB): number {
  return 0.2126 * srgbToLin(color[0]) + 0.7152 * srgbToLin(color[1]) + 0.0722 * srgbToLin(color[2]);
}

export function contrastRatio(left: RGB, right: RGB): number {
  const a = relativeLuminance(left);
  const b = relativeLuminance(right);
  const [hi, lo] = a > b ? [a, b] : [b, a];
  return (hi + 0.05) / (lo + 0.05);
}

export function formatRgb(color: RGB): string {
  return `rgb(${channel(color[0])} ${channel(color[1])} ${channel(color[2])})`;
}

export function parseRgb(value: string): RGB | null {
  const match = value.match(/rgb\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)/i);
  if (!match) return null;
  return [Number(match[1]), Number(match[2]), Number(match[3])];
}

function liftForContrast(background: RGB, foreground: RGB, minimum: number): RGB {
  let next = background;
  for (let i = 0; i < 18; i += 1) {
    if (contrastRatio(next, foreground) >= minimum) return next;
    const [hue, saturation, lightness] = rgbToHsl(next[0], next[1], next[2]);
    next = hslToRgb(hue, saturation * 0.97, Math.min(0.93, lightness + 0.016));
  }
  return next;
}

/** 把封面主色压成浅色莫兰迪底：保留色相、压饱和、保证深色文字可读。 */
export function morandiPageBackground(sample: RGB): string {
  const [hue, saturation] = rgbToHsl(sample[0], sample[1], sample[2]);
  const muted = hslToRgb(hue, clamp(Math.max(saturation * 0.62, 0.2), 0.2, 0.42), 0.76);
  const readable = liftForContrast(
    liftForContrast(muted, PAGE_TEXT_PRIMARY, 7),
    PAGE_TEXT_SECONDARY,
    4.5,
  );
  return formatRgb(readable);
}
