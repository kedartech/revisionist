// The board picks and sends a piece that stands in an area (BPA). In a territory world a mark of
// the world's own pieces has kind `piece`; picking one shows its panel with the piece's own kind.
// A movement form may offer places as destinations while the piece stands in an area: the board
// lights the area each offered place lies in for that force (the form's `areas`), when that area
// is one of the piece's moves, and files the form with the place the form offers for it, the first
// in the form's order when two lie in one area, naming that place on the chip. A form that offers
// area keys works as before, and a game without territories is unchanged.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { theatreBoard, forgetShapes } = await import('../js/views/realism-theatre.js');
const { forgetMarks } = await import('../js/views/realism-territory.js');
const { piecePanel } = await import('../js/views/realism-board.js');
const rules = await import('../js/realism-rules.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const TMAP = fixture.territory_map;
const LEVY = 'The Norra Levy';

/** The toy world's form as a 1941 fleet form offers it: places as destinations, with the area each lies in for each force. */
function placeForm({ choices, areas } = {}) {
  return {
    name: 'move_piece',
    label: 'Move a piece',
    summary: 'Send a piece to a place.',
    pipeline: 'field_order',
    params: [
      { name: 'force', label: 'Which piece', kind: 'enum', lo: null, hi: null, places: [], areas: {}, choices: [
        { value: 'norra_levy', label: 'The Norra Levy' }, { value: 'norra_kites', label: 'The Norra Kites' }] },
      { name: 'to', label: 'To', kind: 'enum', lo: null, hi: null, places: [], choices: choices ?? [
        { value: 'gulf_roads', label: 'The Gulf Roads' }, { value: 'sudby', label: 'Sudby' },
        { value: 'sudby_quay', label: 'Sudby Quay' }, { value: 'norrhavn', label: 'Norrhavn' }],
      areas: areas ?? {
        norra_levy: { gulf_roads: 'the_gulf', sudby: 'sudland_coast', sudby_quay: 'sudland_coast', norrhavn: 'norra_plain' },
        norra_kites: { gulf_roads: 'the_gulf', sudby: 'sudland_coast', sudby_quay: 'sudland_coast', norrhavn: 'norra_plain' },
      } },
    ],
  };
}

function seat(lever = placeForm()) {
  return {
    ...fixture,
    map: structuredClone(TMAP),
    desk: { ...fixture.desk, levers: [lever] },
    court: { load_limit: 2, ring: [], chambers: [], paths: [] },
    clock: { ...fixture.clock, world_date: '1900-04-02' },
    orders: { orders: [] },
  };
}

async function room(rv) {
  const ui = { piece: null, theatre: { mode: 'map', scope: 'reports' } };
  const acts = [];
  const was = globalThis.fetch;
  globalThis.fetch = async (url) => ({ ok: true, status: 200, json: async () => (url === '/api/realism/map' ? { reply: '', refused: false, file: TMAP.file, map: SHAPES } : {}) });
  const r = {
    ui,
    acts,
    view: null,
    draw() {
      r.view?.remove();
      r.view = theatreBoard(rv, ui, {
        pick: (p) => { if (p.theatre) ui.theatre = p.theatre; if (p.piece !== undefined) ui.piece = p.piece; r.draw(); },
        act: (message, action, body, then) => { acts.push({ message, action, body, then }); },
      });
      document.body.append(r.view);
      return r.view;
    },
  };
  try {
    forgetShapes();
    forgetMarks();
    r.draw();
    await new Promise((ok) => setTimeout(ok, 0));
    await new Promise((ok) => setTimeout(ok, 0));
  } finally { globalThis.fetch = was; }
  r.draw();
  return r;
}
const pickLevy = (r) => { r.ui.piece = { kind: 'force', name: LEVY }; return r.draw(); };
const lit = (view) => view.querySelectorAll('g.rl-map-target').map((g) => g.getAttribute('data-area')).sort();
const litArea = (view, key) => view.querySelectorAll('g.rl-map-target').find((g) => g.getAttribute('data-area') === key);
const chip = (view) => view.querySelector('.rl-pup-chip');
const sendIt = (view) => chip(view).querySelectorAll('button').find((b) => words(b) === 'Send it');
/** The panel's "What" line. */
const what = (panel) => words(panel.querySelectorAll('dd')[0]);
const filed = (r) => r.acts.filter((a) => a.action === 'lever').map((a) => a.body);

// --- rule 1: a mark of kind `piece` has a panel ------------------------------------

test('picking a mark of kind piece shows its panel with the piece\'s own kind, and does not throw', () => {
  const rv = seat();
  const levy = rv.map.marks.find((m) => m.name === LEVY);
  assert.equal(levy.kind, 'piece');
  const panel = piecePanel(rv, { kind: 'force', name: LEVY }, () => {});
  const said = words(panel);
  assert.match(said, new RegExp(LEVY));
  assert.equal(what(panel), levy.piece.kind);
});

test('a mark of kind piece with no piece block says Piece, as the territory view does', () => {
  const rv = seat();
  const levy = rv.map.marks.find((m) => m.name === LEVY);
  levy.piece = null;
  assert.equal(what(piecePanel(rv, { kind: 'force', name: LEVY }, () => {})), 'Piece');
});

test('no mark kind the server can send makes the panel throw', () => {
  for (const kind of ['fleet', 'army', 'air', 'front', 'route', 'piece']) {
    const rv = seat();
    rv.map.marks.find((m) => m.name === LEVY).kind = kind;
    assert.doesNotThrow(() => piecePanel(rv, { kind: 'force', name: LEVY }, () => {}), kind);
  }
});

test('a point map mark keeps the words it had', () => {
  const fleet = fixture.map.marks.find((m) => m.name === 'US Atlantic Fleet');
  const panel = piecePanel(fixture, { kind: 'force', name: fleet.name }, () => {});
  assert.equal(what(panel), rules.markKindWord(fleet.kind));
});

// --- rule 2: places light the area they lie in; choosing files the place ------------

test('the form\'s destinations by area: each place under the area it lies in for the force, area keys as themselves', () => {
  const lever = placeForm({
    choices: [{ value: 'isle', label: 'The Isle' }, { value: 'sudby', label: 'Sudby' }, { value: 'sudby_quay', label: 'Sudby Quay' }],
    areas: { norra_levy: { sudby: 'sudland_coast', sudby_quay: 'sudland_coast' } },
  });
  const got = rules.formDestinations(lever, 'norra_levy');
  assert.deepEqual([...got.entries()], [
    ['isle', { value: 'isle', place: null, count: 1 }],
    ['sudland_coast', { value: 'sudby', place: 'Sudby', count: 2 }],
  ]);
  assert.deepEqual([...rules.formDestinations(lever, 'norra_kites').keys()], ['isle', 'sudby', 'sudby_quay'], 'a force the form gives no areas for keeps the values');
});

test('a picked piece whose form offers places lights the area each place lies in, when it is one of the piece\'s moves', async () => {
  const r = await room(seat());
  pickLevy(r);
  assert.deepEqual(lit(r.view), ['sudland_coast'], 'the Levy moves to the Isle and the Sudland coast; only Sudby\'s area is offered');
});

test('an offered place\'s area that is not one of the piece\'s moves is not lit', async () => {
  const r = await room(seat());
  pickLevy(r);
  assert.equal(litArea(r.view, 'the_gulf'), undefined, 'the Gulf Roads lies in the Gulf, which the Levy cannot reach');
  assert.equal(litArea(r.view, 'norra_plain'), undefined, 'Norrhavn lies where the Levy stands');
});

test('choosing a lit area files the form with the place the form offers there', async () => {
  const r = await room(seat());
  pickLevy(r);
  litArea(r.view, 'sudland_coast').click();
  sendIt(r.view).click();
  assert.deepEqual(filed(r), [{ lever: 'move_piece', params: { force: 'norra_levy', to: 'sudby' } }]);
});

test('a form that offers area keys works as before', async () => {
  const lever = placeForm({
    choices: [{ value: 'isle', label: 'The Isle' }, { value: 'sudland_coast', label: 'The Sudland Coast' }],
    areas: {},
  });
  const r = await room(seat(lever));
  pickLevy(r);
  assert.deepEqual(lit(r.view), ['isle', 'sudland_coast']);
  litArea(r.view, 'isle').click();
  assert.doesNotMatch(words(chip(r.view)), /Filed as/);
  sendIt(r.view).click();
  assert.deepEqual(filed(r), [{ lever: 'move_piece', params: { force: 'norra_levy', to: 'isle' } }]);
});

// --- rule 3: two places in one area: the first in the form's order, named --------

test('two offered places in one area: the chip names the first in the form\'s order and files it', async () => {
  const r = await room(seat());
  pickLevy(r);
  litArea(r.view, 'sudland_coast').click();
  assert.match(words(chip(r.view)), /Filed as Sudby, the first of 2 places the form offers in The Sudland Coast/);
  const swapped = placeForm({
    choices: [{ value: 'sudby_quay', label: 'Sudby Quay' }, { value: 'sudby', label: 'Sudby' }],
  });
  const again = await room(seat(swapped));
  pickLevy(again);
  litArea(again.view, 'sudland_coast').click();
  assert.match(words(chip(again.view)), /Filed as Sudby Quay/);
  sendIt(again.view).click();
  assert.equal(filed(again)[0].params.to, 'sudby_quay');
});

test('one offered place in an area: the chip names it without a count', async () => {
  const lever = placeForm({ choices: [{ value: 'sudby', label: 'Sudby' }], areas: { norra_levy: { sudby: 'sudland_coast' } } });
  const r = await room(seat(lever));
  pickLevy(r);
  litArea(r.view, 'sudland_coast').click();
  const said = words(chip(r.view));
  assert.match(said, /Filed as Sudby(?!,| Quay)/);
  assert.doesNotMatch(said, /the first of/);
});

// --- rule 5: a game without territories is unchanged --------------------------------

test('a point game\'s pick still draws its forms panel and no chip, with the form\'s areas present or not', () => {
  for (const withAreas of [false, true]) {
    const rv = structuredClone(fixture);
    if (withAreas) for (const l of rv.desk.levers) for (const p of l.params) p.areas = { us_atlantic_fleet: { norfolk: 'western_atlantic' } };
    const view = theatreBoard(rv, { piece: { kind: 'force', name: 'US Atlantic Fleet' }, theatre: { mode: 'map', scope: 'reports' } }, { pick: () => {}, act: () => {} });
    assert.ok(view.querySelector('.rl-theatre-forms'), 'the point map\'s forms still show');
    assert.equal(chip(view), null);
  }
});
