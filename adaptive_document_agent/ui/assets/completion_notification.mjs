// Trusted application code only. No document text, filenames or external assets.
// Keep stored consent/deduplication, but replace any live controller with audio.
const CONTROLLER = Symbol.for("adaptive-document-agent.completion-notice.v2");

function controllerFor(win) {
  if (win[CONTROLLER]) return win[CONTROLLER];
  const storageKey = `ada:completion:v1:${win.location.pathname}`;
  let saved = {};
  let storageAvailable = true;
  try { saved = JSON.parse(win.sessionStorage.getItem(storageKey) || "{}"); }
  catch { storageAvailable = false; }
  if (!saved || typeof saved !== "object") saved = {};
  const state = {
    enabled: saved.enabled === true,
    seen: new Set(Array.isArray(saved.seen) ? saved.seen : []),
    latestRuns: new Map(Array.isArray(saved.latestRuns) ? saved.latestRuns : []),
    busy: false,
    message: "",
    listeners: new Set(),
  };
  const supported = () => win.isSecureContext && typeof win.Notification === "function";
  const permission = () => supported() ? win.Notification.permission : "unsupported";
  const save = () => {
    try {
      win.sessionStorage.setItem(storageKey, JSON.stringify({
        enabled: state.enabled, seen: [...state.seen].slice(-100),
        latestRuns: [...state.latestRuns].slice(-100),
      }));
    } catch { storageAvailable = false; }
  };
  const redraw = () => state.listeners.forEach(update => update());
  function status() {
    if (!supported()) return "System notifications are unavailable in this browser or connection. Check progress on this page.";
    if (permission() === "denied") return "Notifications are blocked. Allow them in this site's browser settings to enable them.";
    if (state.message) return state.message;
    if (!storageAvailable) return "Browser storage is unavailable. Notifications cannot stay enabled across a refresh.";
    if (state.busy) return "Waiting for browser permission…";
    if (!state.enabled || permission() !== "granted") return "Get a message when your PowerPoint is ready to download.";
    return "You’ll get a message when your PowerPoint is ready to download.";
  }
  function show(test = false, id = "test") {
    if (!state.enabled || permission() !== "granted") return;
    try {
      const notice = new win.Notification(test ? "Completion notifications enabled" : "PowerPoint ready to download", {
        body: test ? "This is a test notification." : "Export checks are complete. Return to the app to download and review your presentation.",
        tag: `ada-presentation-${id}`,
        silent: true,
      });
      notice.onclick = () => { win.focus(); notice.close(); };
      notice.onerror = () => {
        state.message = "The browser could not show a system notification. Check progress and downloads on this page.";
        redraw();
      };
      if (test) state.message = "Test message sent. Check your system notifications.";
    } catch {
      state.message = "System notifications are unavailable here. Check progress and downloads on this page.";
      redraw();
    }
  }
  async function toggle() {
    if (state.busy) return;
    state.message = "";
    if (state.enabled && permission() === "granted") {
      state.enabled = false;
      save(); redraw(); return;
    }
    if (!supported() || permission() === "denied") { redraw(); return; }
    // Request directly inside the button's user gesture, before any await.
    try {
      const response = permission() === "granted" ? Promise.resolve("granted") : win.Notification.requestPermission();
      state.busy = true; redraw();
      state.enabled = (await response) === "granted";
      if (!state.enabled && permission() !== "denied") state.message = "Permission was not granted. Notifications remain off.";
    } catch {
      state.enabled = false;
      state.message = "Permission could not be requested. Open the app directly in a browser tab and enable notifications there.";
    } finally {
      state.busy = false; save(); redraw();
    }
  }
  function complete(id, runId) {
    if (!id) return;
    // A restored server session may have cached content but no attempt record.
    // Recover that content's last run locally, instead of creating a new run.
    const run = typeof runId === "string" && runId ? runId : state.latestRuns.get(id) || "cached";
    const event = `${id}:${run}`;
    if (state.seen.has(event) || (!runId && state.seen.has(id))) return;
    state.latestRuns.set(id, run);
    // A result completed while notifications were off must not alert later.
    state.seen.add(event); save();
    if (state.enabled && permission() === "granted") state.message = "";
    show(false, event);
    redraw();
  }
  const controller = { state, permission, status, save, redraw, toggle, show, complete };
  win[CONTROLLER] = controller;
  return controller;
}

export default function(component) {
  const { parentElement, data } = component;
  const controller = controllerFor(window);
  const root = parentElement.querySelector(".completion-notice");
  if (data?.mode === "complete") {
    root.hidden = true;
    controller.complete(data.event_id, data.run_id);
    return;
  }
  root.hidden = false;
  const enable = root.querySelector(".notice-enable");
  const toggleText = root.querySelector(".notice-toggle-text");
  const test = root.querySelector(".notice-test");
  const status = root.querySelector(".notice-status");
  const update = () => {
    const { state } = controller;
    const active = state.enabled && controller.permission() === "granted";
    root.dataset.state = active ? "on" : controller.permission() === "denied" ? "blocked" : controller.permission() === "unsupported" ? "unsupported" : "off";
    enable.setAttribute("aria-checked", String(active));
    toggleText.textContent = state.busy ? "…" : active ? "On" : "Off";
    enable.disabled = state.busy || ["denied", "unsupported"].includes(controller.permission());
    test.disabled = !active;
    status.textContent = controller.status();
  };
  const onToggle = () => { void controller.toggle(); };
  const onTest = () => {
    controller.state.message = "";
    controller.show(true); controller.redraw();
  };
  controller.state.listeners.add(update);
  enable.addEventListener("click", onToggle);
  test.addEventListener("click", onTest);
  update();
  return () => {
    controller.state.listeners.delete(update);
    enable.removeEventListener("click", onToggle);
    test.removeEventListener("click", onTest);
  };
}
