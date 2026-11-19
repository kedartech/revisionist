import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { installDom, words } from './dom-fake.js';
import { courtBoard } from '../js/views/realism-court.js';
import { statusStrip } from '../js/views/realism-status.js';

installDom();
const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));

test('decision squares show their own waiting load out of the court limit, slow at and over it', () => {
  const rv = structuredClone(fixture);
  const steps = rv.court.paths[0].steps;
  steps[0].orders = Array.from({ length: 3 }, (_, i) => ({ id: `own-${i}`, label: 'Own order', held_days: 0 }));
  // Other people's roster loads must never contribute to this square.
  rv.people = { yours: [{ person: steps[0].person, load: 99 }], opponents: [], others: [] };
  const view = courtBoard(rv, {});
  const squares = view.querySelectorAll('.rl-court-sq');
  const loads = squares.map((sq) => sq.querySelector('.rl-court-load'));
  assert.ok(loads.every(Boolean), 'every decision square, including You and empty ones');
  assert.equal(loads[0].querySelectorAll('.rl-court-pip.on').length, 3);
  assert.equal(loads[0].getAttribute('aria-label'), '3 orders waiting; load limit 2; slow');
  assert.match(words(loads[0]), /3 of 2 · slow/);
  assert.equal(loads[1].querySelectorAll('.rl-court-pip.on').length, 0);
  assert.equal(loads[1].querySelectorAll('.rl-court-pip').length, 2);
  assert.doesNotMatch(words(loads[1]), /slow/);
  assert.equal(view.querySelectorAll('.clerk .rl-court-load').length, 0);
  steps[0].orders.pop();
  const atLimit = courtBoard(rv, {}).querySelector('.rl-court-load');
  assert.match(words(atLimit), /2 of 2 · slow/);
  // The same person can hold this seat's orders on more than one path.
  rv.court.paths[1].steps[0].person = steps[0].person;
  rv.court.paths[1].steps[0].orders = [{ id: 'other-path', label: 'Own naval order', held_days: 0 }, steps[0].orders[0]];
  const shared = courtBoard(rv, {}).querySelectorAll('.rl-court-load');
  assert.equal(shared[0].getAttribute('aria-label'), '2 orders waiting; load limit 2; slow');
  assert.equal(shared[3].getAttribute('aria-label'), shared[0].getAttribute('aria-label'));
});

test('the status strip counts only own orders filed in this wake, including settled ones, without a cap', () => {
  const rv = structuredClone(fixture);
  rv.wake.wake = 7;
  rv.record.orders = [
    ...Array.from({ length: 12 }, (_, i) => ({ id: `own-${i}`, wake: 7, moving: i % 2 === 0 })),
    { id: 'earlier', wake: 6, moving: true },
    { id: 'next', wake: 8, moving: true },
  ];
  const strip = statusStrip(rv, {}, { act: () => {} });
  assert.ok(strip.querySelector('.rl-filed-count'), 'the strip shows the filed count');
  assert.equal(words(strip.querySelector('.rl-filed-count')), '12 orders filed this wake.');
  rv.record.orders = [{ id: 'single', wake: 7 }];
  assert.equal(words(statusStrip(rv, {}, { act: () => {} }).querySelector('.rl-filed-count')), '1 order filed this wake.');
  rv.wake.wake = 8;
  assert.equal(words(statusStrip(rv, {}, { act: () => {} }).querySelector('.rl-filed-count')), '0 orders filed this wake.');
});
