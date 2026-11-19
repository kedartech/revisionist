// Holders and the front line (FRL): on the territory map each land area is tinted by its
// holder's standing to the seat with a pattern as well, and the holder's name is in its text
// twin; a border between two holders at war is drawn heavy and every other border plain; an
// area that changed hands carries a dated mark and a capital marked to fall carries that
// line; a tap on an area opens its sheet: holder, since when, printed yields.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { fire, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { territoryDrawing, territoryView } = await import('../js/views/realism-territory.js');
const rules = await import('../js/realism-rules.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const CSS_TEXT = readFileSync(new URL('../css/c-map.css', import.meta.url), 'utf8');
const DESK = { width: 960, height: 740 };
const PHONE = { width: 366, height: 422 };

const NORRA = { key: 'N', name: 'Norra', relation: 'own' };
const SUDLAND = { key: 'S', name: 'Sudland', relation: 'enemy' };
const FRANCE = { key: 'F', name: 'Valmy', relation: 'ally' };
const NEUTRAL = { key: 'T', name: 'Tarn', relation: 'neutral' };

/** The toy board with holders given by area key: `{ norra_hills: NORRA, ... }`, and any other area keys on each. */
function held(by, more = {}) {
  const map = structuredClone(fixture.territory_map);
  map.areas = map.areas.map((a) => ({
    ...a, holder: null, held_since: null, taken_from: null, falling: null, ...(by[a.key] ? { holder: by[a.key] } : {}), ...(more[a.key] ?? {}),
  }));
  return map;
}

// the front: Norra holds the hills and the plain's neighbour is an ally; Sudland holds the coast
const FRONT = { norra_hills: NORRA, norra_plain: FRANCE, sudland_coast: SUDLAND, isle: NEUTRAL };
const draw = (map, opts = {}) => territoryDrawing(map, SHAPES, { px: DESK, ...opts });
const border = (pic, pair) => pic.querySelectorAll('path.rl-border').find((b) => b.getAttribute('data-between') === pair);
const area = (pic, key) => pic.querySelectorAll('path.rl-area').find((a) => a.getAttribute('data-area') === key);
const tint = (pic, key) => pic.querySelectorAll('path.rl-hold').find((a) => a.getAttribute('data-area') === key);

// --- Rule 1: tinted by the holder's standing, with a pattern, and the name in the text twin ----

test('a holder is told in words: its name and how it stands to the seat', () => {
  assert.equal(rules.holderWords({ holder: NORRA }), 'Norra (yours)');
  assert.equal(rules.holderWords({ holder: SUDLAND }), 'Sudland (enemy)');
  assert.equal(rules.holderWords({ holder: FRANCE }), 'Valmy (ally)');
  assert.equal(rules.holderWords({ holder: NEUTRAL }), 'Tarn (neutral)');
  assert.equal(rules.holderWords({ holder: null }), 'No holder');
});

test('each held land area is tinted by its holder\'s standing, and each standing has a pattern of its own', () => {
  const pic = draw(held(FRONT));
  const want = { norra_hills: 'own', norra_plain: 'ally', sudland_coast: 'enemy', isle: 'neutral' };
  const patterns = new Map();
  for (const [key, relation] of Object.entries(want)) {
    const el = tint(pic, key);
    assert.ok(el, `${key} is tinted`);
    assert.ok(el.classList.contains(`rl-hold-${relation}`), `${key} tinted as ${relation}`);
    const fill = el.getAttribute('fill');
    const id = fill.match(/^url\(#(.+)\)$/)?.[1];
    assert.ok(id, `${key} is filled with a pattern, not a flat colour`);
    const pat = pic.querySelectorAll('pattern').find((p) => p.getAttribute('id') === id);
    assert.ok(pat, `${key}'s pattern is defined`);
    patterns.set(relation, pat.getAttribute('data-pattern'));
  }
  assert.equal(new Set(patterns.values()).size, 4, 'four standings, four different patterns');
  for (const v of patterns.values()) assert.ok(v);
});

test('an area nobody holds, and a sea zone, are not tinted', () => {
  const pic = draw(held({ norra_hills: NORRA }));
  assert.equal(pic.querySelectorAll('path.rl-hold').length, 1);
  assert.equal(tint(pic, 'the_gulf'), undefined);
  assert.equal(tint(pic, 'isle'), undefined);
});

test('a tinted area says its holder in its name for a screen reader, and in its list row', () => {
  const map = held(FRONT);
  const pic = draw(map);
  assert.match(area(pic, 'sudland_coast').getAttribute('aria-label'), /Land territory, The South, held by Sudland \(enemy\)$/);
  assert.match(area(pic, 'norra_hills').getAttribute('aria-label'), /held by Norra \(yours\)$/);
  assert.doesNotMatch(area(pic, 'the_gulf').getAttribute('aria-label'), /held by/);
  const view = territoryView(map, SHAPES, { mode: 'list' });
  const rows = view.querySelectorAll('table.rl-area-list tbody tr');
  const row = (k) => rows.find((r) => r.getAttribute('data-area') === k);
  assert.deepEqual(view.querySelectorAll('table.rl-area-list thead th').map(words), ['Area', 'Kind', 'Region', 'Borders', 'Holder']);
  assert.equal(words(row('sudland_coast').childNodes.at(-1)), 'Sudland (enemy). On the front with The Norra Hills');
  assert.equal(words(row('norra_plain').childNodes.at(-1)), 'Valmy (ally)');
  assert.equal(words(row('the_gulf').childNodes.at(-1)), '');
});

// --- Rule 2: a border between two holders at war is heavy; every other is plain ----------------

test('holders are at war when one is the seat\'s enemy and the other its own or an ally', () => {
  assert.equal(rules.holdersAtWar({ holder: NORRA }, { holder: SUDLAND }), true);
  assert.equal(rules.holdersAtWar({ holder: FRANCE }, { holder: SUDLAND }), true);
  assert.equal(rules.holdersAtWar({ holder: NORRA }, { holder: FRANCE }), false, 'allies are not at war');
  assert.equal(rules.holdersAtWar({ holder: NORRA }, { holder: NORRA }), false);
  assert.equal(rules.holdersAtWar({ holder: SUDLAND }, { holder: SUDLAND }), false);
  assert.equal(rules.holdersAtWar({ holder: NEUTRAL }, { holder: SUDLAND }), false);
  assert.equal(rules.holdersAtWar({ holder: null }, { holder: SUDLAND }), false);
});

test('the border between holders at war is drawn heavy; all others plain, an ally\'s too', () => {
  const pic = draw(held(FRONT));
  const front = border(pic, 'norra_hills sudland_coast');
  assert.ok(front, 'the hills and the coast share a border');
  assert.ok(front.classList.contains('rl-border-front'));
  assert.equal(front.getAttribute('data-front'), 'true');
  const allies = border(pic, 'norra_hills norra_plain');
  assert.ok(allies, 'the hills and the plain share a border');
  assert.ok(!allies.classList.contains('rl-border-front'), 'own and ally: no front');
  assert.ok(allies.classList.contains('rl-border-land'));
  assert.equal(pic.querySelectorAll('path.rl-border-front').length, 1);
  // a coast and a sea zone are never a front, whoever holds the coast
  assert.ok(pic.querySelectorAll('path.rl-border-coast').every((b) => !b.classList.contains('rl-border-front')));
});

test('a front is heavier than a plain border, and not by colour: a wider stroke', () => {
  const heavy = CSS_TEXT.match(/\.rl-border-front \{[^}]*stroke-width: ([\d.]+)px/);
  const plain = CSS_TEXT.match(/\.rl-border-land \{[^}]*stroke-width: ([\d.]+)px/);
  assert.ok(heavy && plain);
  assert.ok(Number(heavy[1]) >= Number(plain[1]) * 3, `front ${heavy[1]}px against plain ${plain[1]}px`);
});

test('the front is said in words: the area\'s sheet and list row name the enemy across the line', () => {
  const { areas } = held(FRONT);
  const of = (k) => areas.find((a) => a.key === k);
  assert.equal(rules.frontLine(of('norra_hills'), areas), 'On the front with The Sudland Coast');
  assert.equal(rules.frontLine(of('norra_plain'), areas), '');
});

// --- Rule 3: a dated mark for a change of holder, the line for a capital marked to fall ------------

const SINCE = { isle: { held_since: '1900-04-02', taken_from: SUDLAND }, sudland_coast: { falling: '1900-04-09' } };

test('an area that changed hands carries a dated mark; one that did not carries none', () => {
  const pic = draw(held({ ...FRONT, isle: NORRA }, SINCE));
  const marks = pic.querySelectorAll('g.rl-tm-held');
  assert.equal(marks.length, 1);
  assert.equal(marks[0].getAttribute('data-area'), 'isle');
  assert.equal(words(marks[0]), 'Taken 2 Apr');
  assert.equal(marks[0].getAttribute('aria-label'), 'The Isle: Changed hands 2 Apr, taken from Sudland');
  assert.equal(rules.changedLine({ held_since: '1900-04-02', taken_from: SUDLAND }), 'Changed hands 2 Apr, taken from Sudland');
  assert.equal(rules.changedLine({ held_since: null, taken_from: null }), '');
});

test('a capital marked to fall carries the line, in the drawing and in the list', () => {
  const map = held(FRONT, SINCE);
  const pic = draw(map);
  const falls = pic.querySelectorAll('g.rl-tm-fall');
  assert.equal(falls.length, 1);
  assert.equal(falls[0].getAttribute('data-area'), 'sudland_coast');
  assert.equal(words(falls[0]), 'Falls after 9 Apr');
  assert.equal(falls[0].getAttribute('aria-label'),
    'The Sudland Coast: Capital marked to fall: it falls at the close of the wake after 9 Apr');
  assert.equal(rules.fallingLine({ falling: null }), '');
  const view = territoryView(map, SHAPES, { mode: 'list' });
  const row = view.querySelectorAll('table.rl-area-list tbody tr').find((r) => r.getAttribute('data-area') === 'sudland_coast');
  assert.match(words(row.childNodes.at(-1)), /Sudland \(enemy\)\. Capital marked to fall: it falls at the close of the wake after 9 Apr/);
});

test('a still picture draws the marks too, with nothing to press', () => {
  const pic = draw(held(FRONT, SINCE), { still: true });
  assert.equal(pic.querySelectorAll('g.rl-tm-fall').length, 1);
  assert.equal(pic.querySelectorAll('g.rl-tm-held').length, 1);
  assert.equal(area(pic, 'isle').getAttribute('tabindex'), null);
});

// --- Rule 4: a tap on an area opens its sheet ---------------------------------------------------

test('a tap or Enter on a land area asks for its sheet', () => {
  const asked = [];
  const pic = draw(held(FRONT), { onArea: (k) => asked.push(k) });
  fire(area(pic, 'norra_hills'), 'click');
  area(pic, 'isle').dispatchEvent({ type: 'keydown', key: 'Enter', preventDefault() {}, stopPropagation() {} });
  assert.deepEqual(asked, ['norra_hills', 'isle']);
});

test('the sheet gives the holder, since when, and the printed yields', () => {
  const map = held({ ...FRONT, isle: NORRA }, { ...SINCE, norra_plain: { yields: { grain: 10, levies: 2000 } } });
  const view = territoryView(map, SHAPES, { area: 'isle' });
  const sheet = view.querySelector('section.rl-area-sheet');
  assert.ok(sheet);
  assert.equal(words(sheet.querySelector('h3')), 'The Isle');
  const dl = sheet.querySelector('dl').childNodes.map(words);
  assert.deepEqual(dl, ['Holder', 'Norra (yours)', 'Held since', '2 Apr, taken from Sudland', 'Printed yields', 'None printed']);
  const plain = territoryView(map, SHAPES, { area: 'norra_plain' }).querySelector('section.rl-area-sheet');
  assert.deepEqual(plain.querySelector('dl').childNodes.map(words), ['Holder', 'Valmy (ally)', 'Held since', 'The same holder since the game began', 'Printed yields', 'grain 10, levies 2000']);
  const fall = territoryView(map, SHAPES, { area: 'sudland_coast' }).querySelector('section.rl-area-sheet');
  assert.match(words(fall), /Capital marked to fall: it falls at the close of the wake after 9 Apr/);
  assert.match(words(fall), /On the front with The Norra Hills/);
});

test('a sea zone\'s sheet has no holder and no yields; no sheet is open until an area is picked', () => {
  const map = held(FRONT);
  assert.equal(territoryView(map, SHAPES, {}).querySelector('section.rl-area-sheet'), null);
  const sea = territoryView(map, SHAPES, { area: 'the_gulf' }).querySelector('section.rl-area-sheet');
  assert.match(words(sea), /Sea zone/);
  assert.doesNotMatch(words(sea), /Holder/);
  assert.equal(territoryView(map, SHAPES, { area: 'no_such' }).querySelector('section.rl-area-sheet'), null);
});

test('the sheet closes by its own button, asking for no area', () => {
  const asked = [];
  const view = territoryView(held(FRONT), SHAPES, { area: 'isle', onArea: (k) => asked.push(k) });
  const close = view.querySelector('section.rl-area-sheet').querySelectorAll('button').find((b) => words(b) === 'Close');
  fire(close, 'click');
  assert.deepEqual(asked, [null]);
});

test('on the board a tap on an area is the room\'s pick, and the picked area\'s sheet is shown', async () => {
  const { theatreBoard, forgetShapes } = await import('../js/views/realism-theatre.js');
  forgetShapes();
  const reply = { reply: '', refused: false, file: fixture.territory_map.file, map: SHAPES };
  const was = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => structuredClone(reply) });
  try {
    const seat = (theatre) => ({ ...fixture, map: held(FRONT, SINCE) });
    const picked = [];
    const mk = (theatre) => theatreBoard(seat(), { piece: null, theatre: { mode: 'map', scope: 'reports', ...theatre } }, { pick: (p) => picked.push(p), act: () => {} });
    document.body.append(mk({}));
    await new Promise((ok) => setTimeout(ok, 0));
    await new Promise((ok) => setTimeout(ok, 0));
    const view = mk({});
    fire(view.querySelectorAll('path.rl-area').find((a) => a.getAttribute('data-area') === 'isle'), 'click');
    assert.equal(picked.at(-1).theatre.area, 'isle');
    assert.equal(mk({ area: 'isle' }).querySelector('section.rl-area-sheet').getAttribute('data-area'), 'isle');
  } finally { globalThis.fetch = was; }
});

// --- Keeps: nothing by colour alone, at both widths --------------------------------------------

test('every tint has a pattern rule and every front a stroke width, with tokens only, at both widths', () => {
  for (const px of [DESK, PHONE]) {
    const pic = draw(held(FRONT, SINCE), { px });
    for (const el of pic.querySelectorAll('path.rl-hold')) assert.match(el.getAttribute('fill'), /^url\(#/);
    assert.equal(pic.querySelectorAll('path.rl-border-front').length, 1);
  }
  for (const rel of ['own', 'ally', 'enemy', 'neutral']) assert.match(CSS_TEXT, new RegExp(`\\.rl-hold-${rel}`));
  const rules_ = CSS_TEXT.split('/* holders')[1] ?? '';
  assert.ok(rules_.length > 0, 'the holders block is in the stylesheet');
  assert.doesNotMatch(rules_, /#[0-9a-fA-F]{3,6}\b|rgb\(/, 'tokens only');
});
