import assert from 'node:assert/strict';
import {test} from 'node:test';
import render, {formatDuration} from '../adaptive_document_agent/ui/assets/progress_timer.mjs';

test('duration formats whole elapsed seconds without an ETA', () => {
  assert.equal(formatDuration(-1), '0m 0s');
  assert.equal(formatDuration(59.9), '0m 59s');
  assert.equal(formatDuration(3661), '1h 1m 1s');
});

test('busy clock advances locally and cleans up; terminal clock stays frozen', t => {
  let now = 0;
  let callback;
  let cleared = 0;
  t.mock.method(performance, 'now', () => now);
  t.mock.method(globalThis, 'setInterval', fn => {callback = fn; return 1;});
  t.mock.method(globalThis, 'clearInterval', () => cleared++);
  const total = {}, stage = {};
  const parentElement = {querySelector: selector => ({'[data-total]': total, '[data-stage]': stage})[selector] || null};
  const stop = render({parentElement, data: {elapsed: 100, stage_elapsed: 5, running: true}});
  assert.equal(total.textContent, 'Total elapsed: 1m 40s');
  now = 4000;
  callback();
  assert.equal(total.textContent, 'Total elapsed: 1m 44s');
  assert.equal(stage.textContent, 'Current stage: 0m 9s');
  stop();
  assert.equal(cleared, 1);
  callback = null;
  render({parentElement, data: {elapsed: 104, stage_elapsed: 9, running: false}})();
  assert.equal(callback, null);
  assert.equal(total.textContent, 'Total elapsed: 1m 44s');
});

test('the toolbar runner follows task state, stays beside the bell and cleans up on unmount', t => {
  t.mock.method(globalThis, 'setInterval', () => 1);
  t.mock.method(globalThis, 'clearInterval', () => {});
  const listeners = new Set();
  const win = {innerWidth: 1200,
    addEventListener: (event, fn) => {assert.equal(event, 'resize'); listeners.add(fn);},
    removeEventListener: (event, fn) => listeners.delete(fn)};
  const activity = {style: {}, attributes: new Map(),
    setAttribute(name, value) {this.attributes.set(name, value);}};
  const nodes = {'[data-total]': {}, '[data-stage]': {}, '[data-activity]': activity};
  const parentElement = {querySelector: selector => nodes[selector],
    ownerDocument: {defaultView: win, querySelectorAll: () => [
      {getBoundingClientRect: () => ({left: 900, width: 260, height: 36})},
    ]}};
  const data = {elapsed: 5, stage_elapsed: 2, running: true, label: 'Understanding document',
    run_id: 'first', run_started_at: 100, stage_id: 'discovery', stage_sequence: 1};
  const stop = render({parentElement, data});
  assert.equal(activity.hidden, false);
  assert.equal(activity.attributes.get('aria-label'), 'Analysis running: Understanding document');
  assert.equal(activity.style.right, '352px'); // 52px reserved beside the native toolbar.
  assert.equal(listeners.size, 1);
  stop();
  assert.equal(listeners.size, 0);
  for (const label of ['Analysis stopped', 'PowerPoint ready to download']) {
    render({parentElement, data: {...data, label, running: false}})();
    assert.equal(activity.hidden, true);
  }
  render({parentElement, data: {...data, run_id: 'retry', run_started_at: 200,
    label: 'Retrying analysis'}})();
  assert.equal(activity.hidden, false);
  assert.match(activity.title, /Retrying analysis/);
});

function clockHarness(t) {
  let now = 0;
  let nextId = 0;
  const callbacks = new Map();
  t.mock.method(performance, 'now', () => now);
  t.mock.method(globalThis, 'setInterval', fn => {
    callbacks.set(++nextId, fn);
    return nextId;
  });
  t.mock.method(globalThis, 'clearInterval', id => callbacks.delete(id));
  const total = {}, stage = {};
  const parentElement = {querySelector: selector => ({'[data-total]': total, '[data-stage]': stage})[selector] || null};
  const initial = {run_id: 'attempt-1', run_started_at: 100, stage_id: 'discovery',
    stage_sequence: 2, elapsed: 10.2, stage_elapsed: 4.2, running: true, label: 'Batch 1'};
  return {total, stage, callbacks, initial,
    at(ms) {now = ms;},
    tick() {for (const callback of callbacks.values()) callback();},
    render(data) {return render({parentElement, data: {...initial, ...data}});}};
}

