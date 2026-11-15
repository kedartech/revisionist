// Wake playback: while a wake runs, the overlay plays the seat's own orders in the order they
// were filed (an order on a path as its token on a small copy of that path, a move as its mark
// on the map), then the stakes, then the setting's lines. No more orders are played than the
// overlay's limits allow; the rest are counted in one line. Under reduced motion every step is
// a still frame.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import * as overlay from '../js/views/realism-overlay.js';
import { installDom, words } from './dom-fake.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));
// the room's call: the overlay, drawn again with the playback
const wakeOverlay = (args, more) => overlay.withPlayback(overlay.wakeOverlay(args), more);

// the fixture's awaiting fleet move, carried out: under way, with its own line in the record
const MOVE_ID = fixture.map.orders[0].order;
const moveLine = {
  id: 'mv0000000001', wake: 2, filed: '12 October 1941', settled: '14 October 1941',
  asked: 'Move a fleet: US Atlantic Fleet to Argentia', to: null, holder: null,
  status: 'carried out', moving: false, track: MOVE_ID, due: null, said: null,
};
const underWay = { ...fixture.map, orders: [{ ...fixture.map.orders[0], status: 'under_way' }] };
const record = [...fixture.record.orders.slice(0, 3), moveLine, ...fixture.record.orders.slice(3)];
const extra = { court: fixture.court, stakes: fixture.stakes };

const reel = (layer) => layer.querySelector('section.rl-ovl-play');
const steps = (layer) => reel(layer)?.querySelectorAll('li.rl-ovl-step') ?? [];
const kinds = (layer) => steps(layer).map((li) => li.getAttribute('data-kind'));

test('the room hands the overlay the court and the stakes it already holds', () => {
  const room = read('js/views/realism-room.js');
  assert.match(room, /const layer = withPlayback\(wakeOverlay\(\{ message, lines: overlayLines\(rv\.setting, rv\.wake\.wake\), map: rv\.map, orders: rv\.record\?\.orders \}\), \{ court: rv\.court, stakes: rv\.stakes \}\);/);
});

test('the playback redraws the same layer, which still holds the room; a layer it did not make is left alone', () => {
  installDom();
  const layer = overlay.wakeOverlay({ message: 'The day is running', lines: ['A line.'], map: underWay, orders: record });
  assert.equal(overlay.withPlayback(layer, extra), layer);
  assert.equal(layer.getAttribute('role'), 'alertdialog');
  assert.equal(layer.querySelectorAll('.rl-ovl-box').length, 1);
  assert.equal(words(layer.querySelector('h2')), 'The day is running');
  assert.equal(layer.querySelectorAll('figure.rl-ovl-map').length, 1);
  assert.ok(reel(layer));
  const other = installDom().createElement('div');
  assert.equal(overlay.withPlayback(other, extra), other);
  assert.equal(other.children.length, 0);
});

test('the seat\'s orders play in the order they were filed, then the stakes', () => {
  installDom();
  const layer = wakeOverlay({ message: 'm', lines: ['A line.'], map: underWay, orders: record }, extra);
  assert.deepEqual(kinds(layer), ['path', 'move', 'line', 'path', 'stakes']);
  assert.deepEqual(steps(layer).slice(0, 4).map((li) => words(li.querySelector('.rl-ovl-cap'))), [
    'Send a bill to Congress: Revise the Neutrality Act',
    'Move a fleet: US Atlantic Fleet to Argentia',
    'Escort the convoys to Iceland and shoot on sight',
    'Give a naval order: Escort the convoys, The Iceland route',
  ]);
  assert.deepEqual(steps(layer).map((li) => li.className.match(/rl-ovl-step-(\d+)/)[1]).map(Number), [1, 2, 3, 4, 5]);
  // settled orders that are not a move under way are not played
  for (const o of fixture.record.orders.filter((x) => !x.moving)) assert.ok(!words(reel(layer)).includes(o.asked), o.asked);
});

test('filed order comes from the filed day, not the record\'s order; one day keeps filing order', () => {
  const shuffled = [record[2], record[0], record[3], record[1]];
  assert.deepEqual(overlay.playback(shuffled, underWay, fixture.court).steps.map((s) => s.order.filed),
    ['10 October 1941', '12 October 1941', '17 October 1941', '18 October 1941']);
  // the record lists newest first, so two orders of one day play oldest first: the later in the list
  const a = { ...record[0], id: 'a', asked: 'First filed', filed: '18 October 1941' };
  const b = { ...record[0], id: 'b', asked: 'Second filed', filed: '18 October 1941' };
  assert.deepEqual(overlay.playback([b, a], null, fixture.court).steps.map((s) => s.order.asked), ['First filed', 'Second filed']);
});

