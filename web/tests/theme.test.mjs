import assert from "node:assert/strict";
import { after, afterEach, beforeEach, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createPinia, setActivePinia } from "pinia";
import { createServer } from "vite";

// 主题 store 只触碰 localStorage / document / matchMedia，用最小替身加载真实 TS 源。
const server = await createServer({
  root: fileURLToPath(new URL("..", import.meta.url)),
  configFile: false,
  envFile: false,
  appType: "custom",
  server: { middlewareMode: true, hmr: { port: 28_700 + (process.pid % 1_000) }, watch: null },
  optimizeDeps: { noDiscovery: true, include: [] },
});

const STYLE_STORAGE_KEY = "musico-style-theme";
let store;
let stored;
let themeColor;

beforeEach(async () => {
  stored = new Map();
  themeColor = "";
  globalThis.window = {
    matchMedia: () => ({ matches: false, addEventListener: () => undefined }),
  };
  globalThis.localStorage = {
    getItem: (key) => (stored.has(key) ? stored.get(key) : null),
    setItem: (key, value) => void stored.set(key, String(value)),
    removeItem: (key) => void stored.delete(key),
  };
  globalThis.document = {
    documentElement: { dataset: {}, classList: { toggle: () => undefined } },
    querySelector: () => ({
      setAttribute: (_name, value) => {
        themeColor = value;
      },
    }),
  };
  server.moduleGraph.invalidateAll();
  setActivePinia(createPinia());
  const { useThemeStore } = await server.ssrLoadModule("/src/stores/theme.ts");
  store = useThemeStore();
});

afterEach(() => {
  delete globalThis.localStorage;
});

after(async () => {
  await server.close();
  delete globalThis.window;
  delete globalThis.document;
});

test("默认页面样式主题是极简", () => {
  store.init();

  assert.equal(store.styleTheme, "minimal");
  assert.equal(store.styleThemes.length, 1);
  assert.equal(store.styleThemes[0].name, "极简");
  assert.equal(document.documentElement.dataset.theme, "minimal");
});

test("选中主题写入 localStorage 并同步到 data-theme", () => {
  store.init();
  store.setStyleTheme("minimal");

  assert.equal(localStorage.getItem(STYLE_STORAGE_KEY), "minimal");
  assert.equal(document.documentElement.dataset.theme, "minimal");

  store.init();
  assert.equal(store.styleTheme, "minimal");
});

test("未知主题值回退到极简并清掉脏数据", () => {
  localStorage.setItem(STYLE_STORAGE_KEY, "neon");
  store.init();

  assert.equal(store.styleTheme, "minimal");
  assert.equal(localStorage.getItem(STYLE_STORAGE_KEY), null);
  assert.equal(document.documentElement.dataset.theme, "minimal");
  assert.equal(themeColor, "#fafafa");
});
