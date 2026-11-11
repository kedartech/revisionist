// Unit tests for the orders log (Phase 4 In-Tray follow-up, unit T4). Only the pure helpers are run:
// ordersLog builds DOM with h(), so it is not called here. Run: node --test test/p4-orders.test.js
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { newestFirst, orderStage } from '../js/views/realism-orders.js';

const fixture = JSON.parse(readFileSync(fileURLToPath(new URL('./fixtures/realism-seat.json', import.meta.url)), 'utf8'));

function part(over = {}) {
  return { ask: 'Ask', to: null, route: null, fidelity: null, refused_under: null, reason: null, accepted: null, applied: null, ...over };
}

function result(filed, ...parts) {
  return { id: `r-${filed}`, filed, parts };
}

test('the fixture result is landed, so its stage is finished on its applied day', () => {
  assert.equal(orderStage(fixture.results[0]), 'Finished 14 October 1941');
});

test('an order with no part applied or refused is only made', () => {
  assert.equal(orderStage(result('1941-10-12', part())), 'Made 12 October 1941');
});

test('an order with no parts is only made', () => {
  assert.equal(orderStage(result('1941-10-12')), 'Made 12 October 1941');
});

test('a worded filed day is shown as given when the order is only made', () => {
  assert.equal(orderStage(result('1 September 1941', part())), 'Made 1 September 1941');
});

test('an order is finished on the latest applied day of its parts', () => {
  const r = result('1941-10-12',
    part({ applied: '9 October 1941' }),
    part({ applied: '21 October 1941' }),
    part({ applied: '3 November 1941' }));
  assert.equal(orderStage(r), 'Finished 3 November 1941');
});

test('an order with some parts applied and one still open has landed in part', () => {
  const r = result('1941-10-12', part({ applied: '14 October 1941' }), part());
  assert.equal(orderStage(r), 'Landed in part');
});

test('an order with one part refused and one applied has landed in part', () => {
  const r = result('1941-10-12', part({ refused_under: 'Refused under the Neutrality Act' }), part({ applied: '14 October 1941' }));
  assert.equal(orderStage(r), 'Landed in part');
});

test('an order with every part refused is refused', () => {
  const r = result('1941-10-12',
    part({ refused_under: 'Refused under the Neutrality Act' }),
    part({ refused_under: 'Refused under the Neutrality Act' }));
  assert.equal(orderStage(r), 'Refused');
});

test('a single refused part is refused, not landed in part', () => {
  assert.equal(orderStage(result('1941-10-12', part({ refused_under: 'Refused under the Neutrality Act' }))), 'Refused');
});

test('newestFirst puts the latest filed order at the top and keeps ties in order', () => {
  const a = result('1941-10-01');
  const b = result('1941-10-12');
  const c = result('1941-10-12');
  const out = newestFirst([a, b, c]);
  assert.deepEqual(out.map((r) => r.id), [b.id, c.id, a.id]);
});

test('newestFirst sorts worded filed days by their real date', () => {
  const sept3 = result('3 September 1941');
  const oct14 = result('14 October 1941');
  const sept1 = result('1 September 1941');
  assert.deepEqual(newestFirst([sept3, oct14, sept1]).map((r) => r.id), [oct14.id, sept3.id, sept1.id]);
});

test('newestFirst sorts an ISO filed day and a worded one together', () => {
  const iso = result('1941-10-12');
  const worded = result('14 October 1941');
  const earlier = result('1 September 1941');
  assert.deepEqual(newestFirst([earlier, iso, worded]).map((r) => r.id), [worded.id, iso.id, earlier.id]);
});

test('newestFirst does not mutate its input', () => {
  const input = [result('1941-10-01'), result('1941-10-12')];
  const before = input.map((r) => r.id);
  newestFirst(input);
  assert.deepEqual(input.map((r) => r.id), before);
});

test('the fixture results sort without a document', () => {
  assert.deepEqual(newestFirst(fixture.results).map((r) => r.id), fixture.results.map((r) => r.id));
});
