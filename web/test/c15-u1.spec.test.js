// Spec for 15a unit U1 (status strip and tiles), written with the console contract: the unit
// makes it pass and never edits it. The strip shows the date and, in multiplayer only, the
// countdown and the players-done bar; no wake number (Josh, 12 Nov).
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { buttons, installDom, words } from './dom-fake.js';

installDom();
const { statusStrip, summaryTiles } = await import('../js/views/realism-status.js');
const { commitLabel, wakeHeader } = await import('../js/views/realism-wake.js');

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));
const OWNS = ['js/views/realism-status.js', 'css/c-header.css', 'js/views/realism-wake.js'];

const soon = new Date(Date.now() + (2 * 60 + 5) * 60_000).toISOString();
const room = (wake) => ({ ...fixture, documents: fixture.listing, wake: { ...wake, deadline: wake.deadline === null ? null : soon } });
const ui = { tab: 'desk', side: 'papers', chat: { open: false } };
const calls = [];
const act = (...args) => calls.push(args);

test('the strip shows the world date in words and never a wake number', () => {
  const strip = statusStrip(room(fixture.wake), ui, { act });
  assert.ok(strip.getAttribute('aria-label'), 'the strip is a named region');
  assert.match(words(strip), /20 October 1941/);
  assert.doesNotMatch(words(strip), /\bwake\s*\d/i);
  assert.doesNotMatch(words(strip), /1941-10-20|T\d\d:/, 'no ISO date or time on screen');
});

test('multiplayer: a countdown to the deadline and the players-done bar, counts only', () => {
  const strip = statusStrip(room({ ...fixture.wake, committed: 1, humans: 3 }), ui, { act });
  const clock = strip.querySelector('time.rl-countdown');
  assert.ok(clock, 'a time.rl-countdown');
  assert.equal(clock.getAttribute('datetime'), soon);
  assert.ok(words(clock).length > 0, 'the countdown says how long is left');
  const bar = strip.querySelector('.rl-done-bar');
  assert.ok(bar, 'a .rl-done-bar');
  assert.equal(bar.getAttribute('aria-label'), '1 of 3 players done');
  assert.equal(bar.children.length, 3);
  assert.equal(bar.children.filter((c) => c.classList.contains('on')).length, 1);
});

test('solo: no countdown and no players-done bar', () => {
  const strip = statusStrip(room(fixture.wake_solo), ui, { act });
  assert.equal(strip.querySelector('.rl-countdown'), null);
  assert.equal(strip.querySelector('.rl-done-bar'), null);
  assert.match(words(strip), /20 October 1941/);
});

test('Done for today: the primary button commits through act, then a word once done', () => {
  calls.length = 0;
  const open = statusStrip(room({ ...fixture.wake, you_committed: false }), ui, { act });
  const [done] = buttons(open, 'Done for today');
  assert.ok(done, 'a Done for today button');
  assert.ok(done.classList.contains('btn-1'), 'the primary button level');
  done.click();
  assert.equal(calls.length, 1);
  assert.equal(calls[0][1], 'commit');
  const sealed = room({ ...fixture.wake, you_committed: true, committed: 1, humans: 2 });
  const after = statusStrip(sealed, ui, { act });
  assert.equal(buttons(after, 'Done for today').length, 0);
  assert.match(words(after), new RegExp(commitLabel(sealed.wake)));
  assert.equal(buttons(statusStrip(room({ ...fixture.wake_solo, deadline: null }), ui, { act }), 'Done for today').length, 0,
    'no commit while no wake is open');
});

test('four tiles count from the seat\'s own data, each a button that picks its panel', () => {
  const rv = {
    ...fixture,
    documents: { ...fixture.listing, unread: 5 },
    agenda: { ...fixture.agenda, items: [{ ...fixture.agenda.items[0] }, { ...fixture.agenda.items[0], id: 'a2', deadline: null }] },
    orders: { orders: [
      { ...fixture.orders.orders[1], decision_needed: true, status: 'moving' },
      { ...fixture.orders.orders[0], decision_needed: false, status: 'moving' },
      { ...fixture.orders.orders[0], id: 'o9', decision_needed: false, status: 'moving' },
      { ...fixture.orders.orders[2], decision_needed: false, status: 'enacted' },
    ] },
    threats: fixture.threats.slice(0, 1),
  };
  const picked = [];
  const tiles = summaryTiles(rv, (p) => picked.push(p));
  const all = tiles.querySelectorAll('.tile');
  assert.equal(all.length, 4);
  const read = (label) => all.find((t) => words(t.querySelector('.tile-label') ?? t).includes(label));
  assert.equal(words(read('Unread').querySelector('.tile-n')), '5');
  assert.equal(words(read('Due').querySelector('.tile-n')), '2', 'a dated agenda item and an order that needs you');
  assert.equal(words(read('Orders under way').querySelector('.tile-n')), '3');
  assert.equal(words(read('Threats').querySelector('.tile-n')), '1');
  for (const t of all) assert.equal(t.tagName.toLowerCase(), 'button');
  read('Unread').click();
  read('Due').click();
  read('Orders under way').click();
  read('Threats').click();
  assert.deepEqual(picked, [{ tab: 'papers' }, { tab: 'desk' }, { tab: 'orders' }, { tab: 'orders' }]);
});

test('the header wake keeps the count and the commit but no wake number', () => {
  const head = wakeHeader(fixture.wake, { act });
  assert.doesNotMatch(words(head), /\bWake\s*\d/);
  assert.match(words(head), /1 of 2 players done/);
});

test('the strip\'s stylesheet: strip, countdown and bar styled, the pulse still under reduced motion', () => {
  const css = read('css/c-header.css').replace(/\/\*[\s\S]*?\*\//g, '');
  for (const sel of ['.rl-strip', '.rl-countdown', '.rl-done-bar']) assert.ok(css.includes(sel), sel);
  if (/animation\s*:/.test(css)) {
    const reduced = /@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*?)\n\}/.exec(css);
    assert.ok(reduced, 'a reduced-motion block');
    assert.match(reduced[1], /animation:\s*none/);
  }
});

test('owned files: no HTML parsing, no inline style, no colour literal', () => {
  for (const f of OWNS) {
    const src = read(f).replace(/\/\*[\s\S]*?\*\//g, '');
    assert.doesNotMatch(src, /innerHTML|style=|\.style\./, f);
    if (f.endsWith('.css')) assert.doesNotMatch(src, /#[0-9a-fA-F]{3,8}\b|rgba?\(/, f);
  }
});
