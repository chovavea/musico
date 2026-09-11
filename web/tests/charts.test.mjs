import assert from "node:assert/strict";
import { after, afterEach, beforeEach, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createPinia, setActivePinia } from "pinia";
import { createServer } from "vite";

const server = await createServer({
  root: fileURLToPath(new URL("..", import.meta.url)),
  configFile: false,
  envFile: false,
  appType: "custom",
  server: { middlewareMode: true, hmr: { port: 24_700 + (process.pid % 1_000) }, watch: null },
  optimizeDeps: { noDiscovery: true, include: [] },
});
const originalFetch = globalThis.fetch;
let store;

function envelope(data, code = 0, msg = "") {
  return new Response(JSON.stringify({ code, data, msg }), { status: 200 });
}

function latest(boardId, staleness = "fresh") {
  return {
    board_id: boardId,
    fetched_at: new Date().toISOString(),
    staleness,
    items: [],
  };
}

beforeEach(async () => {
  server.moduleGraph.invalidateAll();
  setActivePinia(createPinia());
  const { useChartsStore } = await server.ssrLoadModule("/src/stores/charts.ts");
  store = useChartsStore();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  store?.$dispose();
});

after(async () => {
  await server.close();
});

test("latest requests are deduplicated per board and expose loading state", async () => {
  let resolveRequest;
  let calls = 0;
  globalThis.fetch = () => {
    calls += 1;
    return new Promise((resolve) => {
      resolveRequest = resolve;
    });
  };

  const first = store.refreshLatest("board-a");
  const second = store.refreshLatest("board-a");
  assert.equal(store.latestLoading["board-a"], true);
  await Promise.resolve();
  assert.equal(calls, 1);

  resolveRequest(envelope(latest("board-a")));
  await Promise.all([first, second]);
  assert.equal(calls, 1);
  assert.equal(store.latestLoading["board-a"], undefined);
});

test("a successful board refresh does not clear another board error", async () => {
  globalThis.fetch = async (url) =>
    String(url).includes("board-a")
      ? envelope(null, 1, "A 榜暂不可用")
      : envelope(latest("board-b"));

  await store.refreshLatest("board-a");
  await store.refreshLatest("board-b");

  assert.equal(store.latestErrors["board-a"], "A 榜暂不可用");
  assert.equal(store.latestErrors["board-b"], undefined);
  assert.equal(store.error, "A 榜暂不可用");
});

test("stale YAML boards refresh immediately while recent catalog boards wait", async () => {
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    return envelope(latest("yaml-board"));
  };
  store.latest["yaml-board"] = {
    ...latest("yaml-board", "stale"),
    items: [{ external_id: "cached" }],
  };
  store.latest["catalog:qqmusic:26"] = {
    ...latest("catalog:qqmusic:26", "stale"),
    items: [{ external_id: "cached" }],
  };

  await store.refreshLatestEntry("yaml-board");
  await store.refreshLatestEntry("catalog:qqmusic:26");

  assert.equal(calls.length, 1);
  assert.match(calls[0], /yaml-board/);
});

test("failed catalog reorder clears pending and restores a fresh groups reference", async () => {
  globalThis.fetch = async () => envelope(null, 1, "保存顺序失败");
  store.catalog = [
    {
      id: "qqmusic",
      name: "QQ",
      groups: [{ name: "歌曲", charts: [{ key: "26", name: "热歌", playable: true }] }],
    },
  ];
  const previousGroups = store.catalog[0].groups;

  const request = store.reorderCatalogChart("qqmusic", "26", null);
  assert.equal(store.catalogReorderPending["qqmusic:26"], true);
  assert.equal(await request, false);
  assert.equal(store.catalogReorderPending["qqmusic:26"], undefined);
  assert.equal(store.actionError, "保存顺序失败");
  assert.notEqual(store.catalog[0].groups, previousGroups);
  assert.equal(store.catalog[0].groups[0].charts[0].key, "26");
});
