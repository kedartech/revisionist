// Spec for Train 2 unit V (contract K2), revised for unit Q2 (contract KQ): at most eight
// lines a wake, the window moving on each wake. The unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import * as overlay from '../js/views/realism-overlay.js';
import { QUIET_LINES, overlayLines, wakeOverlay } from '../js/views/realism-overlay.js';
import { installDom, words } from './dom-fake.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

test('the setting gives the lines: facts, then dated events', () => {
  assert.deepEqual(overlayLines(fixture.setting), [
    ...fixture.setting.facts,
    '17 October 1941: USS Kearny is torpedoed off Iceland.',
    '31 October 1941: USS Reuben James is sunk.',
  ]);
});

test('with no setting text, three fixed period-neutral lines', () => {
  assert.equal(QUIET_LINES.length, 3);
  assert.ok(QUIET_LINES.every((l) => typeof l === 'string' && l.length > 10 && !/\d{4}/.test(l)));
  assert.deepEqual(overlayLines({ situation: null, sides: [], crawl: [], facts: [], dates: [] }), [...QUIET_LINES]);
  assert.deepEqual(overlayLines(null), [...QUIET_LINES]);
});

test('the layer holds the room, and moves by CSS only', () => {
  const src = read('js/views/realism-overlay.js');
  assert.match(src, /'alertdialog'/);
  assert.match(src, /'aria-busy'/);
  assert.doesNotMatch(src, /setInterval|setTimeout|requestAnimationFrame/);
  const css = read('css/p5-overlay.css');
  assert.match(css, /@keyframes/);
  assert.match(css, /prefers-reduced-motion/);
});

const many = (n) => ({ facts: Array.from({ length: n }, (_, i) => `Line ${i + 1}.`), dates: [] });
const nums = (lines) => lines.map((l) => Number(l.match(/\d+/)[0]));

test('eight slots; eight lines or fewer come out as they are on every wake', () => {
  assert.equal(overlay.OVERLAY_SLOTS, 8);
  const five = overlayLines(fixture.setting);
  for (const turn of [0, 1, 2, 7]) assert.deepEqual(overlayLines(fixture.setting, turn), five);
  assert.deepEqual(overlayLines(many(8), 3), many(8).facts);
});

test('more than eight: eight in a row from (turn * 8) % n, wrapping', () => {
  const s = many(18);
  assert.deepEqual(nums(overlayLines(s)), [1, 2, 3, 4, 5, 6, 7, 8]);
  assert.deepEqual(nums(overlayLines(s, 0)), [1, 2, 3, 4, 5, 6, 7, 8]);
  assert.deepEqual(nums(overlayLines(s, 1)), [9, 10, 11, 12, 13, 14, 15, 16]);
  assert.deepEqual(nums(overlayLines(s, 2)), [17, 18, 1, 2, 3, 4, 5, 6]);
  assert.deepEqual(nums(overlayLines(s, 3)), [7, 8, 9, 10, 11, 12, 13, 14]);
  assert.deepEqual(nums(overlayLines(many(9), 1)), [9, 1, 2, 3, 4, 5, 6, 7]);
});

test('every line is shown within ceil(n / 8) wakes', () => {
  for (const n of [9, 16, 17, 18, 25, 40]) {
    const seen = new Set();
    for (let turn = 0; turn < Math.ceil(n / 8); turn += 1) for (const l of overlayLines(many(n), turn)) seen.add(l);
    assert.equal(seen.size, n, `n=${n}`);
  }
});

test('the layer never draws more than eight lines', () => {
  installDom();
  const lines = many(18).facts;
  const layer = wakeOverlay({ message: 'The day is running', lines });
  assert.equal(layer.querySelectorAll('li').length, 8);
  assert.deepEqual(layer.querySelectorAll('li').map((li) => li.textContent), lines.slice(0, 8));
  assert.equal(wakeOverlay({ message: 'm', lines: lines.slice(0, 3) }).querySelectorAll('li').length, 3);
});

