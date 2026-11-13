// The Due tile counts what the desk shows when it is tapped: the dated agenda items. Orders
// that need a decision are counted on the Orders tab badge instead.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';

installDom();
const { summaryTiles } = await import('../js/views/realism-status.js');
const { tabBar } = await import('../js/views/realism-tabs.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url), 'utf8'));

const tileN = (tiles, label) => {
  const t = tiles.querySelectorAll('.tile').find((x) => words(x.querySelector('.tile-label') ?? x).includes(label));
  return words(t.querySelector('.tile-n'));
};

test('orders that need a decision and no dated agenda item: Due reads 0, the Orders badge counts them', () => {
  const rv = {
    ...fixture,
    documents: fixture.listing,
    agenda: { ...fixture.agenda, items: [{ ...fixture.agenda.items[0], deadline: null }] },
    orders: { orders: [
      { ...fixture.orders.orders[0], decision_needed: true, status: 'moving' },
      { ...fixture.orders.orders[1], decision_needed: true, status: 'moving' },
    ] },
  };
  const picked = [];
  const tiles = summaryTiles(rv, (p) => picked.push(p));
  assert.equal(tileN(tiles, 'Due'), '0', 'the desk would open on no dated item');
  const [, , orders] = tabBar(rv, { tab: 'desk', side: 'papers', chat: { open: false } }, () => {}).querySelectorAll('button');
  assert.match(words(orders), /\b2\b/, 'the Orders badge still counts the orders that need you');
  tiles.querySelectorAll('.tile').find((x) => words(x).includes('Due')).click();
  assert.deepEqual(picked, [{ tab: 'desk' }], 'the Due tile still opens the desk');
});