test('an order on a path: a small copy of that path, its token on the holder\'s square', () => {
  installDom();
  const layer = wakeOverlay({ message: 'm', lines: [], map: null, orders: record }, extra);
  const bill = steps(layer)[0];
  const path = bill.querySelector('ol.rl-ovl-path');
  assert.equal(path.getAttribute('aria-label'), 'A bill through Congress');
  assert.deepEqual(path.querySelectorAll('li.rl-ovl-sq').map((sq) => words(sq.querySelector('.rl-ovl-who'))),
    ['Sam Rayburn', 'Alben W. Barkley', 'You']);
  // the clerk is a small mark between the squares, named for screen readers only
  const marks = path.querySelectorAll('li.rl-ovl-clerk');
  assert.equal(marks.length, 1);
  assert.equal(marks[0].getAttribute('aria-label'), 'House committee clerk');
  assert.equal(words(marks[0]), '');
  assert.deepEqual(path.children.map((li) => li.className.split(' ')[0]), ['rl-ovl-sq', 'rl-ovl-clerk', 'rl-ovl-sq', 'rl-ovl-sq']);
  const toks = path.querySelectorAll('.rl-ovl-tok');
  assert.equal(toks.length, 1);
  assert.equal(toks[0].closest('li.rl-ovl-sq'), path.querySelectorAll('li.rl-ovl-sq')[0], 'on Rayburn\'s square');
  assert.equal(words(toks[0]), 'day 9 of about 8');
  const convoy = steps(layer)[2].querySelector('ol.rl-ovl-path');
  assert.equal(convoy.getAttribute('aria-label'), 'A naval order');
  assert.equal(words(convoy.querySelector('.rl-ovl-tok')), 'day 2 of about 2');
  assert.equal(convoy.querySelector('.rl-ovl-tok').closest('li.rl-ovl-sq'), convoy.querySelectorAll('li.rl-ovl-sq')[0], 'on Stark\'s square');
  // further along: the token sits on Barkley's square, not the first one
  const bill0 = fixture.court.paths[0];
  const tok = bill0.steps[0].orders[0];
  const moved = { ...fixture.court, paths: [{ ...bill0, steps: bill0.steps.map((st, i) => ({ ...st, orders: i === 2 ? [{ ...tok, held_days: 3 }] : [] })) }] };
  const later = wakeOverlay({ message: 'm', lines: [], map: null, orders: record }, { court: moved });
  const sq = steps(later)[0].querySelectorAll('li.rl-ovl-sq');
  assert.deepEqual(sq.map((x) => x.querySelectorAll('.rl-ovl-tok').length), [0, 1, 0]);
  assert.equal(words(sq[1].querySelector('.rl-ovl-tok')), 'day 4 of about 20');
});

test('only the played order\'s path is drawn: no other path, and no one on no played path', () => {
  installDom();
  const layer = wakeOverlay({ message: 'm', lines: [], map: null, orders: record }, extra);
  const seen = words(reel(layer));
  for (const name of ['A cable to the Prime Minister', 'Winston Churchill', 'Harry L. Hopkins', 'Stephen T. Early']) {
    assert.ok(!seen.includes(name), name);
  }
  assert.equal(reel(layer).querySelectorAll('ol.rl-ovl-path').length, 2);
});

test('an order sent to a person and on no path: its line, to whom, and when the answer is due', () => {
  installDom();
  const layer = wakeOverlay({ message: 'm', lines: [], map: null, orders: record }, extra);
  const sent = steps(layer)[1];
  assert.equal(sent.getAttribute('data-kind'), 'line');
  assert.match(words(sent), /To Harold R\. Stark/);
  assert.match(words(sent), /Answer due 21 October 1941/);
  assert.equal(sent.querySelector('ol.rl-ovl-path'), null);
});

test('with no court data, an order on a path plays as its line', () => {
  installDom();
  const layer = wakeOverlay({ message: 'm', lines: [], map: null, orders: record }, { stakes: fixture.stakes });
  assert.deepEqual(kinds(layer), ['line', 'line', 'line', 'stakes']);
  assert.match(words(steps(layer)[0]), /With Sam Rayburn/);
});

test('a move plays on the map: its mark starts at its own step', () => {
  installDom();
  const layer = wakeOverlay({ message: 'm', lines: [], map: underWay, orders: record }, extra);
  const move = steps(layer)[1];
  assert.equal(move.getAttribute('data-kind'), 'move');
  assert.match(words(move), /On the map: US Atlantic Fleet, under way to Argentia/);
  const g = layer.querySelector('figure.rl-ovl-map').querySelectorAll('g.rl-mk-order');
  assert.equal(g.length, 1);
  assert.ok(g[0].classList.contains('rl-ovl-go'));
  assert.ok(g[0].classList.contains('rl-ovl-at-2'), g[0].className);
});

