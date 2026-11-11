// Spec for Train 2 unit O, written with contract K2: the unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { NO_ORDERS, orderChip, orderGroups, orderLines } from '../js/views/realism-orders.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

const { record, orders } = fixture;
const entry = (extra = {}) => ({ id: 'x', wake: 1, filed: '1 October 1941', settled: null, asked: 'Do it', to: null, holder: null,
  status: 'on its way', moving: true, track: null, due: null, said: null, ...extra });

test('the chip says where an order stands', () => {
  const need = orders.orders.find((o) => o.decision_needed);
  assert.deepEqual(orderChip(entry({ track: need.id }), need), { word: 'Needs you', tone: 'need' });
  assert.deepEqual(orderChip(entry(), null), { word: 'Under way', tone: 'moving' });
  const settled = (status) => orderChip(entry({ moving: false, status, settled: '9 October 1941' }), null);
  assert.deepEqual(settled('carried out loosely'), { word: 'Carried out', tone: 'ok' });
  assert.deepEqual(settled('carried out'), { word: 'Carried out', tone: 'ok' });
  assert.deepEqual(settled('enacted'), { word: 'Carried out', tone: 'ok' });
  assert.deepEqual(settled('agreed'), { word: 'Agreed', tone: 'ok' });
  assert.deepEqual(settled('rebuffed'), { word: 'Declined', tone: 'bad' });
  assert.deepEqual(settled('refused'), { word: 'Refused', tone: 'bad' });
  assert.deepEqual(settled('lapsed'), { word: 'Lapsed', tone: 'quiet' });
  assert.deepEqual(settled('withdrawn'), { word: 'Withdrawn', tone: 'quiet' });
  assert.deepEqual(settled('held over'), { word: 'Held over', tone: 'quiet' });
});

test('a tracker order that does not wait on the seat is not "Needs you"', () => {
  const moving = orders.orders.find((o) => o.status === 'moving' && !o.decision_needed);
  assert.equal(orderChip(entry({ track: moving.id }), moving).word, 'Under way');
});

test('the lines show only what is set, the holder only while moving and not the addressee', () => {
  assert.deepEqual(orderLines(entry({ to: 'Harold R. Stark', holder: 'Harold R. Stark', due: '21 October 1941' })),
    ['To Harold R. Stark', 'Answer expected 21 October 1941']);
  assert.deepEqual(orderLines(entry({ holder: 'Sam Rayburn' })), ['With Sam Rayburn']);
  assert.deepEqual(orderLines(entry({ moving: false, to: 'Burton K. Wheeler', settled: '14 October 1941', said: 'No.' })),
    ['To Burton K. Wheeler', 'Settled 14 October 1941', '“No.”']);
  assert.deepEqual(orderLines(entry({ moving: false, holder: 'Someone', status: 'enacted' })), []);
});

test('the record splits into needs you, moving and finished, in record order', () => {
  const g = orderGroups(record, orders);
  assert.deepEqual(g.need.map((e) => e.track), ['o-convoy']);
  assert.deepEqual(g.moving.map((e) => e.id), ['a90f3e6b1c22', '0b7d24c9e815']);
  assert.deepEqual(g.finished.map((e) => e.id), [
    'e43a91d07f6c', '7c2f8e0a3d91', 'c1a7e5f20b3d', 'c2b8f6031c4e', 'c3c907142d5f',
    'c4da18253e60', 'c5eb29364f71', 'c6fc3a475082', 'c70d4b586193', 'c81e5c6972a4',
  ]);
  assert.deepEqual(orderGroups({ orders: [], wake: null }, { orders: [] }), { need: [], moving: [], finished: [] });
});

test('the empty line and the heading', () => {
  assert.equal(NO_ORDERS, 'No orders yet. Pick an idea or write one.');
  const src = read('js/views/realism-orders.js');
  assert.match(src, /'Your orders'/);
  assert.match(src, /Finished \(\$\{/);
});
