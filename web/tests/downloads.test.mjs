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
  server: { middlewareMode: true, hmr: { port: 25_700 + (process.pid % 1_000) }, watch: null },
  optimizeDeps: { noDiscovery: true, include: [] },
});
const originalFetch = globalThis.fetch;
let store;
let hrefAssigned = "";

function envelope(data, code = 0, msg = "") {
  return new Response(JSON.stringify({ code, data, msg }), { status: 200 });
}

function task(id, status, createdAt) {
  return {
    id,
    track_id: id,
    title: id,
    artist: "a",
    status,
    bytes_done: 0,
    bytes_total: null,
    progress: null,
    attempt_count: 1,
    max_attempts: 3,
    selected_source_id: null,
    selected_quality: null,
    source_page_url: null,
    last_error: status === "failed" ? "x" : null,
    created_at: createdAt,
    completed_at: status === "failed" ? createdAt : null,
  };
}

function summary(counts, active = null) {
  return { counts, active };
}

beforeEach(async () => {
  hrefAssigned = "";
  globalThis.window = {
    location: {
      set href(value) {
        hrefAssigned = value;
      },
      get href() {
        return hrefAssigned;
      },
    },
    setInterval: () => 0,
    clearInterval: () => undefined,
  };
  server.moduleGraph.invalidateAll();
  setActivePinia(createPinia());
  const { useDownloadsStore } = await server.ssrLoadModule("/src/stores/downloads.ts");
  store = useDownloadsStore();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  store?.$dispose();
});

after(async () => {
  await server.close();
});

test("first summary snapshots existing failures and does not jump", async () => {
  const fallbackCalls = [];
  globalThis.fetch = async (input, init) => {
    const url = String(input);
    if (url.endsWith("/downloads/summary")) {
      return envelope(summary({ failed: 1 }));
    }
    if (url.endsWith("/downloads") && (!init || !init.method || init.method === "GET")) {
      return envelope({ items: [task("old", "failed", "2026-01-01T00:00:00Z")] });
    }
    if (url.includes("/fallback")) {
      fallbackCalls.push(url);
      return envelope({ outcome: "jumped", url: "https://pan.quark.cn/s/abc" });
    }
    return envelope({});
  };

  await store.refreshSummary();

  assert.equal(store.failedSnapshotReady, true);
  assert.equal(store.failedIds.old, true);
  assert.deepEqual(fallbackCalls, []);
  assert.equal(hrefAssigned, "");
});

test("a later failure jumps the new task, not an older failed one", async () => {
  let failedCount = 1;
  let items = [task("old", "failed", "2026-01-01T00:00:00Z")];
  const fallbackCalls = [];
  globalThis.fetch = async (input, init) => {
    const url = String(input);
    if (url.endsWith("/downloads/summary")) {
      return envelope(summary({ failed: failedCount }));
    }
    if (url.endsWith("/downloads") && (!init || !init.method || init.method === "GET")) {
      return envelope({ items });
    }
    if (url.includes("/fallback")) {
      fallbackCalls.push(url);
      return envelope({
        outcome: "jumped",
        url: "https://pan.quark.cn/s/newone",
      });
    }
    return envelope({});
  };

  await store.refreshSummary();
  items = [
    task("new", "failed", "2026-09-15T00:00:00Z"),
    task("old", "failed", "2026-01-01T00:00:00Z"),
  ];
  failedCount = 2;
  await store.refreshSummary();

  assert.equal(fallbackCalls.length, 1);
  assert.match(fallbackCalls[0], /\/downloads\/new\/fallback/);
  assert.equal(store.failureNotice?.id, "new");
  assert.equal(hrefAssigned, "https://pan.quark.cn/s/newone");
});

test("two new failures keep resolving until one returns a share link", async () => {
  let failedCount = 0;
  let items = [];
  const fallbackCalls = [];
  globalThis.fetch = async (input, init) => {
    const url = String(input);
    if (url.endsWith("/downloads/summary")) {
      return envelope(summary({ failed: failedCount }));
    }
    if (url.endsWith("/downloads") && (!init || !init.method || init.method === "GET")) {
      return envelope({ items });
    }
    if (url.includes("/fallback")) {
      fallbackCalls.push(url);
      const id = url.split("/downloads/")[1].split("/")[0];
      if (id === "miss") {
        return envelope({ outcome: "no_wav", url: null });
      }
      return envelope({
        outcome: "jumped",
        url: `https://pan.quark.cn/s/${id}`,
      });
    }
    return envelope({});
  };

  await store.refreshSummary();
  items = [
    task("miss", "failed", "2026-09-15T00:00:02Z"),
    task("hit", "failed", "2026-09-15T00:00:01Z"),
  ];
  failedCount = 2;
  await store.refreshSummary();

  assert.deepEqual(
    fallbackCalls.map((url) => url.split("/downloads/")[1]),
    ["miss/fallback", "hit/fallback"],
  );
  assert.equal(hrefAssigned, "https://pan.quark.cn/s/hit");
});

test("a jumped result on another host does not navigate", async () => {
  let failedCount = 0;
  let items = [];
  globalThis.fetch = async (input, init) => {
    const url = String(input);
    if (url.endsWith("/downloads/summary")) {
      return envelope(summary({ failed: failedCount }));
    }
    if (url.endsWith("/downloads") && (!init || !init.method || init.method === "GET")) {
      return envelope({ items });
    }
    if (url.includes("/fallback")) {
      return envelope({
        outcome: "jumped",
        url: "https://evil.example/pan.quark.cn/s/abc",
      });
    }
    return envelope({});
  };

  await store.refreshSummary();
  items = [task("t1", "failed", "2026-09-15T00:00:00Z")];
  failedCount = 1;
  await store.refreshSummary();

  assert.equal(hrefAssigned, "");
});
