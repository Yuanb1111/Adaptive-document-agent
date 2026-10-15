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
  const data = {elapsed: 5, stage_elapsed: 2, running: true, label: 'Understanding document'};
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
  render({parentElement, data: {...data, label: 'Retrying analysis'}})();
  assert.equal(activity.hidden, false);
  assert.match(activity.title, /Retrying analysis/);
});
