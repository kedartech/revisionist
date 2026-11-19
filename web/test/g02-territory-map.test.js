// The territory map: when the seat's `map` block has `areas`, the board is drawn from the
// game's map file, fetched once per hash, with land filled, sea zones outlined and every border
// stroked; the frame is a region's, worked out from its areas alone, and holds still; marks
// and tap targets keep their size; zoom is 1, 2 or 4 times; every area is focusable and in the
// list; one layer at a time. A game without territories draws exactly as before.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { theatreBoard, loadShapes, forgetShapes, shapesFor } = await import('../js/views/realism-theatre.js');
const { territoryDrawing, territoryView, fit, offeredLayers } = await import('../js/views/realism-territory.js');
const rules = await import('../js/realism-rules.js');
const { pickPanel, uiFor } = await import('../js/views/realism-room.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const CSS_TEXT = readFileSync(new URL('../css/c-map.css', import.meta.url), 'utf8');
const TMAP = fixture.territory_map;
const HASH = TMAP.file.sha256;
const PHONE = { width: 366, height: 422 };
const DESK = { width: 960, height: 740 };

const seat = (map = {}) => ({ ...fixture, map: { ...structuredClone(TMAP), ...map } });
const ui = (theatre = {}, piece = null) => ({ piece, theatre: { mode: 'map', scope: 'reports', ...theatre } });
const board = (r, u = ui(), more = {}) => theatreBoard(r, u, { pick: () => {}, act: () => {}, ...more });
const box = (el) => el.querySelector('svg.rl-tm-svg').getAttribute('viewBox');
const viewBox = (svgEl) => svgEl.getAttribute('viewBox').split(' ').map(Number);
const group = (el, label) => el.querySelectorAll('[role="group"]').find((g) => g.getAttribute('aria-label') === label);
const pressed = (g) => g.querySelectorAll('button').filter((b) => b.getAttribute('aria-pressed') === 'true').map(words);
const draw = (map = TMAP, opts = {}) => territoryDrawing(map, SHAPES, { px: DESK, ...opts });

/** A fake `fetch` answering the `map` action with `reply`, counting what is asked. */
function serve(reply = { reply: '', refused: false, file: TMAP.file, map: SHAPES }) {
  const asked = [];
  const was = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    asked.push(url);
    return { ok: true, status: 200, json: async () => (url === '/api/realism/map' ? structuredClone(reply) : {}) };
  };
  return { asked, done: () => { globalThis.fetch = was; } };
}

/** The board after the shapes have arrived. */
async function drawn(r = seat(), u = ui(), more = {}) {
  forgetShapes();
  const net = serve();
  try {
    const first = board(r, u, more);
    document.body.append(first);
    await new Promise((ok) => setTimeout(ok, 0));
    await new Promise((ok) => setTimeout(ok, 0));
    first.remove();
    return { first, view: board(r, u, more), asked: net.asked };
  } finally { net.done(); }
}

// --- Rule 1: drawn from the game's map file, fetched once per hash --------------------------

test('a territory game fetches its map file once per hash, and never the coastline file', async () => {
  const { first, view, asked } = await drawn();
  assert.deepEqual(asked, ['/api/realism/map'], 'one ask for the shapes, no coastline');
  assert.ok(first.querySelector('figure svg.rl-tm-svg'), 'the first board fills in when the shapes land');
  assert.ok(group(first, 'Region') && group(first, 'Zoom'), 'with its region picker and zoom');
  assert.ok(view.querySelector('svg.rl-tm-svg'));
  const net = serve();
  try {
    board(seat()); board(seat(), ui({ frame: 'north' }));
    await new Promise((ok) => setTimeout(ok, 0));
    assert.deepEqual(net.asked, [], 'a hash already fetched is not fetched again');
  } finally { net.done(); }
});

test('boards drawn while the shapes are on their way ask for them once', async () => {
  forgetShapes();
  const net = serve();
  try {
    board(seat()); board(seat()); board(seat(), ui({ frame: 'north' }));
    await new Promise((ok) => setTimeout(ok, 0));
    await new Promise((ok) => setTimeout(ok, 0));
    assert.deepEqual(net.asked, ['/api/realism/map']);
  } finally { net.done(); }
});

