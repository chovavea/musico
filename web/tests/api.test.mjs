import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import {
  ApiError,
  cancelFullSearch,
  createDownload,
  getApiToken,
  isAbortError,
  listBoards,
  resolveDownloadFallback,
  searchTracks,
  setApiToken,
} from "../src/api.ts";

const originalFetch = globalThis.fetch;
const originalLocalStorage = globalThis.localStorage;

function stubStorage() {
  const items = new Map();
  return {
    getItem: (key) => (items.has(key) ? items.get(key) : null),
    setItem: (key, value) => items.set(key, String(value)),
    removeItem: (key) => items.delete(key),
  };
}

const originalSetTimeout = globalThis.setTimeout;

afterEach(() => {
  cancelFullSearch();
  globalThis.fetch = originalFetch;
  globalThis.localStorage = originalLocalStorage;
  globalThis.setTimeout = originalSetTimeout;
});

test("parses a valid API envelope", async () => {
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ code: 0, data: [], msg: "" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });

  const response = await listBoards();
  assert.equal(response.code, 0);
  assert.deepEqual(response.data, []);
});

test("turns transport failures into structured readable errors", async () => {
  globalThis.fetch = async () => {
    throw new TypeError("fetch failed");
  };

  await assert.rejects(listBoards(), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.kind, "network");
    assert.match(error.message, /网络连接失败/);
    assert.equal(error.url, "/api/v1/boards");
    return true;
  });
});

test("merges an external abort signal into a request", async () => {
  globalThis.fetch = (_url, init) =>
    new Promise((_resolve, reject) => {
      init.signal.addEventListener(
        "abort",
        () => reject(new DOMException("aborted", "AbortError")),
        { once: true },
      );
    });

  const controller = new AbortController();
  const request = searchTracks("周杰伦", "suggest", 5, controller.signal);
  controller.abort();

  await assert.rejects(request, (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.kind, "aborted");
    assert.match(error.message, /已取消/);
    return true;
  });
});

test("a newer full search cancels the previous full search", async () => {
  const pending = [];
  globalThis.fetch = (_url, init) =>
    new Promise((resolve, reject) => {
      init.signal.addEventListener(
        "abort",
        () => reject(new DOMException("aborted", "AbortError")),
        { once: true },
      );
      pending.push(resolve);
    });

  const first = searchTracks("first", "full", 20);
  const second = searchTracks("second", "full", 20);

  await assert.rejects(first, (error) => error instanceof ApiError && error.kind === "aborted");
  pending[1](
    new Response(
      JSON.stringify({
        code: 0,
        data: { query: "second", type: "full", items: [], platforms: [], partial: false },
        msg: "",
      }),
      { status: 200 },
    ),
  );
  const response = await second;
  assert.equal(response.data.query, "second");
});

test("isAbortError recognizes ApiError and DOMException aborts", () => {
  assert.equal(
    isAbortError(new ApiError("请求已取消", "aborted", "/api/v1/search")),
    true,
  );
  assert.equal(isAbortError(new DOMException("aborted", "AbortError")), true);
  assert.equal(
    isAbortError(new ApiError("网络连接失败，请稍后重试", "network", "/api/v1/search")),
    false,
  );
});

test("reports HTTP and malformed response details", async () => {
  globalThis.fetch = async () => new Response("<html>bad gateway</html>", { status: 502 });

  await assert.rejects(listBoards(), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.kind, "http");
    assert.equal(error.status, 502);
    assert.match(error.message, /HTTP 502/);
    return true;
  });
});

test("write requests carry the stored API token while reads never do", async () => {
  globalThis.localStorage = stubStorage();
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), headers: new Headers(init?.headers) });
    return new Response(JSON.stringify({ code: 0, data: { state: "queued" }, msg: "" }), {
      status: 202,
    });
  };
  setApiToken("stored-token");

  await createDownload({
    platform: "qqmusic",
    external_id: "qq-1",
    title: "晴天",
    artist: "周杰伦",
  });
  await listBoards();

  assert.equal(getApiToken(), "stored-token");
  assert.equal(calls[0].headers.get("X-API-Token"), "stored-token");
  assert.equal(calls[1].headers.get("X-API-Token"), null);
});

test("clearing the API token stops sending the header", async () => {
  globalThis.localStorage = stubStorage();
  const calls = [];
  globalThis.fetch = async (_url, init) => {
    calls.push(new Headers(init?.headers));
    return new Response(JSON.stringify({ code: 0, data: { state: "queued" }, msg: "" }), {
      status: 202,
    });
  };
  setApiToken("stored-token");
  setApiToken("  ");

  await createDownload({
    platform: "qqmusic",
    external_id: "qq-1",
    title: "晴天",
    artist: "周杰伦",
  });

  assert.equal(getApiToken(), "");
  assert.equal(calls[0].get("X-API-Token"), null);
});

test("the token gate 401 explains where to set the token", async () => {
  globalThis.localStorage = stubStorage();
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        code: 40101,
        data: null,
        msg: "unauthorized: missing or invalid API token",
      }),
      { status: 401 },
    );

  const response = await createDownload({
    platform: "qqmusic",
    external_id: "qq-1",
    title: "晴天",
    artist: "周杰伦",
  });

  assert.equal(response.code, 40101);
  assert.match(response.msg, /配置/);
  assert.doesNotMatch(response.msg, /unauthorized/);
});

test("the download fallback is given far more than the default request timeout", async () => {
  const delays = [];
  globalThis.setTimeout = (handler, delay, ...rest) => {
    delays.push(delay);
    return originalSetTimeout(handler, delay, ...rest);
  };
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({ code: 0, data: { outcome: "not_found", task_id: "t1" }, msg: "" }),
      { status: 200 },
    );

  await resolveDownloadFallback("t1");

  // 服务端要串行读好几个页面，15 秒的默认超时会让浏览器先放弃。
  assert.ok(delays.includes(120_000));
  assert.ok(!delays.includes(15_000));
});
