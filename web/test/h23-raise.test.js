// Raising a piece on screen (RNB), one test or more per rule: 1. a place that can raise shows
// "Raise a piece here" in its sheet, and the war economy sheet lists every such place; 2. it opens
// the kinds as tiles: the picture, the five figures, the cost as two bars against the pools, and
// the day it would arrive; 3. choosing one runs the check and shows the pools as they would stand,
// then a confirm chip, as a move on the map has; 4. a refusal shows the check's reason on the tile;
// 5. pieces being raised are a list in the war economy sheet, each with its place and day, and
// open that place on the map.
// Keeps: the client decides nothing (the kinds, costs, days and the check's words are the server's);
// nothing is filed without the confirm.
// Mutants: a tile for a kind the reply did not list; the confirm filed without the check.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { theatreBoard, forgetShapes } = await import('../js/views/realism-theatre.js');
const { forgetMarks } = await import('../js/views/realism-territory.js');
const { ownSheet } = await import('../js/views/realism-economy.js');
const { nationsPanel } = await import('../js/views/realism-nations.js');
const raise = await import('../js/views/realism-raise.js');

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const fixture = JSON.parse(read('./fixtures/realism-seat.json'));
const SHAPES = JSON.parse(read('./fixtures/toy.map.json'));
const TMAP = fixture.territory_map;
const KITE_FIGURES = { attack: 4, defence: 2, speed: 5, reach: 2, hidden: 1 };

/** The seat's view with the economy block the server sends with `raising` on; the Fire Kites with figures unless `bare`. */
function seat({ bare = false } = {}) {
  const economy = structuredClone(fixture.raising_economy);
  if (!bare) economy.own.places[0].kinds[0].figures = { ...KITE_FIGURES };
  return {
    ...structuredClone(fixture),
    map: structuredClone(TMAP),
    economy,
    clock: { ...fixture.clock, world_date: economy.day },
  };
}

const settle = async () => { for (let i = 0; i < 4; i += 1) await new Promise((ok) => setTimeout(ok, 0)); };
const label = (el) => el.getAttribute('aria-label');

/** Every call the client makes to the server; `answer(action, body)` gives each reply (a promise or a value). */
function server(answer = () => ({})) {
  const calls = [];
  api.realism = (action, body = {}) => {
    calls.push([action, structuredClone(body)]);
    if (action === 'map') return Promise.resolve({ reply: '', refused: false, file: TMAP.file, map: SHAPES });
    return Promise.resolve(answer(action, body));
  };
  return calls;
}

/** A reply that waits for `release(value)`. */
function held() {
  let release;
  const promise = new Promise((ok) => { release = ok; });
  return { promise, release: (v) => release(v) };
}

/** The theatre on the toy map, redrawn on each pick as the room does; `acts` collects what is filed. */
async function theatre(rv, theatreState = {}) {
  const ui = { piece: null, theatre: { mode: 'map', scope: 'reports', ...theatreState } };
  const acts = [];
  const was = globalThis.fetch;
  globalThis.fetch = async (url) => ({ ok: true, status: 200, json: async () => (url === '/api/realism/map' ? { reply: '', refused: false, file: TMAP.file, map: SHAPES } : {}) });
  const box = { view: null, ui, acts };
  const draw = () => {
    box.view?.remove();
    box.view = theatreBoard(rv, ui, {
      pick: (p) => { if (p.theatre) ui.theatre = p.theatre; draw(); },
      act: (message, action, body, then) => { acts.push([message, action, structuredClone(body)]); then?.({ refused: false }); },
    });
    document.body.append(box.view);
  };
  box.draw = draw;
  try {
    forgetShapes();
    forgetMarks();
    draw();
    await settle();
  } finally { globalThis.fetch = was; }
  draw();
  return box;
}

const sheetOf = (box) => box.view.querySelector('.rl-rs-sheet');
const tiles = (el) => el.querySelectorAll('.rl-rs-tile');

