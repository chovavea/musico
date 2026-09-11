import assert from "node:assert/strict";
import { after, afterEach, beforeEach, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createPinia, setActivePinia } from "pinia";
import { createServer } from "vite";

// Load the real TypeScript store with the existing Vite toolchain, without a
// browser, a live backend, or another test-runner dependency.
const server = await createServer({
  root: fileURLToPath(new URL("..", import.meta.url)),
  configFile: false,
  envFile: false,
  appType: "custom",
  server: { middlewareMode: true, hmr: false, watch: null },
  optimizeDeps: { noDiscovery: true, include: [] },
});

class FakeAudio {
  static results = [];
  [Symbol.toStringTag] = "HTMLAudioElement";
  listeners = new Map();
  currentTime = 0;
  duration = 0;
  pauseCalls = 0;
  playCalls = 0;
  source = "";

  set src(value) {
    this.source = new URL(value, document.baseURI).href;
  }
  get src() {
    return this.source;
  }
  addEventListener(event, handler) {
    this.listeners.set(event, [...(this.listeners.get(event) ?? []), handler]);
  }
  emit(event) {
    for (const handler of this.listeners.get(event) ?? []) handler();
  }
  play() {
    this.playCalls += 1;
    return FakeAudio.results.shift() ?? Promise.resolve();
  }
  pause() {
    this.pauseCalls += 1;
  }
  removeAttribute(name) {
    if (name === "src") this.source = "";
  }
  load() {}
}

class FakeOfficial {
  static instance = null;
  listeners = new Map();
  data = {};
  duration = 269;
  currentTime = 0;
  playCalls = [];
  pauseCalls = 0;

  constructor() {
    FakeOfficial.instance = this;
  }
  on(event, handler) {
    this.listeners.set(event, [...(this.listeners.get(event) ?? []), handler]);
    return this;
  }
  emit(event, payload = {}) {
    for (const handler of this.listeners.get(event) ?? []) handler(payload);
  }
  play(mid) {
    this.playCalls.push(mid);
    this.data = { song: { mid } };
    return this;
  }
  pause() {
    this.pauseCalls += 1;
    this.emit("pause");
    return this;
  }
  toggle() {
    this.emit("play");
    return this;
  }
}

const qq = {
  rank: 1,
  title: "晴天 & 夏天",
  artist: "周杰伦",
  album: "叶惠美",
  duration_ms: 269000,
  isrc: null,
  version: null,
  platform: "qqmusic",
  external_id: "mid-123",
  preview_url: null,
  official_url: null,
  expire_at: null,
  quality: null,
  cover_url: null,
  normalized_score: 1,
  previous_rank: null,
  raw_score: null,
};
const netease = { ...qq, platform: "netease", external_id: "123" };
const settle = () => new Promise((resolve) => setImmediate(resolve));
let store;
let useDownloadsStore;

beforeEach(async () => {
  globalThis.Audio = FakeAudio;
  globalThis.window = { QMplayer: FakeOfficial };
  globalThis.document = {
    baseURI: "http://localhost/",
    createElement: () => ({}),
    head: { appendChild: () => {} },
  };
  FakeAudio.results = [];
  FakeOfficial.instance = null;
  server.moduleGraph.invalidateAll();
  setActivePinia(createPinia());
  const { usePlayerStore } = await server.ssrLoadModule("/src/stores/player.ts");
  ({ useDownloadsStore } = await server.ssrLoadModule("/src/stores/downloads.ts"));
  store = usePlayerStore();
});

afterEach(() => {
  store?.pause();
  store?.$dispose();
});

after(async () => {
  await server.close();
  delete globalThis.Audio;
  delete globalThis.window;
  delete globalThis.document;
});

test("QQ still uses its official player when playback succeeds", async () => {
  store.play(qq);
  await settle();
  const official = FakeOfficial.instance;
  assert.deepEqual(official.playCalls, [qq.external_id]);
  official.emit("play");
  assert.equal(store.usingOfficial, true);
  assert.equal(store.playing, true);
  assert.equal(store.loading, false);
  assert.equal(store.audio, null);
  assert.equal(store.officialTimer, null);
});

test("QQ failure falls back for the same song without advancing the queue", async () => {
  const next = { ...qq, external_id: "next" };
  store.play(qq, [qq, next]);
  await settle();
  FakeOfficial.instance.emit("error");
  await settle();
  const url = new URL(store.audio.src);
  assert.equal(store.current.external_id, qq.external_id);
  assert.equal(store.index, 0);
  assert.equal(store.usingOfficial, false);
  assert.equal(store.playing, true);
  assert.equal(store.failed, false);
  assert.equal(url.pathname, "/api/v1/preview/qqmusic/mid-123/stream");
  assert.equal(url.searchParams.has("download_only"), false);
  assert.equal(url.searchParams.get("title"), qq.title);
  assert.equal(url.searchParams.get("artist"), qq.artist);
  assert.equal(url.searchParams.get("album"), qq.album);
  assert.equal(url.searchParams.get("duration_ms"), String(qq.duration_ms));
  assert.ok(FakeOfficial.instance.pauseCalls > 0);
});