test('one delay rule per slot, a cycle of eight times three seconds, no style attribute', () => {
  const css = read('css/p5-overlay.css');
  const slots = [...css.matchAll(/\.rl-ovl-line:nth-child\((\d+)\)\s*\{\s*animation-delay:\s*([\d.]+)s;\s*\}/g)];
  assert.deepEqual(slots.map((m) => Number(m[1])), [1, 2, 3, 4, 5, 6, 7, 8]);
  assert.deepEqual(slots.map((m) => Number(m[2])), [0, 3, 6, 9, 12, 15, 18, 21]);
  assert.match(css, /animation: rl-ovl-show 24s linear infinite both;/);
  const src = read('js/views/realism-overlay.js');
  assert.doesNotMatch(src, /style=|\.style\.|'style'/);
});

// W1: while the wake runs the overlay also shows what is already known: your orders on
// their way (one line each, to whom) and your own forces under way on a compact map.
// Own marks and under-way orders only; nothing another side's papers report.

const ORDER = (over) => ({
  order: 'o-x', force: 'Task Force 1', mark: null, to: { name: 'Halifax', lat: 44.6, lon: -63.6 },
  status: 'under_way', with_person: null, filed: '1941-10-15', ...over,
});
const withOrders = (orders) => ({ ...fixture.map, orders });
const ovlMap = (layer) => layer.querySelector('figure.rl-ovl-map');
const settle = () => new Promise((r) => setImmediate(r));

test('the room hands the overlay its map and its record while the wake runs', () => {
  const room = read('js/views/realism-room.js');
  assert.match(room, /wakeOverlay\(\{ message, lines: overlayLines\(rv\.setting, rv\.wake\.wake\), map: rv\.map, orders: rv\.record\?\.orders \}\)/);
});

test('the overlay map draws your own marks only, never what another side is reported doing', () => {
  installDom();
  assert.ok(fixture.map.marks.some((m) => m.side === 'other'), 'the fixture holds other sides\' marks');
  const layer = wakeOverlay({ message: 'm', lines: [], map: fixture.map, orders: [] });
  const fig = ovlMap(layer);
  assert.ok(fig, 'a map is drawn');
  const marks = fig.querySelectorAll('g.rl-mk');
  assert.deepEqual(marks.map((g) => g.classList.contains('rl-side-own')), [true]);
  assert.match(words(fig), /US Atlantic Fleet/);
  for (const m of fixture.map.marks.filter((x) => x.side !== 'own')) assert.ok(!words(layer).includes(m.name), m.name);
});

test('the overlay map draws your orders under way only, and nothing in it takes focus', () => {
  installDom();
  const awaiting = fixture.map.orders[0];
  assert.equal(awaiting.status, 'awaiting');
  const layer = wakeOverlay({ message: 'm', lines: [], map: withOrders([awaiting, ORDER({})]), orders: [] });
  const drawn = ovlMap(layer).querySelectorAll('g.rl-mk-order');
  assert.deepEqual(drawn.map((g) => g.classList.contains('rl-o-under_way')), [true]);
  assert.match(words(layer), /Under way: Task Force 1/);
  assert.doesNotMatch(words(layer), /Ordered: /);
  assert.equal(layer.querySelectorAll('[tabindex]').length, 0);
  assert.equal(layer.querySelectorAll('[role="button"]').length, 0);
});

test('your orders on their way: one line each, to whom, moving orders only', () => {
  installDom();
  const want = [
    'Give a naval order: Escort the convoys, The Iceland route · with Franklin D. Roosevelt',
    'Escort the convoys to Iceland and shoot on sight · to Harold R. Stark',
    'Send a bill to Congress: Revise the Neutrality Act · with Sam Rayburn',
  ];
  assert.deepEqual(overlay.leavingLines(fixture.record.orders), want);
  const layer = wakeOverlay({ message: 'm', lines: [], map: null, orders: fixture.record.orders });
  assert.deepEqual(layer.querySelectorAll('ul.rl-ovl-orders li').map(words), want);
  assert.equal(overlay.leavingLines([{ asked: 'On my own', to: null, holder: null, moving: true }])[0], 'On my own');
});