// --- rule 1: "Raise a piece here" in a place's sheet, and every such place in the war economy ---------

test('a place that can raise shows "Raise a piece here" in its area\'s sheet, and it opens the kinds', async () => {
  server();
  const box = await theatre(seat(), { area: 'norra_hills' });
  const sheet = box.view.querySelector('.rl-area-sheet');
  assert.ok(sheet, 'the area\'s sheet is open');
  const [open] = buttons(sheet, raise.RAISE_HERE);
  assert.ok(open, 'the place\'s sheet offers it');
  assert.equal(label(open), 'Raise a piece here: The Hillfort');
  open.click();
  assert.equal(box.ui.theatre.raisePlace.place, 'hillfort');
  assert.equal(box.ui.theatre.area, null, 'the area\'s sheet gives the map to the tiles');
  assert.match(words(sheetOf(box).querySelector('h3')), /^Raise a piece at The Hillfort$/);
});

test('an area with no place of the seat\'s that can raise offers nothing to raise', async () => {
  server();
  const box = await theatre(seat(), { area: 'sudland_coast' });
  assert.ok(box.view.querySelector('.rl-area-sheet'));
  assert.equal(buttons(box.view, raise.RAISE_HERE).length, 0);
});

test('the war economy sheet lists every place that can raise, each opening its kinds', () => {
  const rv = seat();
  const opened = [];
  const sheet = ownSheet(rv.economy, rv.map, { onRaise: (p) => opened.push(p.place), onMap: () => {} });
  const rows = sheet.querySelectorAll('.rl-rs-places li');
  assert.deepEqual(rows.map((r) => r.getAttribute('data-place')), ['hillfort', 'norrhavn']);
  assert.equal(words(rows[0].querySelector('.rl-rs-entry-name')), 'The Hillfort');
  assert.equal(words(rows[0].querySelector('.rl-rs-kinds')), 'Fire Kites');
  for (const b of buttons(sheet, raise.RAISE_HERE)) b.click();
  assert.deepEqual(opened, ['hillfort', 'norrhavn']);
});

test('the Nations card\'s war economy hands the room its ways to raise and to the map', () => {
  const rv = seat();
  rv.economy.figures = structuredClone(fixture.raising_economy.figures);
  const got = [];
  const panel = nationsPanel(rv, {
    state: { open: rv.economy.own.nation.key, eco: true }, onRaise: (p) => got.push(['raise', p.place]), onMap: (a) => got.push(['map', a]),
  });
  buttons(panel, raise.RAISE_HERE)[0].click();
  buttons(panel, 'Show on map')[0].click();
  assert.deepEqual(got, [['raise', 'hillfort'], ['map', 'norra_plain']]);
});

test('with raising off the war economy sheet is as today: no place, no raising', () => {
  const rv = seat();
  delete rv.economy.own.places;
  delete rv.economy.own.raising;
  const sheet = ownSheet(rv.economy, rv.map, { onRaise: () => {}, onMap: () => {} });
  assert.ok(!sheet.querySelector('.rl-rs-places'));
  assert.ok(!sheet.querySelector('.rl-rs-raising'));
  assert.doesNotMatch(words(sheet), /raise/i);
});

// --- rule 2: the kinds as tiles ----------------------------------------------------------------

test('the tiles are the kinds the reply lists for the place, and no other', async () => {
  server();
  const rv = seat();
  rv.economy.own.places[0].kinds.push({ ...structuredClone(rv.economy.own.places[1].kinds[0]), refusal: '' });
  const box = await theatre(rv, { raisePlace: { place: 'hillfort' } });
  assert.deepEqual(tiles(sheetOf(box)).map((t) => t.getAttribute('data-kind')), ['fire_kite', 'levy']);
  const other = await theatre(seat(), { raisePlace: { place: 'norrhavn' } });
  assert.deepEqual(tiles(sheetOf(other)).map((t) => t.getAttribute('data-kind')), ['levy']);
});

