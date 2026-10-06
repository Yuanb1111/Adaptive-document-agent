// Trusted application code only. No document text, filenames or external assets.
const CONTROLLER = Symbol.for("adaptive-document-agent.completion-notice.v1");

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
    sound: saved.sound === true,
    seen: new Set(Array.isArray(saved.seen) ? saved.seen : []),
    latestRuns: new Map(Array.isArray(saved.latestRuns) ? saved.latestRuns : []),
    audio: null,
    busy: false,
    message: "",
    listeners: new Set(),
  };
  const supported = () => win.isSecureContext && typeof win.Notification === "function";
  const permission = () => supported() ? win.Notification.permission : "unsupported";
  const save = () => {
    try {
      win.sessionStorage.setItem(storageKey, JSON.stringify({
        enabled: state.enabled, sound: state.sound, seen: [...state.seen].slice(-100),
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
    if (!state.enabled || permission() !== "granted") return "Notifications are off. Enable them before generation finishes.";
    if (state.sound && !state.audio) return "Notifications are on. Click Test notification to re-enable sound after this page refresh.";
    return "Notifications are on for this tab. You will be notified when a verified PowerPoint is ready.";
  }
  function unlockSound() {
    if (!state.sound) return;
    const AudioContext = win.AudioContext || win.webkitAudioContext;
    if (!AudioContext) {
      state.message = "Notifications are on; this browser does not support the optional sound.";
      return;
    }
    try {
      state.audio ??= new AudioContext();
      if (state.audio.state === "suspended") {
        return state.audio.resume().catch(() => {
          state.message = "Notifications are on; sound was blocked by the browser.";
          redraw();
        });
      }
    } catch {
      state.message = "Notifications are on; sound is unavailable in this browser.";
    }
  }
  function playSound() {
    if (!state.sound) return;
    if (!state.audio || state.audio.state !== "running") {
      state.message = "PowerPoint is ready. The browser blocked sound; click Test notification to re-enable it.";
      redraw();
      return;
    }
    try {
      const oscillator = state.audio.createOscillator();
      const gain = state.audio.createGain();
      const now = state.audio.currentTime;
      oscillator.frequency.setValueAtTime(740, now);
      gain.gain.setValueAtTime(0, now);
      gain.gain.linearRampToValueAtTime(.12, now + .02);
      gain.gain.exponentialRampToValueAtTime(.001, now + .3);
      oscillator.connect(gain).connect(state.audio.destination);
      oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
      oscillator.start(now);
      oscillator.stop(now + .32);
    } catch {
      state.message = "PowerPoint is ready. The optional sound could not play.";
      redraw();
    }
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
      playSound();
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
      unlockSound();
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
    show(false, event);
    redraw();
  }
  const controller = { state, permission, status, save, redraw, toggle, unlockSound, show, complete };
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
  const sound = root.querySelector(".notice-sound");
  const test = root.querySelector(".notice-test");
  const status = root.querySelector(".notice-status");
  const update = () => {
    const { state } = controller;
    const active = state.enabled && controller.permission() === "granted";
    enable.textContent = active ? "Turn off completion notifications" : "Enable completion notifications";
    enable.disabled = state.busy || ["denied", "unsupported"].includes(controller.permission());
    sound.checked = state.sound;
    sound.disabled = !active;
    test.disabled = !active;
    status.textContent = controller.status();
  };
  const onToggle = () => { void controller.toggle(); };
  const onSound = () => {
    controller.state.sound = sound.checked;
    controller.state.message = "";
    controller.unlockSound();
    controller.save(); controller.redraw();
  };
  const onTest = () => {
    controller.state.message = "";
    const audioReady = controller.unlockSound();
    // AudioContext.resume may settle asynchronously after the user gesture.
    Promise.resolve(audioReady).then(() => { controller.show(true); controller.redraw(); });
  };
  controller.state.listeners.add(update);
  enable.addEventListener("click", onToggle);
  sound.addEventListener("change", onSound);
  test.addEventListener("click", onTest);
  update();
  return () => {
    controller.state.listeners.delete(update);
    enable.removeEventListener("click", onToggle);
    sound.removeEventListener("change", onSound);
    test.removeEventListener("click", onTest);
  };
}
