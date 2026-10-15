// A local clock only: no model requests, widget state changes or network traffic.
export function formatDuration(seconds) {
  seconds = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  return `${hours ? `${hours}h ` : ""}${minutes}m ${seconds % 60}s`;
}

export default function({parentElement, data}) {
  // The host survives Streamlit data updates. Keep a single monotonic browser
  // anchor there, even if the component module is evaluated again. Cleanup
  // stops writers/listeners but retains timing state for the next render.
  const clockKey = Symbol.for('fourier.progressClock');
  let clock = parentElement[clockKey];
  clock?.dispose?.();
  const now = performance.now();
  const runId = data.run_id ?? 'legacy';
  const sameRun = clock && runId === (clock.data.run_id ?? 'legacy');
  if (clock && ((!sameRun && data.run_started_at < clock.data.run_started_at)
      || (sameRun &&
          ((data.stage_sequence ?? 0) < clock.sequence || (!clock.data.running && data.running))))) {
    // A delayed running/previous-stage snapshot cannot revive a terminal clock
    // or replace a newer phase. Reattach the writer to the accepted snapshot.
    data = clock.data;
  }
  if (!clock || (data.run_id ?? 'legacy') !== (clock.data.run_id ?? 'legacy')) {
    clock = {origin: now - data.elapsed * 1000, total: 0, stage: 0};
    parentElement[clockKey] = clock;
  }
  const sequence = data.stage_sequence ?? 0;
  const stageId = data.stage_id ?? 'processing';
  if (clock.sequence !== sequence || clock.stageId !== stageId) {
    clock.stageOffset = data.elapsed - data.stage_elapsed;
    clock.stage = 0;
  }
  clock.sequence = sequence;
  clock.stageId = stageId;
  clock.data = {...data};
  const owner = Symbol('timer-render');
  clock.owner = owner;
  const activity = parentElement.querySelector('[data-activity]');
  const doc = parentElement.ownerDocument;
  const win = doc?.defaultView;
  const position = () => {
    if (!activity || !win) return;
    const rects = [...doc.querySelectorAll('[data-testid="stToolbarActions"], [data-testid="stAppDeployButton"], [data-testid="stMainMenu"]')]
      .map(e => e.getBoundingClientRect()).filter(r => r.width && r.height);
    const left = Math.min(...rects.map(r => r.left));
    // Leave the existing completion bell and native toolbar controls intact.
    if (Number.isFinite(left)) activity.style.right = `${Math.max(8, Math.min(win.innerWidth - 40, win.innerWidth - left + 52))}px`;
  };
  if (activity) {
    activity.hidden = !data.running;
    const description = `Analysis running: ${data.label || 'Processing document'}`;
    activity.setAttribute('aria-label', description);
    activity.title = description;
  }
  position();
  win?.addEventListener('resize', position);
  const draw = () => {
    if (clock.owner !== owner) return;
    const elapsed = (performance.now() - clock.origin) / 1000;
    // Running updates never rebase the local anchor. At completion, preserve
    // the last displayed second if delivery occurred just after a clock tick.
    clock.total = Math.max(clock.total, Math.floor(data.running ? elapsed : data.elapsed));
    clock.stage = Math.max(clock.stage, Math.floor(data.running ? elapsed - clock.stageOffset : data.stage_elapsed));
    parentElement.querySelector('[data-total]').textContent = `Total elapsed: ${formatDuration(clock.total)}`;
    parentElement.querySelector('[data-stage]').textContent = `Current stage: ${formatDuration(clock.stage)}`;
  };
  draw();
  const timer = data.running ? setInterval(draw, 1000) : null;
  let disposed = false;
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    if (timer !== null) clearInterval(timer);
    win?.removeEventListener('resize', position);
    if (clock.owner === owner) clock.owner = null;
  };
  clock.dispose = dispose;
  return dispose;
}