test('a refused map action keeps no shapes and the board says it is drawing', async () => {
  forgetShapes();
  const net = serve({ reply: 'This game\'s map is missing on the server.', refused: true, file: null, map: null });
  try {
    const view = board(seat());
    assert.match(words(view.querySelector('figure')), /Drawing the map/);
    await new Promise((ok) => setTimeout(ok, 0));
    assert.equal(shapesFor(TMAP.file), null);
  } finally { net.done(); }
  assert.equal(await loadShapes({ name: 'x', sha256: 'other' }, async () => ({ refused: false, file: { sha256: 'nope' }, map: SHAPES })), undefined);
  assert.equal(shapesFor({ sha256: 'other' }), null, 'a reply for another hash is not kept');
});

test('land territories are filled, sea zones outlined, each from its rings', async () => {
  const { view } = await drawn();
  const areas = view.querySelectorAll('path.rl-area');
  assert.deepEqual(areas.map((a) => a.getAttribute('data-area')), TMAP.areas.map((a) => a.key));
  for (const a of TMAP.areas) {
    const el = areas.find((p) => p.getAttribute('data-area') === a.key);
    assert.ok(el.classList.contains(a.kind === 'sea' ? 'rl-area-sea' : 'rl-area-land'), a.key);
  }
  const isle = areas.find((p) => p.getAttribute('data-area') === 'isle').getAttribute('d');
  assert.equal(isle, 'M230 120L270 120L270 80L230 80L230 120Z', 'flat y runs up: drawn top-down');
  assert.match(CSS_TEXT, /\.rl-area-land \{ fill: var\(--chart-land\)/);
  assert.match(CSS_TEXT, /\.rl-area-sea \{ fill: transparent/);
});

test('every border is stroked, once, for both of its areas', () => {
  const pic = draw();
  const between = pic.querySelectorAll('path.rl-border').map((b) => b.getAttribute('data-between'));
  // every pair of areas sharing an edge in the file, whichever of the two lists it
  const pairs = new Set();
  for (const [k, a] of Object.entries(SHAPES.areas)) {
    for (const ring of a.rings) {
      for (let i = 1; i < ring.length; i += 1) {
        for (const [o, b] of Object.entries(SHAPES.areas)) {
          if (o === k) continue;
          for (const r2 of b.rings) {
            for (let j = 1; j < r2.length; j += 1) {
              if ((r2[j - 1] === ring[i] && r2[j] === ring[i - 1]) || (r2[j - 1] === ring[i - 1] && r2[j] === ring[i])) pairs.add([k, o].sort().join(' '));
            }
          }
        }
      }
    }
  }
  for (const p of pairs) assert.equal(between.filter((b) => b === p).length, 1, `one border for ${p}`);
  assert.ok(between.includes('isle open_sea'), 'the isle\'s coast is a border of both');
  assert.ok(between.includes('norra_hills'), 'the map\'s edge is stroked too');
  const kinds = Object.fromEntries(pic.querySelectorAll('path.rl-border').map((b) => [b.getAttribute('data-between'), b.getAttribute('class')]));
  assert.match(kinds['norra_hills norra_plain'], /rl-border-land/);
  assert.match(kinds['norra_plain the_gulf'], /rl-border-coast/);
  assert.match(kinds['open_sea the_gulf'], /rl-border-sea/);
});

test('borders(): a border shared by two areas is one entry, however the rings run', () => {
  const shapes = {
    vertices: [[0, 0], [1, 0], [1, 1], [0, 1], [2, 0], [2, 1]],
    areas: { a: { rings: [[0, 1, 2, 3, 0]] }, b: { rings: [[1, 4, 5, 2, 1]] } },
  };
  const out = rules.borders(shapes);
  const shared = out.filter((b) => b.between.join() === 'a,b');
  assert.equal(shared.length, 1);
  assert.deepEqual(shared[0].edges, [[1, 2]]);
});

test('a game without territories draws as before: the coastline file, no map action', async () => {
  forgetShapes();
  const net = serve();
  try {
    const view = board({ ...fixture }, { piece: null, theatre: { mode: 'map', scope: 'world' } });
    await new Promise((ok) => setTimeout(ok, 0));
    assert.ok(!view.querySelector('svg.rl-tm-svg'));
    assert.ok(view.querySelector('.rl-theatre-area'), 'the theatre boxes stay');
    assert.ok(!net.asked.includes('/api/realism/map'));
  } finally { net.done(); }
});

// --- Rule 2: the projection from coords; the widest frame is the map's own box ---------------

test('a flat map and a lonlat map both draw, each framed by its own box', () => {
  const flat = draw();
  assert.deepEqual(viewBox(flat), [0, 0, 300, 200], 'flat: a plain scale of the box');
  const lonlat = {
    format: 1, coords: 'lonlat', box: [20, 50, 40, 60],
    vertices: [[20, 50], [30, 50], [30, 60], [20, 60], [40, 50], [40, 60]],
    areas: { west: { rings: [[0, 1, 2, 3, 0]], label: [25, 55] }, east: { rings: [[1, 4, 5, 2, 1]], label: [35, 55] } },
    backdrop: [],
  };
  const map = {
    ...TMAP, marks: [], coords: 'lonlat', box: [20, 50, 40, 60], regions: [{ key: 'r', name: 'R', parent: null }],
    areas: [
      { key: 'west', name: 'West', kind: 'land', region: 'r', terrain: 'plain', neighbours: ['east'] },
      { key: 'east', name: 'East', kind: 'land', region: 'r', terrain: 'plain', neighbours: ['west'] },
    ],
  };
  const pic = territoryDrawing(map, lonlat, { px: DESK });
  const k = Math.cos((55 * Math.PI) / 180);
  const [x, y, w, hgt] = viewBox(pic);
  assert.deepEqual([x, y, hgt], [0, 0, 10]);
  assert.ok(Math.abs(w - 20 * k) < 0.01, 'today\'s squeezed projection for lonlat');
  assert.equal(pic.querySelectorAll('path.rl-area').length, 2);
});

test('the map block\'s box is the widest frame, not the marks', () => {
  const pic = draw({ ...TMAP, box: [0, 0, 300, 200] });
  assert.deepEqual(viewBox(pic), [0, 0, 300, 200]);
  const one = draw({ ...TMAP, marks: TMAP.marks.slice(0, 1) });
  assert.deepEqual(viewBox(one), [0, 0, 300, 200], 'one mark does not shrink the frame');
});

// --- Rule 3: a fixed frame per region; the picker walks the tree; the frame holds still ------

test('each region\'s frame is the box around its areas, at every level of the tree', () => {
  const frames = rules.regionFrames(TMAP, SHAPES);
  assert.deepEqual(frames.get('north'), { west: 0, south: 100, east: 200, north: 200 });
  assert.deepEqual(frames.get('south'), { west: 0, south: 0, east: 100, north: 100 });
  assert.deepEqual(frames.get('mainland'), { west: 0, south: 0, east: 200, north: 200 }, 'a parent spans its children');
  assert.deepEqual(frames.get('waters'), { west: 100, south: 0, east: 300, north: 200 });
  assert.deepEqual(viewBox(draw(TMAP, { frame: 'north' })), [0, 0, 200, 100]);
  assert.deepEqual(viewBox(draw(TMAP, { frame: 'south' })), [0, 100, 100, 100]);
  const north = draw(TMAP, { frame: 'north' });
  const clip = north.querySelector('clipPath rect');
  assert.deepEqual(['x', 'y', 'width', 'height'].map((a) => Number(clip.getAttribute(a))), [0, 0, 200, 100], 'nothing outside the frame shows');
  assert.equal(north.querySelector('g.rl-tm-frame').getAttribute('clip-path'), `url(#${north.querySelector('clipPath').getAttribute('id')})`);
});

test('the frame is identical before and after a sheet opens, a target lights or the poll lands', () => {
  for (const zoom of rules.ZOOMS) {
    const before = box(territoryView(TMAP, SHAPES, { frame: 'north', zoom, px: DESK }));
    const lit = [{ place: TMAP.places[1], value: 'sudby', days: '4 days', chosen: false }];
    assert.equal(box(territoryView(TMAP, SHAPES, { frame: 'north', zoom, px: DESK, targets: lit })), before, 'a target lit off the frame moves nothing');
    const moved = structuredClone(TMAP);
    moved.marks[0].piece.area = { key: 'sudland_coast', name: 'The Sudland Coast', place: null };
    assert.equal(box(territoryView(moved, SHAPES, { frame: 'north', zoom, px: DESK, selected: moved.marks[0].name })), before, 'a piece moved and picked moves nothing');
  }
});

test('the frame is identical before and after a sheet opens: a moving form opened on the board', async () => {
  const r = seat();
  const u = ui({ frame: 'waters' });
  const { view } = await drawn(r, u);
  const before = box(view);
  const fleet = { kind: 'force', name: 'US Atlantic Fleet' };
  const withForm = board({ ...r, map: { ...r.map, marks: [...r.map.marks, ...fixture.map.marks] } }, { ...u, piece: fleet });
  assert.equal(box(withForm), before);
});

test('the picker walks the tree: whole map, the trail to the frame, the regions under it', async () => {
  const picks = [];
  const { view } = await drawn(seat(), ui({ frame: 'mainland' }), { pick: (p) => picks.push(p) });
  const g = group(view, 'Region');
  assert.deepEqual(g.querySelectorAll('button').map(words), ['Whole map', 'The Mainland', 'The North', 'The South']);
  assert.deepEqual(pressed(g), ['The Mainland']);
  buttons(g, 'The North')[0].click();
  assert.equal(picks.at(-1).theatre.frame, 'north');
  const top = board(seat(), ui());
  assert.deepEqual(group(top, 'Region').querySelectorAll('button').map(words), ['Whole map', 'The Mainland', 'The Waters']);
});

test('the poll keeps the picker: the room\'s theatre state survives a redraw of the same game', () => {
  const state = uiFor('g-trm');
  pickPanel(state, { theatre: { ...state.theatre, frame: 'south', zoom: 2 } }, false);
  const again = uiFor('g-trm');
  assert.equal(again.theatre.frame, 'south');
  assert.equal(again.theatre.zoom, 2);
  pickPanel(again, { piece: { kind: 'force', name: 'x' } }, false);
  assert.equal(uiFor('g-trm').theatre.frame, 'south', 'a pick keeps the frame');
  assert.equal(box(territoryView(TMAP, SHAPES, { ...again.theatre, px: DESK })), '25 125 50 50');
});

// --- Rule 4: marks 24 px, tap targets 44 px; labels hide on overlap, show on tap -------------

test('marks are at least 24 px and tap targets 44 px at 390 px width, at every zoom', () => {
  for (const zoom of rules.ZOOMS) {
    const pic = draw(TMAP, { px: PHONE, zoom, fanned: 'norra_plain' });
    const k = Number(pic.getAttribute('data-k'));
    const [, , w, hgt] = viewBox(pic);
    assert.ok(Math.abs(k - Math.max(w / PHONE.width, hgt / PHONE.height)) < 1e-9, 'k: units a pixel');
    const mark = pic.querySelector('g.rl-tm-mark');
    assert.match(mark.getAttribute('transform'), new RegExp(`scale\\(${k}\\)`), 'marks are scaled back to pixels');
    const hit = mark.querySelector('rect.rl-tm-hit');
    assert.ok(Number(hit.getAttribute('width')) >= 44 && Number(hit.getAttribute('height')) >= 44);
    const shape = mark.querySelector('.rl-mk-shape');
    assert.ok(Number(shape.getAttribute('height')) >= 24 && Number(shape.getAttribute('width')) >= 24);
  }
  assert.equal(rules.MIN_MARK_PX, 24);
  assert.equal(rules.MIN_TAP_PX, 44);
  assert.match(CSS_TEXT, /\.rl-tmap \.rl-filter \{ min-height: 44px; min-width: 44px; \}/, 'the switches are tap-sized too');
});

test('a label sits at its area\'s label point, and is hidden when it would overlap another', () => {
  const pic = draw(TMAP, { px: DESK });
  const labels = pic.querySelectorAll('g.rl-tm-label');
  const isle = labels.find((l) => l.getAttribute('data-area') === 'isle');
  assert.deepEqual([isle.getAttribute('data-x'), isle.getAttribute('data-y')], ['250', '100'], 'the isle\'s label point, y flipped');
  assert.equal(labels.filter((l) => l.classList.contains('hidden')).length, 0, 'room for every label on a desk');
  fit(pic, { width: 120, height: 80 });
  const hidden = labels.filter((l) => l.classList.contains('hidden'));
  assert.ok(hidden.length > 0, 'crowded: some hidden');
  assert.ok(hidden.length < labels.length, 'the first is always kept');
  const key = hidden[0].getAttribute('data-area');
  pic.querySelector(`path.rl-area[data-area="${key}"]`).click();
  assert.ok(hidden[0].classList.contains('shown'), 'a tap on the area shows its label');
  assert.match(CSS_TEXT, /\.rl-tm-label\.hidden \{ display: none; \}/);
  assert.match(CSS_TEXT, /\.rl-tm-label\.hidden\.shown \{ display: inline; \}/);
});

test('hiddenLabels(): an overlap hides the later label; apart, none', () => {
  const two = [{ key: 'a', x: 0, y: 0, text: 'Alpha' }, { key: 'b', x: 5, y: 0, text: 'Bravo' }];
  assert.deepEqual([...rules.hiddenLabels(two, 1)], ['b']);
  assert.deepEqual([...rules.hiddenLabels(two, 0.01)], []);
});

// --- Rule 5: zoom 1, 2, 4 by buttons and pinch; the phone map is never under half the height --

test('zoom is 1, 2 and 4 times within the frame, by buttons', async () => {
  const picks = [];
  const { view } = await drawn(seat(), ui({ frame: 'north' }), { pick: (p) => picks.push(p) });
  const g = group(view, 'Zoom');
  assert.deepEqual(g.querySelectorAll('button').map(words), ['1×', '2×', '4×']);
  buttons(g, '2×')[0].click();
  assert.equal(picks.at(-1).theatre.zoom, 2);
  assert.equal(picks.at(-1).theatre.frame, 'north', 'zoom keeps the frame');
  const [x, y, w, hgt] = viewBox(draw(TMAP, { frame: 'north', zoom: 4, centre: [0, 0] }));
  assert.deepEqual([w, hgt], [50, 25]);
  assert.deepEqual([x, y], [0, 0], 'never outside the frame');
  const [x2, y2] = viewBox(draw(TMAP, { frame: 'north', zoom: 4, centre: [1000, 1000] }));
  assert.deepEqual([x2, y2], [150, 75]);
});

test('a pinch picks the nearest zoom step', () => {
  assert.equal(rules.pinchZoom(1, 1.1), 1);
  assert.equal(rules.pinchZoom(1, 2.2), 2);
  assert.equal(rules.pinchZoom(2, 2.5), 4);
  assert.equal(rules.pinchZoom(4, 0.4), 2);
  assert.equal(rules.pinchZoom(4, 10), 4);
  const views = [];
  const pic = draw(TMAP, { px: { width: 300, height: 200 }, onView: (v) => views.push(v) });
  const ev = (type, id, x, y) => ({ type, pointerId: id, clientX: x, clientY: y, target: pic, preventDefault() {}, stopPropagation() {} });
  pic.dispatchEvent(ev('pointerdown', 1, 140, 100));
  pic.dispatchEvent(ev('pointerdown', 2, 160, 100));
  pic.dispatchEvent(ev('pointermove', 1, 120, 100));
  pic.dispatchEvent(ev('pointermove', 2, 180, 100));
  pic.dispatchEvent(ev('pointerup', 1, 120, 100));
  pic.dispatchEvent(ev('pointerup', 2, 180, 100));
  assert.equal(views.length, 1, 'told once, at the end');
  assert.equal(views[0].zoom, 4, 'spread three times: the 4× step');
  assert.deepEqual(views[0].centre, [150, 100]);
});

test('on a phone the map is never under half the viewport\'s height', () => {
  const phone = CSS_TEXT.slice(CSS_TEXT.lastIndexOf('@media (max-width: 767px)'));
  assert.match(phone, /\.rl-tm-svg \{[^}]*min-height: 50vh/);
});

// --- Rule 6: every area focusable, and in the list -----------------------------------------

test('every area is focusable and named', () => {
  const pic = draw();
  for (const a of pic.querySelectorAll('path.rl-area')) {
    assert.equal(a.getAttribute('tabindex'), '0');
    assert.match(a.getAttribute('aria-label'), /: (Land territory|Sea zone), The /);
  }
});

test('every area has a twin in List mode: its name, kind, region and neighbours', async () => {
  const { view } = await drawn(seat(), ui({ mode: 'list' }));
  const rows = view.querySelectorAll('table.rl-area-list tbody tr');
  assert.equal(rows.length, TMAP.areas.length);
  const gulf = rows.find((r) => r.getAttribute('data-area') === 'the_gulf');
  assert.deepEqual(gulf.childNodes.map(words), ['The Gulf', 'Sea zone', 'The Waters', 'The Norra Plain, The Open Sea, The Sudland Coast', '']);
  const hills = rows.find((r) => r.getAttribute('data-area') === 'norra_hills');
  assert.deepEqual(hills.childNodes.map(words), ['The Norra Hills', 'Land territory', 'The North', 'The Norra Plain, The Sudland Coast', 'No holder']);
});

// --- Rule 7: one layer at a time, one switch, a layer with nothing to draw not offered -------

test('one layer shows at a time; a layer with nothing to draw yet is not offered', async () => {
  assert.deepEqual(offeredLayers(TMAP), ['military']);
  const { view } = await drawn();
  // ECO: the economy layer is offered after them wherever the board prints a yield
  assert.deepEqual(group(view, 'Layer').querySelectorAll('button').map(words), ['Military', 'Economy']);
  assert.deepEqual(pressed(group(view, 'Layer')), ['Military'], 'the board opens on the first layer, not the economy');
  assert.equal(group(view, 'Scope'), undefined, 'no reports/world scope in a territory game');
  const capitals = [{ name: 'Old Brann', place: TMAP.places[1], stance: { word: 'Hostile', step: 1 }, at_war: true }];
  const both = board(seat({ capitals }), ui({ layer: 'diplomatic' }));
  assert.deepEqual(group(both, 'Layer').querySelectorAll('button').map(words), ['Military', 'Diplomatic', 'Economy']);
  assert.deepEqual(pressed(group(both, 'Layer')), ['Diplomatic']);
  assert.equal(both.querySelectorAll('g.rl-tm-mark, g.rl-tm-stack').length, 0, 'the diplomatic layer draws no pieces');
  assert.equal(both.querySelectorAll('g.rl-cap').length, 1);
  const mil = board(seat({ capitals }), ui({ layer: 'military' }));
  assert.equal(mil.querySelectorAll('g.rl-cap').length, 0, 'the military layer draws no capitals');
  assert.ok(mil.querySelectorAll('g.rl-tm-mark, g.rl-tm-stack').length > 0);
  const asked = board(seat(), ui({ layer: 'diplomatic' }));
  assert.ok(asked.querySelectorAll('g.rl-tm-mark, g.rl-tm-stack').length > 0, 'a layer not offered falls back to one that is');
});

test('own pieces stand at their area\'s label point', () => {
  const pic = draw(TMAP, { fanned: 'norra_plain' });
  const herald = pic.querySelectorAll('g.rl-tm-mark').find((g) => /Norra Herald/.test(g.getAttribute('aria-label')));
  assert.deepEqual([herald.getAttribute('data-x'), herald.getAttribute('data-y')], ['150', '50'], 'the Norra Plain\'s label point');
  assert.match(herald.getAttribute('aria-label'), /Herald, Yours · Norra, Known, The Norra Plain/);
});