test('same-phase polls and batch text never rewind or rebase the browser clock', t => {
  const h = clockHarness(t);
  let stop = h.render();
  for (let i = 1; i <= 60; i++) {
    h.at(i * 1000);
    h.tick();
    const expectedTotal = `Total elapsed: ${formatDuration(10 + i)}`;
    const expectedStage = `Current stage: ${formatDuration(4 + i)}`;
    assert.equal(h.total.textContent, expectedTotal);
    assert.equal(h.stage.textContent, expectedStage);
    stop();
    // Alternating delivery delay/fractional rounding around the tick, plus a
    // changed batch message, must not produce 11 -> 10 -> 11 or jump ahead.
    stop = h.render({elapsed: 10.2 + i + (i % 2 ? -0.8 : 1.1),
      stage_elapsed: 4.2 + i + (i % 2 ? -0.8 : 1.1), label: `Batch ${i + 1}`});
    assert.equal(h.total.textContent, expectedTotal);
    assert.equal(h.stage.textContent, expectedStage);
    assert.equal(h.callbacks.size, 1);
  }
  stop();
  assert.equal(h.callbacks.size, 0);
});

test('new phases reset only current-stage time; stale phases and old callbacks cannot overwrite it', t => {
  const h = clockHarness(t);
  const oldStop = h.render();
  const oldTick = [...h.callbacks.values()][0];
  h.at(5000);
  h.tick();
  const stop = h.render({stage_id: 'extraction', stage_sequence: 3, elapsed: 15.2,
    stage_elapsed: 0.2, label: 'Extracting tables'});
  assert.equal(h.total.textContent, 'Total elapsed: 0m 15s');
  assert.equal(h.stage.textContent, 'Current stage: 0m 0s');
  assert.equal(h.callbacks.size, 1);
  oldTick();
  oldStop(); // Late framework cleanup belongs to the old render only.
  assert.equal(h.stage.textContent, 'Current stage: 0m 0s');
  h.at(8000);
  h.tick();
  assert.equal(h.stage.textContent, 'Current stage: 0m 3s');
  const staleStop = h.render({stage_sequence: 2, elapsed: 14, stage_elapsed: 8});
  assert.equal(h.stage.textContent, 'Current stage: 0m 3s');
  stop();
  h.at(9000);
  h.tick();
  assert.equal(h.stage.textContent, 'Current stage: 0m 4s');
  staleStop();
});

test('terminal clocks freeze without rewinding; retries reset and reject delayed prior attempts', t => {
  const h = clockHarness(t);
  h.render();
  h.at(2000);
  h.tick();
  assert.equal(h.stage.textContent, 'Current stage: 0m 6s');
  h.render({running: false, elapsed: 11.9, stage_elapsed: 5.9, label: 'Analysis stopped'})();
  assert.equal(h.total.textContent, 'Total elapsed: 0m 12s');
  assert.equal(h.stage.textContent, 'Current stage: 0m 6s');
  h.at(15000);
  h.render({elapsed: 20, stage_elapsed: 14})();
  assert.equal(h.stage.textContent, 'Current stage: 0m 6s');
  assert.equal(h.callbacks.size, 0);
  const stop = h.render({run_id: 'attempt-2', run_started_at: 200, stage_id: 'startup',
    stage_sequence: 0, elapsed: 0, stage_elapsed: 0});
  assert.equal(h.total.textContent, 'Total elapsed: 0m 0s');
  assert.equal(h.stage.textContent, 'Current stage: 0m 0s');
  h.at(17000);
  h.tick();
  h.render({elapsed: 100, stage_elapsed: 80}); // Delayed old attempt.
  stop();
  assert.equal(h.total.textContent, 'Total elapsed: 0m 2s');
  assert.equal(h.stage.textContent, 'Current stage: 0m 2s');
});
