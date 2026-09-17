import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const server = await createServer({
  root: fileURLToPath(new URL("..", import.meta.url)),
  configFile: false,
  envFile: false,
  appType: "custom",
  server: { middlewareMode: true, hmr: { port: 28_800 + (process.pid % 1_000) }, watch: null },
  optimizeDeps: { noDiscovery: true, include: [] },
});

const {
  PAGE_TEXT_PRIMARY,
  PAGE_TEXT_SECONDARY,
  contrastRatio,
  morandiPageBackground,
  parseRgb,
} = await server.ssrLoadModule("/src/lib/morandi.ts");

after(async () => {
  await server.close();
});

test("封面主色压成浅莫兰迪后，主文案和次文案都保持可读对比", () => {
  const samples = [
    [220, 20, 60],
    [12, 18, 40],
    [250, 210, 40],
    [30, 160, 90],
    [80, 40, 180],
  ];

  for (const sample of samples) {
    const bg = parseRgb(morandiPageBackground(sample));
    assert.ok(bg, `无法解析 ${sample.join(",")}`);
    assert.ok(
      contrastRatio(bg, PAGE_TEXT_PRIMARY) >= 7,
      `主文案对比不足: ${sample.join(",")} -> ${bg.join(",")}`,
    );
    assert.ok(
      contrastRatio(bg, PAGE_TEXT_SECONDARY) >= 4.5,
      `次文案对比不足: ${sample.join(",")} -> ${bg.join(",")}`,
    );
  }
});

test("不同封面色相仍能区分，不会都洗成同一块灰粉", () => {
  const red = parseRgb(morandiPageBackground([220, 30, 50]));
  const teal = parseRgb(morandiPageBackground([20, 160, 150]));
  assert.ok(red && teal);
  const delta = Math.abs(red[0] - teal[0]) + Math.abs(red[1] - teal[1]) + Math.abs(red[2] - teal[2]);
  assert.ok(delta > 40, `色相差太小: ${red.join(",")} vs ${teal.join(",")}`);
});

test("高饱和颜色会被压低，不会直接当背景", () => {
  const bg = parseRgb(morandiPageBackground([255, 0, 0]));
  assert.ok(bg);
  const max = Math.max(...bg);
  const min = Math.min(...bg);
  assert.ok(max - min < 110, `饱和度仍然过高: ${bg.join(",")}`);
  assert.ok(bg.every((channel) => channel > 160), `明度不够浅: ${bg.join(",")}`);
});