test('a place the reply does not list draws no sheet', async () => {
  server();
  const box = await theatre(seat(), { raisePlace: { place: 'sudhaven' } });
  assert.ok(!sheetOf(box));
});

test('a tile has the kind\'s picture and name, its five figures as meters, the cost as two bars and the day', async () => {
  server();
  const box = await theatre(seat(), { raisePlace: { place: 'hillfort' } });
  const [kite] = tiles(sheetOf(box));
  assert.equal(kite.querySelector('[data-picture]')?.getAttribute('data-picture'), 'bombers');
  assert.equal(words(kite.querySelector('.rl-rs-kind')), 'Fire Kites');
  const meters = kite.querySelectorAll('.rl-mark-meter');
  assert.deepEqual(meters.map(label), [
    'Fire Kites: attack: 4 of 5', 'Fire Kites: defence: 2 of 5', 'Fire Kites: speed: 5 of 5', 'Fire Kites: reach: 2 of 5', 'Fire Kites: hidden: 1 of 5',
  ]);
  const bars = kite.querySelectorAll('.rl-rs-costs .rl-mark-bar');
  assert.deepEqual(bars.map(label), ['Grain, Iron: costs 10 of 50 in the pool', 'Levies: costs 1 of 5 in the pool']);
  assert.deepEqual(bars.map((b) => b.querySelector('.rl-mark-fill').getAttribute('data-share')), ['20', '20']);
  assert.equal(words(kite.querySelector('.rl-rs-day')), '30 days to raise · arrives 3 May');
  assert.doesNotMatch(words(sheetOf(box)), /null/, 'an empty slot draws nothing');
});

test('a kind the server sent no figures for has no meters: none is worked out', async () => {
  server();
  const box = await theatre(seat({ bare: true }), { raisePlace: { place: 'hillfort' } });
  const [kite] = tiles(sheetOf(box));
  assert.equal(kite.querySelectorAll('.rl-mark-meter').length, 0);
  assert.equal(kite.querySelectorAll('.rl-rs-costs .rl-mark-bar').length, 2, 'the cost is still drawn');
});

test('a cost larger than its pool is drawn full and hostile, and says so', async () => {
  server();
  const rv = seat();
  rv.economy.own.pools.manpower = 0;
  const box = await theatre(rv, { raisePlace: { place: 'hillfort' } });
  const [, men] = tiles(sheetOf(box))[0].querySelectorAll('.rl-rs-costs .rl-mark-bar');
  assert.ok(men.classList.contains('rl-mark-hostile'));
  assert.equal(men.querySelector('.rl-mark-fill').getAttribute('data-share'), '100', 'an empty pool still shows the cost');
  assert.equal(label(men), 'Levies: costs 1 of 0 in the pool');
});

// --- rule 3: the check, the pools as they would stand, then the confirm ---------------------------------

test('choosing a kind runs the check; while it is out nothing can be sent', async () => {
  const wait = held();
  const calls = server((action) => (action === 'check' ? wait.promise : {}));
  const box = await theatre(seat(), { raisePlace: { place: 'hillfort' } });
  calls.length = 0;
  tiles(sheetOf(box))[0].click();
  await settle();
  assert.deepEqual(calls, [['check', { lever: 'raise_piece', params: { kind: 'fire_kite', place: 'hillfort' } }]]);
  const sheet = sheetOf(box);
  assert.equal(tiles(sheet)[0].getAttribute('aria-pressed'), 'true');
  assert.match(words(sheet.querySelector('.rl-rs-checking')), /^Checking Fire Kites at The Hillfort/);
  assert.equal(buttons(sheet, 'Raise it').length, 0, 'no confirm before the check is in');
  wait.release({ reply: '', refused: false, check: 'allowed', who: null, reason: '' });
  await settle();
  assert.equal(buttons(sheetOf(box), 'Raise it').length, 1);
  assert.deepEqual(box.acts, [], 'the check files nothing');
});

