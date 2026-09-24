import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const server = await createServer({
  root: fileURLToPath(new URL("..", import.meta.url)),
  configFile: false,
  envFile: false,
  appType: "custom",
  server: { middlewareMode: true, hmr: { port: 27_700 + (process.pid % 1_000) }, watch: null },
  optimizeDeps: { noDiscovery: true, include: [] },
});

const { isCreditLine } = await server.ssrLoadModule("/src/composables/useLyrics.ts");

after(async () => {
  await server.close();
});

test("credit prefixes and only the opening title line are credits", () => {
  assert.equal(isCreditLine("词：方文山"), true);
  assert.equal(isCreditLine("曲：陈杰汉", true), true);
  assert.equal(isCreditLine("制作团队：华纳"), true);
  assert.equal(isCreditLine("歌曲企划：李荣浩"), true);
  assert.equal(isCreditLine("Bass：陈俊华"), true);
  assert.equal(isCreditLine("恋人 - 李荣浩", true), true);
  assert.equal(isCreditLine("你 - 我"), false);
  assert.equal(isCreditLine("山岚像茶杯上的云烟"), false);
});
