import assert from "node:assert/strict";
import { test } from "node:test";
import { isQuarkShareUrl } from "../src/lib/quark-share.ts";

test("accepts a Quark share URL and rejects host look-alikes", () => {
  assert.equal(isQuarkShareUrl("https://pan.quark.cn/s/ef20d65b3f5e"), true);
  assert.equal(isQuarkShareUrl("http://pan.quark.cn/s/abc123"), true);
  assert.equal(isQuarkShareUrl("https://evil.example/pan.quark.cn/s/abc123"), false);
  assert.equal(isQuarkShareUrl("https://pan.quark.cn.evil.example/s/abc123"), false);
  assert.equal(isQuarkShareUrl("https://evil.example/?next=https://pan.quark.cn/s/abc123"), false);
  assert.equal(isQuarkShareUrl("javascript:https://pan.quark.cn/s/abc123"), false);
  assert.equal(isQuarkShareUrl("https://user:pass@pan.quark.cn/s/abc123"), false);
});