test('at most ORDER_LINES order lines, then how many more', () => {
  installDom();
  const n = overlay.ORDER_LINES + 3;
  const many = Array.from({ length: n }, (_, i) => ({ asked: `Order ${i + 1}`, to: 'Stark', holder: 'Stark', moving: true }));
  const lines = overlay.leavingLines(many);
  assert.equal(lines.length, overlay.ORDER_LINES + 1);
  assert.equal(lines.at(-1), 'and 3 more');
});

test('the animated marks are capped by MAP_MOVES, with one delay rule per move in the stylesheet', () => {
  installDom();
  const cap = overlay.MAP_MOVES;
  assert.ok(Number.isInteger(cap) && cap > 0);
  const orders = Array.from({ length: cap + 3 }, (_, i) => ORDER({ order: `o-${i}`, force: `Force ${i + 1}` }));
  const fig = ovlMap(wakeOverlay({ message: 'm', lines: [], map: withOrders(orders), orders: [] }));
  assert.equal(fig.querySelectorAll('g.rl-mk-order').length, cap + 3);
  const going = fig.querySelectorAll('g.rl-ovl-go');
  assert.equal(going.length, cap);
  assert.deepEqual(going.map((g) => g.className.match(/rl-ovl-go-(\d+)/)[1]).map(Number),
    Array.from({ length: cap }, (_, i) => i + 1));
  const css = read('css/p5-overlay.css');
  const slots = [...css.matchAll(/\.rl-ovl-go-(\d+) \.rl-mk-arrow,\s*\.rl-ovl-go-\1 \.rl-mk-goal\s*\{\s*animation-delay:/g)];
  assert.deepEqual(slots.map((m) => Number(m[1])), Array.from({ length: cap }, (_, i) => i + 1));
  // only a capped mark moves: every map animation in the sheet is under .rl-ovl-go
  for (const [, sel] of css.matchAll(/([^{}]*)\{[^}]*\banimation(?:-name)?\s*:\s*(?!none)[^;]*;/g)) {
    if (/rl-mk|rl-map/.test(sel)) assert.match(sel, /\.rl-ovl-go\b/, sel.trim());
  }
});

test('under reduced motion the map stands still', () => {
  const css = read('css/p5-overlay.css');
  const still = css.match(/@media \(prefers-reduced-motion: reduce\) \{([\s\S]*?)\n\}/)[1];
  assert.match(still, /\.rl-ovl-go \.rl-mk-arrow,\s*\.rl-ovl-go \.rl-mk-goal\s*\{\s*animation:\s*none;\s*\}/);
});

test('no map in the payload, or nothing of your own on it: no map, the lines as before', () => {
  installDom();
  for (const map of [undefined, null, { places: [], marks: [], orders: [] },
    { ...fixture.map, marks: fixture.map.marks.filter((m) => m.side !== 'own'), orders: fixture.map.orders }]) {
    const layer = wakeOverlay({ message: 'm', lines: ['A line.'], map });
    assert.equal(ovlMap(layer), null);
    assert.equal(layer.querySelector('ul.rl-ovl-orders'), null);
    assert.deepEqual(layer.querySelectorAll('li.rl-ovl-line').map(words), ['A line.']);
  }
});

test('coastlines come from the land file, fetched once; without it the map still draws', async () => {
  const doc = installDom();
  await settle();
  const was = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async (url) => {
    calls += 1;
    assert.equal(url, '/assets/land-110m.json');
    return { ok: true, json: async () => ({ rings: [[[-60, 40], [-50, 40], [-50, 50], [-60, 50]]] }) };
  };
  try {
    const layer = wakeOverlay({ message: 'm', lines: [], map: fixture.map, orders: [] });
    doc.body.append(layer);
    assert.ok(ovlMap(layer).querySelector('svg'), 'drawn before the land arrives');
    await settle();
    assert.ok(ovlMap(layer).querySelector('path.rl-map-land'), 'land drawn once it arrives');
    const again = wakeOverlay({ message: 'm', lines: [], map: fixture.map, orders: [] });
    assert.ok(ovlMap(again).querySelector('path.rl-map-land'), 'land kept for the next run');
    assert.equal(calls, 1);
  } finally {
    globalThis.fetch = was;
  }
});
