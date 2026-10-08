import assert from "node:assert/strict";
import { test } from "node:test";
import render from "../adaptive_document_agent/ui/assets/completion_notification.mjs";

class Element {
  constructor() { this.events = new Map(); this.children = new Map(); this.dataset = {}; this.attributes = new Map(); }
  setAttribute(name, value) { this.attributes.set(name, value); }
  querySelector(selector) { return this.children.get(selector); }
  querySelectorAll() { return []; }
  addEventListener(type, fn) { if (!this.events.has(type)) this.events.set(type, new Set()); this.events.get(type).add(fn); }
  removeEventListener(type, fn) { this.events.get(type)?.delete(fn); }
  focus() { this.focused = true; }
  fire(type, event = {}) { for (const fn of this.events.get(type) || []) fn(event); }
}
function root() {
  const wrapper = new Element();
  const element = new Element();
  wrapper.children.set(".completion-notice", element);
  for (const selector of [".notice-trigger", ".notice-panel", ".notice-enable", ".notice-toggle-text", ".notice-test", ".notice-status", ".notice-preview", ".notice-preview-title", ".notice-preview-body", ".notice-dismiss"]) element.children.set(selector, new Element());
  element.querySelector(".notice-panel").hidden = true;
  element.style = { setProperty() {} };
  return { wrapper, element, get: selector => element.querySelector(selector) };
}
function browser({ saved = new Map(), permission = "default", allowed = "granted", requestThrows = false, unsupported = false, constructorThrows = false } = {}) {
  const notices = [];
  const timers = new Map();
  let timerId = 0;
  let requests = 0;
  class Notification {
    static permission = permission;
    static requestPermission() {
      requests++;
      if (requestThrows) throw new Error("iframe restriction");
      this.permission = allowed;
      return Promise.resolve(allowed);
    }
    constructor(title, options) {
      if (constructorThrows) throw new Error("System notification unavailable");
      notices.push({ title, options, instance: this });
    }
    close() {}
  }
  const win = { isSecureContext: true, Notification: unsupported ? undefined : Notification,
    location: { pathname: "/" }, focus() {},
    sessionStorage: { getItem: key => saved.get(key), setItem: (key, value) => saved.set(key, value) } };
  win.addEventListener = () => {}; win.removeEventListener = () => {};
  win.setTimeout = callback => { const id = ++timerId; timers.set(id, callback); return id; };
  win.clearTimeout = id => timers.delete(id);
  globalThis.document = new Element();
  globalThis.window = win;
  return { win, notices, saved, requests: () => requests, runTimers: () => {
    for (const [id, callback] of [...timers]) { timers.delete(id); callback(); }
  } };
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

test("legacy sound preferences cannot create audio; test and completion messages are silent", async () => {
  const saved = new Map([["ada:completion:v1:/", JSON.stringify({ enabled: true, sound: true })]]);
  const b = browser({ saved, permission: "granted" });
  b.win[Symbol.for("adaptive-document-agent.completion-notice.v1")] = {
    complete() { assert.fail("An old controller with audio must not be reused"); },
  };
  Object.defineProperty(b.win, "AudioContext", { get() { assert.fail("Audio API must not be accessed"); } });
  const r = root();
  render({ parentElement: r.wrapper, data: { mode: "settings" } });
  assert.equal(r.get(".notice-enable").attributes.get("aria-checked"), "true");
  assert.equal(r.get(".notice-toggle-text").textContent, "On");
  assert.equal(r.element.dataset.state, "on");
  r.get(".notice-test").fire("click");
  assert.match(r.get(".notice-status").textContent, /Requesting a silent system notification/);
  finish("sound-run"); finish("sound-run");
  assert.equal(b.notices.length, 2);
  assert.ok(b.notices.every(notice => notice.options.silent === true));
  assert.ok(!("sound" in JSON.parse(b.saved.get("ada:completion:v1:/"))));
  r.get(".notice-enable").fire("click");
  assert.equal(r.get(".notice-enable").attributes.get("aria-checked"), "false");
  assert.equal(r.get(".notice-test").disabled, true);
});


test("bell opens a local panel, Escape restores focus and outside clicks close it", () => {
  const b = browser();
  const r = root();
  const cleanup = render({ parentElement: r.wrapper, data: { mode: "settings" } });
  const doc = globalThis.document;
  r.get(".notice-trigger").fire("click");
  assert.equal(r.get(".notice-panel").hidden, false);
  assert.equal(r.get(".notice-trigger").attributes.get("aria-expanded"), "true");
  assert.equal(b.requests(), 0);
  let prevented = false;
  doc.fire("keydown", { key: "Escape", preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(r.get(".notice-panel").hidden, true);
  assert.equal(r.get(".notice-trigger").focused, true);
  r.get(".notice-trigger").fire("click");
  doc.fire("pointerdown", { composedPath: () => [r.element] });
  assert.equal(r.get(".notice-panel").hidden, false);
  doc.fire("pointerdown", { composedPath: () => [] });
  assert.equal(r.get(".notice-panel").hidden, true);
  cleanup();
  assert.equal(doc.events.get("keydown").size, 0);
  assert.equal(doc.events.get("pointerdown").size, 0);
});


test("test waits for show confirmation and repeated clicks request distinct notices", () => {
  const b = browser({ saved: new Map([["ada:completion:v1:/", '{"enabled":true}']]), permission: "granted" });
  const r = root();
  render({ parentElement: r.wrapper, data: { mode: "settings" } });
  r.get(".notice-test").fire("click");
  assert.match(r.get(".notice-status").textContent, /Requesting/);
  assert.equal(r.get(".notice-preview").hidden, false);
  assert.equal(r.get(".notice-preview-title").textContent, "Test notification");
  b.notices[0].instance.onshow();
  assert.match(r.get(".notice-status").textContent, /browser reported/);
  b.runTimers();
  assert.match(r.get(".notice-status").textContent, /browser reported/);
  r.get(".notice-test").fire("click");
  assert.notEqual(b.notices[0].options.tag, b.notices[1].options.tag);
  b.notices[0].instance.onerror(); // An older request cannot overwrite the new test.
  assert.match(r.get(".notice-status").textContent, /Requesting/);
  b.runTimers();
  assert.match(r.get(".notice-status").textContent, /No display confirmation/);
  b.notices[1].instance.onshow(); // Late browser confirmation remains informative.
  assert.match(r.get(".notice-status").textContent, /browser reported/);
  r.get(".notice-dismiss").fire("click");
  assert.equal(r.get(".notice-preview").hidden, true);
});

test("system errors leave a visible local notice without claiming delivery", () => {
  for (const constructorThrows of [false, true]) {
    const b = browser({ saved: new Map([["ada:completion:v1:/", '{"enabled":true}']]), permission: "granted", constructorThrows });
    const r = root();
    render({ parentElement: r.wrapper, data: { mode: "settings" } });
    r.get(".notice-test").fire("click");
    if (!constructorThrows) b.notices[0].instance.onerror();
    b.runTimers();
    assert.match(r.get(".notice-status").textContent, /could not show|unavailable/);
    assert.equal(r.get(".notice-preview").hidden, false);
    assert.match(r.get(".notice-preview-body").textContent, /In-page preview/);
    finish("verified-export", "attempt");
    assert.equal(r.get(".notice-preview-title").textContent, "PowerPoint ready to download");
    r.get(".notice-enable").fire("click");
    b.runTimers();
    assert.equal(r.get(".notice-preview").hidden, true);
    finish("later-export", "attempt");
    assert.equal(r.get(".notice-preview").hidden, true);
  }
});
