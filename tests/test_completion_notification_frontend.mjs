import assert from "node:assert/strict";
import { test } from "node:test";
import render from "../adaptive_document_agent/ui/assets/completion_notification.mjs";

class Element {
  constructor() { this.events = new Map(); this.children = new Map(); }
  querySelector(selector) { return this.children.get(selector); }
  addEventListener(type, fn) { if (!this.events.has(type)) this.events.set(type, new Set()); this.events.get(type).add(fn); }
  removeEventListener(type, fn) { this.events.get(type)?.delete(fn); }
  fire(type) { for (const fn of this.events.get(type) || []) fn(); }
}
function root() {
  const wrapper = new Element();
  const element = new Element();
  wrapper.children.set(".completion-notice", element);
  for (const selector of [".notice-enable", ".notice-sound", ".notice-test", ".notice-status"]) element.children.set(selector, new Element());
  return { wrapper, element, get: selector => element.querySelector(selector) };
}
function browser({ saved = new Map(), permission = "default", allowed = "granted", requestThrows = false, unsupported = false } = {}) {
  const notices = [];
  let requests = 0;
  class Notification {
    static permission = permission;
    static requestPermission() {
      requests++;
      if (requestThrows) throw new Error("iframe restriction");
      this.permission = allowed;
      return Promise.resolve(allowed);
    }
    constructor(title, options) { notices.push({ title, options }); }
    close() {}
  }
  const win = { isSecureContext: true, Notification: unsupported ? undefined : Notification,
    location: { pathname: "/" }, focus() {},
    sessionStorage: { getItem: key => saved.get(key), setItem: (key, value) => saved.set(key, value) } };
  globalThis.window = win;
  return { win, notices, saved, requests: () => requests };
}
const flush = () => new Promise(resolve => setImmediate(resolve));
const finish = (id, runId) => render({ parentElement: root().wrapper, data: { mode: "complete", event_id: id, run_id: runId } });

test("identical content notifies for each new attempt, once per run even after refresh", async () => {
  const b = browser();
  const r = root();
  render({ parentElement: r.wrapper, data: { mode: "settings" } });
  r.get(".notice-enable").fire("click"); await flush();
  finish("same-content", "first-attempt"); finish("same-content", "first-attempt");
  assert.equal(b.notices.length, 1);
  finish("same-content", "second-attempt"); finish("same-content", "second-attempt");
  assert.equal(b.notices.length, 2);
  const refreshed = browser({ saved: b.saved, permission: "granted" });
  render({ parentElement: root().wrapper, data: { mode: "settings" } });
  finish("same-content", "second-attempt");
  finish("same-content"); // Server restored cached content without its old attempt record.
  assert.equal(refreshed.notices.length, 0);
  finish("same-content", "third-attempt");
  assert.equal(refreshed.notices.length, 1);
});

test("explicit export cycles notify once each and cached restore recovers the latest export", async () => {
  const b = browser();
  const r = root();
  render({ parentElement: r.wrapper, data: { mode: "settings" } });
  r.get(".notice-enable").fire("click"); await flush();
  finish("same-content", "analysis:export:first");
  finish("same-content", "analysis:export:first");
  assert.equal(b.notices.length, 1);
  finish("same-content", "analysis:export:second");
  assert.equal(b.notices.length, 2);
  const refreshed = browser({ saved: b.saved, permission: "granted" });
  render({ parentElement: root().wrapper, data: { mode: "settings" } });
  finish("same-content");
  finish("same-content", "analysis:export:second");
  assert.equal(refreshed.notices.length, 0);
});

test("consent is only requested on a click, then completion is delivered once across remount and reload", async () => {
  const b = browser();
  const r = root();
  let cleanup = render({ parentElement: r.wrapper, data: { mode: "settings" } });
  assert.equal(b.requests(), 0);
  assert.equal(b.notices.length, 0);
  r.get(".notice-enable").fire("click"); await flush();
  assert.equal(b.requests(), 1);
  finish("run1"); finish("run1");
  assert.equal(b.notices.length, 1);
  assert.equal(b.notices[0].title, "PowerPoint ready to download");
  assert.equal(b.notices[0].options.silent, true);
  cleanup();
  cleanup = render({ parentElement: r.wrapper, data: { mode: "settings" } });
  assert.equal(r.get(".notice-enable").events.get("click").size, 1);
  finish("run1");
  assert.equal(b.notices.length, 1);
  cleanup();
  assert.equal(r.get(".notice-enable").events.get("click").size, 0);
  const reloaded = browser({ saved: b.saved, permission: "granted" });
  render({ parentElement: root().wrapper, data: { mode: "settings" } });
  finish("run1"); finish("run2");
  assert.equal(reloaded.notices.length, 1);
});

test("finishing while opted out does not create a stale notification after consent", async () => {
  const b = browser();
  const r = root();
  render({ parentElement: r.wrapper, data: { mode: "settings" } });
  finish("before-consent");
  r.get(".notice-enable").fire("click"); await flush();
  finish("before-consent");
  assert.equal(b.notices.length, 0);
  finish("after-consent");
  assert.equal(b.notices.length, 1);
  r.get(".notice-enable").fire("click");
  finish("disabled");
  assert.equal(b.notices.length, 1);
});

test("denial and unsupported browsers leave clear on-page state without notifications", async () => {
  let b = browser({ allowed: "denied" });
  let r = root();
  render({ parentElement: r.wrapper, data: { mode: "settings" } });
  r.get(".notice-enable").fire("click"); await flush();
  finish("denied");
  assert.equal(b.notices.length, 0);
  assert.match(r.get(".notice-status").textContent, /blocked/);
  assert.equal(r.get(".notice-enable").disabled, true);
  b = browser({ unsupported: true }); r = root();
  render({ parentElement: r.wrapper, data: { mode: "settings" } });
  finish("unsupported");
  assert.equal(b.requests(), 0);
  assert.match(r.get(".notice-status").textContent, /unavailable/);
});

test("synchronous permission restrictions are handled and do not emit a success", async () => {
  const b = browser({ requestThrows: true });
  const r = root();
  render({ parentElement: r.wrapper, data: { mode: "settings" } });
  r.get(".notice-enable").fire("click"); await flush();
  finish("failed-permission");
  assert.equal(b.notices.length, 0);
  assert.match(r.get(".notice-status").textContent, /Open the app directly/);
});

test("optional sound is enabled by a gesture and only played with a successful notification", async () => {
  const b = browser();
  let tones = 0;
  let contexts = 0;
  b.win.AudioContext = class {
    constructor() { contexts++; this.state = "running"; this.currentTime = 0; }
    createOscillator() { return { frequency: { setValueAtTime() {} }, connect: () => ({ connect() {} }), start() { tones++; }, stop() {}, disconnect() {} }; }
    createGain() { return { gain: { setValueAtTime() {}, linearRampToValueAtTime() {}, exponentialRampToValueAtTime() {} }, disconnect() {} }; }
  };
  const r = root();
  render({ parentElement: r.wrapper, data: { mode: "settings" } });
  assert.equal(contexts, 0);
  r.get(".notice-enable").fire("click"); await flush();
  r.get(".notice-sound").checked = true;
  r.get(".notice-sound").fire("change");
  assert.equal(contexts, 1);
  finish("sound-run"); finish("sound-run");
  assert.equal(tones, 1);
  assert.equal(b.notices.length, 1);
});
