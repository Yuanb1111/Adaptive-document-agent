// A local clock only: no model requests, widget state changes or network traffic.
export function formatDuration(seconds) {
  seconds = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  return `${hours ? `${hours}h ` : ""}${minutes}m ${seconds % 60}s`;
}

export default function({parentElement, data}) {
  const started = performance.now();
  const draw = () => {
    const delta = data.running ? (performance.now() - started) / 1000 : 0;
    parentElement.querySelector('[data-total]').textContent = `Total elapsed: ${formatDuration(data.elapsed + delta)}`;
    parentElement.querySelector('[data-stage]').textContent = `Current stage: ${formatDuration(data.stage_elapsed + delta)}`;
  };
  draw();
  const timer = data.running ? setInterval(draw, 1000) : null;
  return () => { if (timer !== null) clearInterval(timer); };
}
