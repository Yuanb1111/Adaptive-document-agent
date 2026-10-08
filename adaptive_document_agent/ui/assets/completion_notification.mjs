// Trusted application code only. No document text, filenames or external assets.
// Keep stored consent/deduplication, but refresh the live delivery feedback.
const CONTROLLER = Symbol.for("adaptive-document-agent.completion-notice.v4");

function controllerFor(win) {
  if (win[CONTROLLER]) return win[CONTROLLER];
  const storageKey = `ada:completion:v1:${win.location.pathname}`;
  let saved = {};
  let storageAvailable = true;
  try { saved = JSON.parse(win.sessionStorage.getItem(storageKey) || "{}"); }
  catch { storageAvailable = false; }
  if (!saved || typeof saved !== "object") saved = {};
  const state = {
    // Default on when the browser has permission; preserve an explicit opt-out.
    enabled: saved.enabled !== false,
    seen: new Set(Array.isArray(saved.seen) ? saved.seen : []),
    latestRuns: new Map(Array.isArray(saved.latestRuns) ? saved.latestRuns : []),
    busy: false,
    message: "",
    preview: null,
    noticeSequence: 0,
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
    if (state.enabled && permission() === "default") return "Completion notifications are enabled by default. Click the switch and allow browser notifications to activate them.";
    if (!state.enabled || permission() !== "granted") return "Get a message when your PowerPoint is ready to download.";
    return "You’ll get a message when your PowerPoint is ready to download.";
  }
  function show(test = false, id = "test") {
    if (!state.enabled || permission() !== "granted") return;
    const sequence = ++state.noticeSequence;
    state.preview = {
      title: test ? "Test notification" : "PowerPoint ready to download",
      body: test ? "In-page preview. A silent system notification is also being requested."
                 : "Export checks are complete. Return to downloads to review your presentation.",
    };
    if (test) state.message = "Requesting a silent system notification…";
    try {
      const notice = new win.Notification(test ? "Completion notifications enabled" : "PowerPoint ready to download", {
        body: test ? "This is a test notification." : "Export checks are complete. Return to the app to download and review your presentation.",
        // Reusing a test tag replaces the prior notice and may suppress a banner.
        tag: test ? `ada-presentation-test-${Date.now()}-${sequence}` : `ada-presentation-${id}`,
        silent: true,
      });
      let settled = false;
      let timer;
      const report = message => {
        if (sequence !== state.noticeSequence) return;
        state.message = message;
        redraw();
      };
      notice.onclick = () => { win.focus(); notice.close(); };
      notice.onshow = () => {
        if (settled) return;
        settled = true;
        win.clearTimeout(timer);
        if (test) report("The browser reported the notification as shown. No banner? Check Windows notification settings and Do not disturb.");
      };
      notice.onerror = () => {
        settled = true;
        win.clearTimeout(timer);
        report("The browser could not show a system notification. The in-page notice remains available.");
      };
      if (test) timer = win.setTimeout(() => {
        if (!settled) report("No display confirmation from the browser. Check Windows notification settings for your browser, notification banners and Do not disturb.");
      }, 3500);
    } catch {
      state.message = "System notifications are unavailable here. The in-page notice remains available.";
      redraw();
    }
  }
  async function toggle() {
    if (state.busy) return;
    state.message = "";
    if (state.enabled && permission() === "granted") {
      state.enabled = false;
      state.noticeSequence++;
      state.preview = null;
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
  const trigger = root.querySelector(".notice-trigger");
  const panel = root.querySelector(".notice-panel");
  const enable = root.querySelector(".notice-enable");
  const toggleText = root.querySelector(".notice-toggle-text");
  const test = root.querySelector(".notice-test");
  const status = root.querySelector(".notice-status");
  const preview = root.querySelector(".notice-preview");
  const previewTitle = root.querySelector(".notice-preview-title");
  const previewBody = root.querySelector(".notice-preview-body");
  const dismiss = root.querySelector(".notice-dismiss");
  const update = () => {
    const { state } = controller;
    const active = state.enabled && controller.permission() === "granted";
    root.dataset.state = active ? "on" : controller.permission() === "denied" ? "blocked" : controller.permission() === "unsupported" ? "unsupported" : "off";
    enable.setAttribute("aria-checked", String(active));
    toggleText.textContent = state.busy ? "…" : active ? "On" : "Off";
    enable.disabled = state.busy || ["denied", "unsupported"].includes(controller.permission());
    test.disabled = !active;
    status.textContent = controller.status();
    trigger.setAttribute("aria-label", `Completion notifications: ${active ? "On" : "Off"}`);
    preview.hidden = !state.preview;
    previewTitle.textContent = state.preview?.title || "";
    previewBody.textContent = state.preview?.body || "";
  };
  const close = (restoreFocus = false) => {
    panel.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    if (restoreFocus) trigger.focus();
  };
  const onTrigger = () => {
    panel.hidden = !panel.hidden;
    trigger.setAttribute("aria-expanded", String(!panel.hidden));
    if (!panel.hidden) (enable.disabled ? test.disabled ? trigger : test : enable).focus();
  };
  const onOutside = event => {
    if (!event.composedPath().includes(root)) close();
  };
  const onEscape = event => {
    if (event.key === "Escape" && !panel.hidden) { close(true); event.preventDefault(); }
  };
  // Place beside the live Streamlit toolbar, including its running indicator.
  // Only geometry is read; native toolbar controls and document data are untouched.
  const position = () => {
    const controls = document.querySelectorAll('[data-testid="stToolbarActions"], [data-testid="stAppDeployButton"], [data-testid="stMainMenu"]');
    const rects = [...controls].map(control => control.getBoundingClientRect()).filter(rect => rect.width && rect.height);
    const left = Math.min(...rects.map(rect => rect.left));
    if (Number.isFinite(left) && left > 48) {
      root.style.setProperty("--notice-right", `${window.innerWidth - left + 8}px`);
    }
  };
  const onToggle = () => { void controller.toggle(); };
  const onTest = () => {
    controller.state.message = "";
    controller.show(true); controller.redraw();
  };
  const onDismiss = () => { controller.state.preview = null; controller.redraw(); };
  controller.state.listeners.add(update);
  enable.addEventListener("click", onToggle);
  test.addEventListener("click", onTest);
  trigger.addEventListener("click", onTrigger);
  dismiss.addEventListener("click", onDismiss);
  document.addEventListener("pointerdown", onOutside);
  document.addEventListener("keydown", onEscape);
  window.addEventListener("resize", position);
  const observer = typeof ResizeObserver === "function" ? new ResizeObserver(position) : null;
  const toolbar = document.querySelector('[data-testid="stToolbarActions"]')?.parentElement;
  if (toolbar) observer?.observe(toolbar);
  position();
  update();
  return () => {
    controller.state.listeners.delete(update);
    enable.removeEventListener("click", onToggle);
    test.removeEventListener("click", onTest);
    trigger.removeEventListener("click", onTrigger);
    dismiss.removeEventListener("click", onDismiss);
    document.removeEventListener("pointerdown", onOutside);
    document.removeEventListener("keydown", onEscape);
    window.removeEventListener("resize", position);
    observer?.disconnect();
  };
}