test("QQ script load failure also uses the backend fallback ladder", async () => {
  delete window.QMplayer;
  document.head.appendChild = (script) => queueMicrotask(() => script.onerror());
  store.play(qq);
  await settle();
  assert.equal(store.downloadOnly, false);
  assert.equal(store.usingOfficial, false);
  assert.equal(store.playing, true);
});

test("a silent or indefinitely loading official player times out to fallback", async (context) => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  delete window.QMplayer;
  store.play(qq);
  context.mock.timers.tick(12_000);
  await settle();
  assert.equal(store.usingOfficial, false);
  assert.equal(store.downloadOnly, false);
  assert.equal(store.playing, true);
});

test("an official player which silently switches songs falls back to the requested song", async () => {
  store.play(qq);
  await settle();
  FakeOfficial.instance.data.song.mid = "wrong-song";
  FakeOfficial.instance.emit("play");
  await settle();
  assert.equal(store.downloadOnly, false);
  assert.equal(store.current.external_id, qq.external_id);
  assert.equal(store.failed, false);
});

test("late SDK events cannot resume official playback or overwrite fallback progress", async () => {
  store.play(qq);
  await settle();
  const official = FakeOfficial.instance;
  official.emit("error");
  await settle();
  store.audio.duration = 100;
  store.audio.currentTime = 25;
  store.audio.emit("loadedmetadata");
  store.audio.emit("timeupdate");
  const pauses = official.pauseCalls;
  official.emit("play");
  official.emit("timeupdate", { currentTime: 90 });
  official.emit("ended");
  official.emit("error");
  assert.equal(official.pauseCalls, pauses + 1);
  assert.equal(store.playing, true);
  assert.equal(store.currentTime, 25);
  assert.equal(store.duration, 100);
  assert.equal(store.failed, false);
});

test("a late ended from the previous QQ song cannot skip the newly selected song", async () => {
  const next = { ...qq, external_id: "next" };
  store.play(qq, [qq, next]);
  await settle();
  const official = FakeOfficial.instance;
  official.emit("play");
  assert.equal(store.usingOfficial, true);

  store.play(next, [qq, next]);
  await settle();
  official.data = { song: { mid: next.external_id } };
  official.emit("ended");
  await settle();
  assert.equal(store.current.external_id, next.external_id);
  assert.equal(store.index, 1);
  assert.equal(store.usingOfficial, true);
});

test("an official error reported for another song cannot demote the current one", async () => {
  const next = { ...qq, external_id: "next" };
  store.play(qq, [qq, next]);
  await settle();
  const official = FakeOfficial.instance;
  official.emit("play");

  store.play(next, [qq, next]);
  await settle();
  official.data = { song: { mid: qq.external_id } };
  official.emit("error");
  await settle();
  assert.equal(store.current.external_id, next.external_id);
  assert.equal(store.usingOfficial, true);
  assert.equal(store.audio, null);
});

test("an ended before the current song made any progress cannot advance the queue", async () => {
  const next = { ...qq, external_id: "next" };
  store.play(qq, [qq, next]);
  await settle();
  FakeOfficial.instance.emit("ended");
  await settle();
  assert.equal(store.current.external_id, qq.external_id);
  assert.equal(store.index, 0);
});

test("official events from a previous session cannot pause or resume the current song", async () => {
  const next = { ...qq, external_id: "next" };
  store.play(qq, [qq, next]);
  await settle();
  const official = FakeOfficial.instance;
  official.emit("play");
  const pauses = official.pauseCalls;

  store.play(next, [qq, next]);
  official.emit("play");
  official.emit("timeupdate", { currentTime: 90 });
  await settle();
  assert.equal(official.pauseCalls, pauses + 1);
  assert.equal(store.current.external_id, next.external_id);
  assert.equal(store.usingOfficial, true);
  assert.equal(store.currentTime, 0);
  assert.equal(store.playing, false);
});

test("pausing and resuming the official player still works with the session guard", async () => {
  store.play(qq);
  await settle();
  const official = FakeOfficial.instance;
  official.emit("play");
  assert.equal(store.playing, true);

  store.toggle();
  assert.equal(store.playing, false);
  store.toggle();
  await settle();
  official.emit("play");
  assert.equal(store.playing, true);
  assert.equal(store.loading, false);
  assert.equal(store.officialTimer, null);
  assert.deepEqual(official.playCalls, [qq.external_id]);
});

