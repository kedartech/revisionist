// A seat is told the same wake counts whoever plays the other leaders, so it cannot tell
// from them whether its Done is the one that runs the wake. A commit still out after a
// moment is that one: the busy line and the overlay then say the wake is running.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { RUNNING, RUNNING_AFTER_MS, SEALING, commitBusy, runningAfter } from '../js/views/realism-wake.js';

function clock() {
  const timers = [];
  return {
    timers,
    wait: (fn, ms) => { timers.push({ fn, ms, live: true }); return timers.length - 1; },
    stop: (id) => { timers[id].live = false; },
    fire: () => timers.filter((t) => t.live).forEach((t) => { t.live = false; t.fn(); }),
  };
}

test('a commit that may not be the last says it is sealing, and upgrades while it is still out', () => {
  const wake = { committed: 0, humans: 8 };
  assert.equal(commitBusy(wake), SEALING);
  const c = clock();
  let said = 0;
  runningAfter(commitBusy(wake), () => { said += 1; }, c);
  assert.equal(c.timers.length, 1);
  assert.equal(c.timers[0].ms, RUNNING_AFTER_MS);
  assert.equal(said, 0);
  c.fire();
  assert.equal(said, 1);
});

test('a commit that returns first cancels the upgrade', () => {
  const c = clock();
  let said = 0;
  const cancel = runningAfter(SEALING, () => { said += 1; }, c);
  cancel();
  c.fire();
  assert.equal(said, 0);
});

test('a call that already runs the wake, or any other call, sets no timer', () => {
  const c = clock();
  runningAfter(RUNNING, () => {}, c);
  runningAfter('Sealing your vote…', () => {}, c);
  assert.equal(c.timers.length, 0);
});
