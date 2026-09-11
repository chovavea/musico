import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import {
  ApiError,
  cancelFullSearch,
  isAbortError,
  listBoards,
  searchTracks,
} from "../src/api.ts";

const originalFetch = globalThis.fetch;

afterEach(() => {
  cancelFullSearch();
  globalThis.fetch = originalFetch;
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
