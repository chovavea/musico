import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const server = await createServer({
  root: fileURLToPath(new URL("..", import.meta.url)),
  configFile: false,
  envFile: false,
  appType: "custom",
  server: { middlewareMode: true, hmr: false, watch: null },
  optimizeDeps: { noDiscovery: true, include: [] },
});

const { nextVisibleCount, sentinelNeedsMore, SEARCH_PAGE_SIZE, SEARCH_SENTINEL_MARGIN_PX } =
  await server.ssrLoadModule("/src/lib/search.ts");

after(async () => {
  await server.close();
});

test("nextVisibleCount keeps appending a page while rows remain", () => {
  assert.equal(nextVisibleCount(10, 100), 20);
  assert.equal(nextVisibleCount(95, 100), 100);
  assert.equal(nextVisibleCount(100, 100), 100);
  assert.equal(nextVisibleCount(0, 0), 0);
  assert.equal(SEARCH_PAGE_SIZE, 10);
});

test("sentinelNeedsMore stays true while the sentinel is still in the padded viewport", () => {
  const viewport = 800;
  assert.equal(sentinelNeedsMore(900, viewport), true);
  assert.equal(sentinelNeedsMore(viewport + SEARCH_SENTINEL_MARGIN_PX, viewport), true);
  assert.equal(sentinelNeedsMore(viewport + SEARCH_SENTINEL_MARGIN_PX + 1, viewport), false);
});

test("a still-visible sentinel keeps paging until it would leave the viewport", () => {
  const total = 100;
  const viewportFits = 25;
  let visible = SEARCH_PAGE_SIZE;
  const steps = [];
  while (visible < total && sentinelNeedsMore(visible * 72, viewportFits * 72)) {
    visible = nextVisibleCount(visible, total);
    steps.push(visible);
  }
  assert.deepEqual(steps, [20, 30]);
});