test("fallback supports seek, pause, resume and next track", async () => {
  const next = { ...netease, external_id: "next" };
  store.play(qq, [qq, next]);
  await settle();
  FakeOfficial.instance.emit("error");
  await settle();
  store.audio.duration = 200;
  store.seek(0.25);
  assert.equal(store.audio.currentTime, 50);
  store.toggle();
  assert.equal(store.playing, false);
  store.toggle();
  await settle();
  assert.equal(store.playing, true);
  store.audio.emit("ended");
  await settle();
  assert.equal(store.current.external_id, "next");
  assert.equal(store.index, 1);
  assert.equal(store.downloadOnly, false);
});

test("non-QQ stream requests include metadata for automatic backend fallback", async () => {
  store.play(netease);
  await settle();
  const url = new URL(store.audio.src);
  assert.equal(url.pathname, "/api/v1/preview/netease/123/stream");
  assert.equal(url.searchParams.get("title"), netease.title);
  assert.equal(url.searchParams.get("artist"), netease.artist);
  assert.equal(url.searchParams.has("download_only"), false);
  assert.equal(FakeOfficial.instance, null);
});

test("ready local assets still take precedence over every online source", async () => {
  store.play({ ...qq, library_asset_id: "local-asset", library_status: "ready" });
  await settle();
  assert.equal(new URL(store.audio.src).pathname, "/api/v1/library/local-asset/stream");
  assert.equal(new URL(store.audio.src).search, "");
  assert.equal(store.usingOfficial, false);
  assert.equal(FakeOfficial.instance, null);
});

test("deleted local assets do not mask the online playback path", async () => {
  useDownloadsStore().deletedAssetIds["deleted"] = true;
  store.play({ ...qq, library_asset_id: "deleted", library_status: "ready" });
  await settle();
  assert.equal(store.usingOfficial, true);
  FakeOfficial.instance.emit("error");
  await settle();
  assert.equal(new URL(store.audio.src).pathname, "/api/v1/preview/qqmusic/mid-123/stream");
});

test("unavailable fallback marks a single song failed only once", async () => {
  store.play(qq);
  await settle();
  FakeAudio.results.push(new Promise(() => {}));
  FakeOfficial.instance.emit("error");
  store.audio.emit("error");
  store.audio.emit("error");
  assert.equal(store.failed, true);
  assert.equal(store.loading, false);
  assert.equal(store.playing, false);
  assert.equal(store.failStreak, 1);
});

test("a song without any playable source stays selected instead of skipping ahead", async () => {
  const next = { ...netease, external_id: "next" };
  store.play(netease, [netease, next]);
  await settle();
  store.audio.emit("error");
  await settle();
  assert.equal(store.current.external_id, netease.external_id);
  assert.equal(store.index, 0);
  assert.equal(store.failed, true);
  assert.equal(store.playing, false);
  assert.equal(store.loading, false);
  assert.equal(store.wantsPlayback, false);
});

test("a late rejection from the previous source cannot corrupt the next song", async () => {
  let reject;
  FakeAudio.results.push(new Promise((_resolve, fail) => { reject = fail; }));
  const next = { ...netease, external_id: "next" };
  store.play(netease, [netease, next]);
  store.audio.emit("error");
  store.next();
  reject(new Error("previous source failed"));
  await settle();
  assert.equal(store.current.external_id, "next");
  assert.equal(store.index, 1);
  assert.equal(store.failed, false);
  assert.equal(store.playing, true);
});

test("late successful audio play cannot mark a new QQ track as playing", async () => {
  let resolve;
  FakeAudio.results.push(new Promise((done) => { resolve = done; }));
  store.play(netease);
  store.play(qq);
  resolve();
  await settle();
  assert.equal(store.current.platform, "qqmusic");
  assert.equal(store.usingOfficial, true);
  assert.equal(store.playing, false);
  assert.equal(store.loading, true);
});

test("pausing while the official SDK is loading cancels its pending playback", async () => {
  store.play(qq);
  store.toggle();
  await settle();
  assert.deepEqual(FakeOfficial.instance.playCalls, []);
  assert.equal(store.playing, false);
  assert.equal(store.loading, false);
  assert.equal(store.officialTimer, null);
});

test("browser autoplay rejection is not treated as a missing source", async () => {
  FakeAudio.results.push(Promise.reject(new DOMException("gesture required", "NotAllowedError")));
  store.play(netease);
  await settle();
  assert.equal(store.failed, false);
  assert.equal(store.failStreak, 0);
  assert.equal(store.playing, false);
  store.toggle();
  await settle();
  assert.equal(store.playing, true);
});