test('a move whose order the record does not name is drawn as today and not played', () => {
  installDom();
  const layer = wakeOverlay({ message: 'm', lines: [], map: underWay, orders: fixture.record.orders }, extra);
  assert.ok(!kinds(layer).includes('move'));
  const g = layer.querySelector('figure.rl-ovl-map g.rl-mk-order');
  assert.ok(g.classList.contains('rl-ovl-go-1'));
  assert.ok(!/rl-ovl-at-/.test(g.className));
});

const pathOrder = (i) => ({
  id: `p${i}`, wake: 3, filed: `${i + 1} October 1941`, settled: null, asked: `Path order ${i + 1}`,
  to: null, holder: 'Sam Rayburn', status: 'on its way', moving: true, track: `o-p${i}`, due: null, said: null,
});
const courtWith = (ids) => ({
  ...fixture.court,
  paths: [{ ...fixture.court.paths[0], steps: [{ ...fixture.court.paths[0].steps[0], orders: ids.map((id) => ({ id, label: 'Send a bill to Congress', since: '1941-10-12', held_days: 2 })) }] }],
});

test('no more orders than ORDER_LINES are played; the rest are counted in one line', () => {
  installDom();
  const n = overlay.ORDER_LINES + 3;
  const orders = Array.from({ length: n }, (_, i) => pathOrder(i)).reverse();
  const court = courtWith(orders.map((o) => o.track));
  const layer = wakeOverlay({ message: 'm', lines: [], map: null, orders }, { court });
  assert.equal(steps(layer).length, overlay.ORDER_LINES);
  assert.deepEqual(steps(layer).map((li) => words(li.querySelector('.rl-ovl-cap'))),
    Array.from({ length: overlay.ORDER_LINES }, (_, i) => `Path order ${i + 1}`));
  assert.deepEqual(reel(layer).querySelectorAll('.rl-ovl-more').map(words), ['and 3 more orders']);
  const one = wakeOverlay({ message: 'm', lines: [], map: null, orders: orders.slice(-overlay.ORDER_LINES - 1) }, { court });
  assert.deepEqual(reel(one).querySelectorAll('.rl-ovl-more').map(words), ['and 1 more order']);
  const all = wakeOverlay({ message: 'm', lines: [], map: null, orders: orders.slice(-overlay.ORDER_LINES) }, { court });
  assert.equal(reel(all).querySelector('.rl-ovl-more'), null);
});

test('no more moves than MAP_MOVES are played; a move past the cap is counted', () => {
  installDom();
  const cap = overlay.MAP_MOVES;
  const base = fixture.map.orders[0];
  const mapOrders = Array.from({ length: cap + 1 }, (_, i) => ({ ...base, order: `o-m${i}`, force: `Force ${i + 1}`, status: 'under_way' }));
  const lines = mapOrders.map((o, i) => ({ ...moveLine, id: `m${i}`, filed: `${i + 1} October 1941`, asked: `Move ${i + 1}`, track: o.order })).reverse();
  const layer = wakeOverlay({ message: 'm', lines: [], map: { ...fixture.map, orders: mapOrders }, orders: lines }, {});
  assert.equal(steps(layer).length, cap);
  assert.deepEqual(kinds(layer), Array(cap).fill('move'));
  assert.deepEqual(reel(layer).querySelectorAll('.rl-ovl-more').map(words), ['and 1 more order']);
  const g = layer.querySelector('figure.rl-ovl-map').querySelectorAll('g.rl-mk-order');
  assert.deepEqual(g.map((x) => (x.className.match(/rl-ovl-at-(\d+)/) ?? [null, null])[1]), ['1', '2', '3', '4', null]);
});

test('nothing to play and no stakes: no reel, the layer as before', () => {
  installDom();
  for (const [orders, more] of [[undefined, undefined], [[], {}], [fixture.record.orders.filter((o) => !o.moving), extra]]) {
    const layer = wakeOverlay({ message: 'm', lines: ['A line.'], map: null, orders }, more?.court ? { court: more.court } : more);
    assert.equal(reel(layer), null);
    assert.ok(!/rl-ovl-wait-/.test(layer.querySelector('ul.rl-ovl-lines').className));
  }
});