test('an allowed check shows the pools as they would stand, then the confirm that files the order', async () => {
  server((action) => (action === 'check' ? { reply: '', refused: false, check: 'allowed', who: null, reason: '' } : {}));
  const box = await theatre(seat(), { raisePlace: { place: 'hillfort' } });
  tiles(sheetOf(box))[0].click();
  await settle();
  const chip = sheetOf(box).querySelector('.rl-rs-confirm');
  assert.ok(chip.classList.contains('rl-pup-chip'), 'a confirm chip, as a move on the map has');
  assert.match(words(chip.querySelector('.rl-rs-ask')), /^Raise Fire Kites at The Hillfort\? It arrives on 3 May\. Nothing is filed until you send it\.$/);
  const after = chip.querySelectorAll('.rl-rs-after .rl-mark-bar');
  assert.deepEqual(after.map(label), ['Grain, Iron: 50 now, 30 after', 'Levies: 5 now, 3 after']);
  assert.deepEqual(after.map((b) => b.querySelector('.rl-mark-fill').getAttribute('data-share')), ['60', '60']);
  assert.deepEqual(box.acts, []);
  buttons(chip, 'Raise it')[0].click();
  assert.deepEqual(box.acts, [['Sending it…', 'lever', { lever: 'raise_piece', params: { kind: 'fire_kite', place: 'hillfort' } }]]);
  assert.equal(box.ui.theatre.raisePlace, null, 'the sheet closes once it is sent');
});

test('Back leaves the tiles with nothing chosen and nothing filed', async () => {
  server((action) => (action === 'check' ? { reply: '', refused: false, check: 'allowed', who: null, reason: '' } : {}));
  const box = await theatre(seat(), { raisePlace: { place: 'hillfort' } });
  tiles(sheetOf(box))[0].click();
  await settle();
  buttons(sheetOf(box), 'Back')[0].click();
  assert.ok(!sheetOf(box).querySelector('.rl-rs-confirm'));
  assert.equal(tiles(sheetOf(box))[0].getAttribute('aria-pressed'), 'false');
  assert.deepEqual(box.acts, []);
});

test('a check that fails offers to check again and nothing to send', async () => {
  let n = 0;
  server((action) => {
    if (action !== 'check') return {};
    n += 1;
    return n === 1 ? Promise.reject(new Error('down')) : { reply: '', refused: false, check: 'allowed', who: null, reason: '' };
  });
  const box = await theatre(seat(), { raisePlace: { place: 'hillfort' } });
  tiles(sheetOf(box))[0].click();
  await settle();
  assert.equal(buttons(sheetOf(box), 'Raise it').length, 0);
  buttons(sheetOf(box), 'Check again')[0].click();
  await settle();
  assert.equal(n, 2);
  assert.equal(buttons(sheetOf(box), 'Raise it').length, 1);
});

test('a check that a lock holds offers the lock\'s choices in place of Raise it', async () => {
  server((action) => (action === 'check' ? { reply: '', refused: false, check: 'locked', who: 'Tomas', reason: 'Tomas must allow it.' } : {}));
  const box = await theatre(seat(), { raisePlace: { place: 'hillfort' } });
  tiles(sheetOf(box))[0].click();
  await settle();
  const chip = sheetOf(box).querySelector('.rl-rs-confirm');
  assert.equal(buttons(chip, 'Raise it').length, 0);
  assert.equal(chip.querySelectorAll('.rl-rs-after .rl-mark-bar').length, 2, 'the pools as they would stand');
  buttons(chip, 'Ask Tomas')[0].click();
  assert.deepEqual(box.acts, [['Asking…', 'lever-ask', { lever: 'raise_piece', params: { kind: 'fire_kite', place: 'hillfort' } }]]);
});

