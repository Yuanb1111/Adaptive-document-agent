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
  const parentElement = {querySelector: selector => selector === '[data-total]' ? total : stage};
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