test('the stakes alone still play, before the lines', () => {
  installDom();
  const layer = wakeOverlay({ message: 'm', lines: ['A line.'], map: null, orders: [] }, { stakes: fixture.stakes });
  assert.deepEqual(kinds(layer), ['stakes']);
  assert.match(words(steps(layer)[0]), /Revising the Neutrality Act/);
  assert.match(words(steps(layer)[0]), /Keep the convoys moving to Iceland\./);
  assert.ok(layer.querySelector('ul.rl-ovl-lines').classList.contains('rl-ovl-wait-1'));
});

test('the last step stays on screen and the lines wait for every step', () => {
  installDom();
  const layer = wakeOverlay({ message: 'm', lines: ['A line.'], map: underWay, orders: record }, extra);
  assert.deepEqual(steps(layer).map((li) => li.classList.contains('rl-ovl-last')), [false, false, false, false, true]);
  assert.ok(layer.querySelector('ul.rl-ovl-lines').classList.contains('rl-ovl-wait-5'));
  // the reel comes before the lines in the box
  const box = layer.querySelector('.rl-ovl-box');
  const order = box.children.map((c) => c.className.split(' ')[0]);
  assert.ok(order.indexOf('rl-ovl-play') < order.indexOf('rl-ovl-lines'), order.join(','));
});

const css = () => read('css/p5-overlay.css');
const delays = (re) => [...css().matchAll(re)].map((m) => [Number(m[1]), Number(m[2])]);

test('one delay rule per step, STEP_SECONDS apart, for every order slot and the stakes', () => {
  const s = overlay.STEP_SECONDS;
  assert.ok(s > 0);
  const n = overlay.ORDER_LINES + 1;
  assert.deepEqual(delays(/\.rl-ovl-step-(\d+)\s*\{\s*animation-delay:\s*([\d.]+)s;\s*\}/g),
    Array.from({ length: n }, (_, i) => [i + 1, i * s]));
  assert.deepEqual(delays(/\.rl-ovl-lines\.rl-ovl-wait-(\d+)\s*\{\s*animation-delay:\s*([\d.]+)s;\s*\}/g),
    Array.from({ length: n }, (_, i) => [i + 1, (i + 1) * s]));
  assert.deepEqual(delays(/\.rl-ovl-go\.rl-ovl-at-(\d+) \.rl-mk-arrow,\s*\.rl-ovl-go\.rl-ovl-at-\1 \.rl-mk-goal\s*\{\s*animation-delay:\s*([\d.]+)s;\s*\}/g),
    Array.from({ length: overlay.ORDER_LINES }, (_, i) => [i + 1, i * s]));
  assert.match(css(), new RegExp(`\\.rl-ovl-step \\{[^}]*animation: rl-ovl-frame ${s}s linear both;`));
  assert.match(css(), /\.rl-ovl-step\.rl-ovl-last \{[^}]*animation-name: rl-ovl-stay;/);
  assert.match(css(), /\.rl-ovl-lines\[class\*="rl-ovl-wait-"\] \{[^}]*animation: rl-ovl-later/);
  // a wait rule must outrank the shorthand: it names both classes and comes after it
  const at = css().indexOf('.rl-ovl-lines[class*="rl-ovl-wait-"] {');
  assert.ok(at >= 0 && at < css().indexOf('.rl-ovl-lines.rl-ovl-wait-1 {'));
  // nothing in the box is squeezed when the playback makes it scroll
  assert.match(css(), /\.rl-ovl-box > \* \{ flex-shrink: 0; \}/);
});

test('under reduced motion each step is a still frame, all on screen, and the lines do not wait', () => {
  const still = css().match(/@media \(prefers-reduced-motion: reduce\) \{([\s\S]*?)\n\}/)[1];
  assert.match(still, /\.rl-ovl-step, \.rl-ovl-step\.rl-ovl-last \{\s*grid-area: auto;\s*animation: none;\s*visibility: visible;\s*opacity: 1;\s*\}/);
  assert.match(still, /\.rl-ovl-tok \{\s*animation: none;\s*\}/);
  assert.match(still, /\.rl-ovl-lines\[class\*="rl-ovl-wait-"\] \{\s*animation: none;\s*opacity: 1;\s*\}/);
});

test('the layer sits over every fixed bar and button of the room', async () => {
  const { readdirSync } = await import('node:fs');
  const z = (text) => [...text.matchAll(/z-index:\s*(\d+)/g)].map((m) => Number(m[1]));
  const own = Number(css().match(/\.rl-ovl \{[^}]*z-index:\s*(\d+)/)[1]);
  const others = readdirSync(join(WEB, 'css')).filter((f) => f.endsWith('.css') && f !== 'p5-overlay.css')
    .flatMap((f) => z(read(`css/${f}`)));
  assert.ok(others.length > 0);
  assert.ok(own > Math.max(...others), `${own} over ${Math.max(...others)}`);
});
