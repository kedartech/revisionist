// Unit tests for the receipt on an order's ledger line, against the fixture. Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { installDom, words } from './dom-fake.js';

installDom();
const acks = await import('../js/views/realism-acks.js');
const { orderCards } = await import('../js/views/realism-orders.js');

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));
const receipted = fixture.record.orders.filter((o) => o.receipt);
const cardsOf = (record, onOpen) => [...orderCards(record, fixture.orders, () => null, onOpen).querySelectorAll('.rl-oc-card')];

test('the fixture has one receipted order, so the cards below prove something', () => {
  assert.equal(receipted.length, 1);
});

test('receiptLine is null for an order with no receipt, or from a payload without the key', () => {
  assert.equal(acks.receiptLine(null, () => {}), null);
  assert.equal(acks.receiptLine(undefined, () => {}), null);
});

test('receiptLine words the receipt and its day, as a button that names what it opens', () => {
  const btn = acks.receiptLine(receipted[0].receipt, () => {});
  assert.equal(btn.tagName, 'BUTTON');
  assert.equal(btn.getAttribute('type'), 'button');
  assert.ok(btn.classList.contains('rl-receipt'));
  assert.equal(words(btn), 'Passed on, 12 October 1941');
  assert.equal(btn.getAttribute('aria-label'), 'Open the paper: Passed on, 12 October 1941');
});

test('pressing the receipt opens the paper by its id', () => {
  const opened = [];
  acks.receiptLine({ word: 'Carried out in full', day: '21 October 1941', doc: 'd-x' }, (d) => opened.push(d)).click();
  assert.deepEqual(opened, [{ id: 'd-x' }]);
});

test('the acknowledgement list and its helpers are gone', () => {
  assert.equal(acks.ackLines, undefined);
  assert.equal(acks.ackThread, undefined);
});

test('a receipted order card shows its receipt and opens the paper; the others show none', () => {
  const opened = [];
  const withReceipt = cardsOf(fixture.record, (d) => opened.push(d)).filter((c) => c.querySelector('.rl-receipt'));
  assert.equal(withReceipt.length, 1);
  assert.ok(words(withReceipt[0]).includes('Revise the Neutrality Act'));
  withReceipt[0].querySelector('.rl-receipt').click();
  assert.deepEqual(opened, [{ id: 'd-reply-1012' }]);
});

test('every order card keeps its one status chip beside the receipt', () => {
  for (const card of cardsOf(fixture.record, () => {})) assert.equal(card.querySelectorAll('.chip').length, 1, words(card));
});

test('an order card from a payload without the key, or drawn with no handler, still draws', () => {
  const bare = { ...fixture.record, orders: fixture.record.orders.map(({ receipt, ...rest }) => rest) };
  assert.equal(cardsOf(bare, () => {}).filter((c) => c.querySelector('.rl-receipt')).length, 0);
  assert.equal(cardsOf(fixture.record).filter((c) => c.querySelector('.rl-receipt')).length, 1);
});

test('the room opens a receipt through the same reader as a tray row', () => {
  assert.match(read('js/views/realism-room.js'), /orderCards\(rv\.record, rv\.orders, [^\n]*\n?[^\n]*\bopen\b/);
});

test('the receipt is styled with tokens only', () => {
  const css = read('css/p4-acks.css').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.match(css, /\.rl-receipt\b/);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b/);
});