test('the chosen kind and its answer are kept when the room redraws', async () => {
  const calls = server((action) => (action === 'check' ? { reply: '', refused: false, check: 'allowed', who: null, reason: '' } : {}));
  const box = await theatre(seat(), { raisePlace: { place: 'hillfort' } });
  tiles(sheetOf(box))[0].click();
  await settle();
  const asked = calls.filter(([a]) => a === 'check').length;
  box.draw();
  assert.equal(buttons(sheetOf(box), 'Raise it').length, 1);
  tiles(sheetOf(box))[0].click();
  await settle();
  assert.equal(buttons(sheetOf(box), 'Raise it').length, 1);
  assert.equal(calls.filter(([a]) => a === 'check').length, asked, 'no second check for the same day');
});

// --- rule 4: a refusal shows the check's reason on the tile ---------------------------------------

test('a refusal from the check is shown on the tile, and no confirm is offered', async () => {
  server((action) => (action === 'check' ? { reply: '', refused: false, check: 'beyond', who: null, reason: 'The place is out of supply' } : {}));
  const box = await theatre(seat(), { raisePlace: { place: 'hillfort' } });
  tiles(sheetOf(box))[0].click();
  await settle();
  const sheet = sheetOf(box);
  const [kite] = tiles(sheet);
  assert.ok(kite.classList.contains('rl-rs-refused'));
  assert.equal(words(kite.querySelector('.rl-rs-why')), 'The place is out of supply');
  assert.ok(!sheet.querySelector('.rl-rs-confirm'));
  assert.equal(buttons(sheet, 'Raise it').length, 0);
});

test('a kind the reply already refuses shows the check\'s words on its tile before it is chosen', async () => {
  server();
  const box = await theatre(seat(), { raisePlace: { place: 'norrhavn' } });
  const [levy] = tiles(sheetOf(box));
  assert.equal(words(levy.querySelector('.rl-rs-why')), 'A piece is already being raised there');
});

// --- rule 5: the pieces being raised, each opening its place on the map ----------------------------

test('the war economy sheet lists each piece being raised with its place and day, and opens it on the map', () => {
  const rv = seat();
  rv.economy.own.raising.push({ ...rv.economy.own.raising[0], kind: 'fire_kite', name: 'Fire Kites', place: 'hillfort', place_name: 'The Hillfort', area: 'norra_hills', day: '1900-05-03', fixed: false, picture: 'bombers' });
  const shown = [];
  const sheet = ownSheet(rv.economy, rv.map, { onRaise: () => {}, onMap: (area) => shown.push(area) });
  const rows = sheet.querySelectorAll('.rl-rs-raising li');
  assert.deepEqual(rows.map((r) => words(r.querySelector('.rl-rs-line'))), [
    'Levy at Norrhavn, arrives 22 Apr',
    'Fire Kites at The Hillfort, arrives 3 May if each step is taken on its day',
  ]);
  assert.equal(rows[1].querySelector('[data-picture]')?.getAttribute('data-picture'), 'bombers');
  const maps = buttons(sheet, 'Show on map');
  assert.deepEqual(maps.map(label), ['Show Norrhavn on the map', 'Show The Hillfort on the map']);
  for (const b of maps) b.click();
  assert.deepEqual(shown, ['norra_plain', 'norra_hills']);
});

test('with no piece being raised the list says so', () => {
  const rv = seat();
  rv.economy.own.raising = [];
  const sheet = ownSheet(rv.economy, rv.map, {});
  assert.equal(words(sheet.querySelectorAll('.rl-rs-none').at(-1)), 'No piece is being raised.');
});

// --- the stylesheet: tokens only, a target of 44 px -------------------------------------------------

test('the raising parts take their colours from the tokens and give each control 44 px', () => {
  const css = read('../css/c-pieces.css');
  const part = css.slice(css.indexOf('/* Raising a piece (RNB)'));
  assert.ok(part.length > 100);
  assert.doesNotMatch(part, /#[0-9a-f]{3,8}\b|rgb\(|hsl\(/i);
  assert.match(part, /\.rl-rs-open, \.rl-rs-map, \.rl-rs-close \{ min-height: 44px; \}/);
  assert.match(part, /\.rl-rs-tile\[aria-pressed="true"\] \{ border: 2px solid var\(--fg-strong\)/);
});
