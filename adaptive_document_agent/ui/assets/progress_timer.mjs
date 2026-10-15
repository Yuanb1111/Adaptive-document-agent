// A local clock only: no model requests, widget state changes or network traffic.
export function formatDuration(seconds) {
  seconds = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  return `${hours ? `${hours}h ` : ""}${minutes}m ${seconds % 60}s`;
}

export default function({parentElement, data}) {
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
  const started = performance.now();
  const draw = () => {
    const delta = data.running ? (performance.now() - started) / 1000 : 0;
    parentElement.querySelector('[data-total]').textContent = `Total elapsed: ${formatDuration(data.elapsed + delta)}`;
    parentElement.querySelector('[data-stage]').textContent = `Current stage: ${formatDuration(data.stage_elapsed + delta)}`;
  };
  draw();
  const timer = data.running ? setInterval(draw, 1000) : null;
  return () => {
    if (timer !== null) clearInterval(timer);
    win?.removeEventListener('resize', position);
  };
}
