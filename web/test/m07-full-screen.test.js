// The map full screen, with its controls on the map: when the room sets `opts.overlay` the map's
// title is for a screen reader only, its line of explanation is not drawn, and its controls sit
// over its corners (the regions and the layers fold into one control each on a phone); a Full
// screen control and the F key on the map ask the room for the whole viewport (`opts.onFull`) and
// the browser for its own full screen where it has one; zoom, centre, the picked piece and an open
// area sheet are kept; a sheet in full screen opens over the map and Escape closes it first.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };

const { territoryView, forgetFull } = await import('../js/views/realism-territory.js');
const { theatreBoard, forgetShapes, loadShapes } = await import('../js/views/realism-theatre.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const CSS_MAP = readFileSync(new URL('../css/c-map.css', import.meta.url), 'utf8');
const CSS_ROOM = readFileSync(new URL('../css/c-sheets.css', import.meta.url), 'utf8');
const TMAP = fixture.territory_map;
const DESK = { width: 960, height: 740 };

const group = (el, label) => el.querySelectorAll('[role="group"]').find((g) => g.getAttribute('aria-label') === label) ?? null;
const view = (opts = {}) => territoryView(TMAP, SHAPES, { px: DESK, frame: 'mainland', overlay: true, ...opts });
const fullBtn = (el) => el.querySelector('button.rl-tm-full');
/** `el` inside a room root on the page, in full screen or not (the page holds one room at a time). */
const inRoom = (el, full) => {
  const root = document.createElement('div');
  root.className = full ? 'realism-screen rl-full' : 'realism-screen';
  root.append(el);
  document.body.replaceChildren(root);
  return el;
};
/** A key pressed on `el`, sent up through its ancestors as a page would (the fake does not bubble). */
function press(el, key, more = {}) {
  const ev = { type: 'keydown', key, target: el, defaultPrevented: false, ...more, preventDefault() { this.defaultPrevented = true; } };
  for (let n = el; n && n.dispatchEvent; n = n.parentNode) n.dispatchEvent(ev);
  return ev;
}
/** The browser's own full screen, faked on the document: what was asked, and whether it refuses. */
function browser({ has = true, refuse = false } = {}) {
  const asked = [];
  const root = document.createElement('html');
  document.documentElement = root;
  document.fullscreenElement = null;
  if (has) {
    root.requestFullscreen = () => { asked.push('enter'); if (refuse) return Promise.reject(new Error('refused')); document.fullscreenElement = root; return Promise.resolve(); };
    document.exitFullscreen = () => { asked.push('exit'); document.fullscreenElement = null; return Promise.resolve(); };
  } else {
    delete document.exitFullscreen;
  }
  return asked;
}
const tick = () => new Promise((ok) => setTimeout(ok, 0));

// --- Rule 1: with the overlay, no title row and no explanation; the controls over the map's corners

test('with the overlay the title is for a screen reader only and the line of explanation is not drawn', () => {
  const v = view();
  const h2 = v.querySelector('h2');
  assert.equal(words(h2), 'Map', 'the title is still there to be read');
  assert.ok(h2.classList.contains('sr-only'), 'and drawn for a screen reader only');
  assert.equal(v.querySelectorAll('p.muted').length, 0, 'no line of explanation');
  const classic = territoryView(TMAP, SHAPES, { px: DESK, frame: 'mainland' });
  assert.ok(!classic.querySelector('h2').classList.contains('sr-only'), 'the Classic layout keeps its title row');
  assert.equal(classic.querySelectorAll('p.muted').length, 1, 'and its line');
});

test('with the overlay the layer, region, zoom and map-or-list controls sit over the map\'s corners, not in rows above it', () => {
  const v = view();
  const stage = v.querySelector('.rl-tm-stage');
  assert.ok(stage, 'the map sits in a stage the controls are laid over');
  assert.ok(stage.querySelector('figure.rl-map-figure'), 'with the drawing in it');
  assert.equal(v.querySelectorAll('.rl-bar').length, 0, 'no row of controls above the map');
  const top = stage.querySelector('.rl-tm-corner.rl-tm-top');
  const foot = stage.querySelector('.rl-tm-corner.rl-tm-zoomcorner');
  assert.ok(top && foot, 'a top corner and a zoom corner');
  assert.ok(group(top.querySelector('.rl-tm-tools-start'), 'Layer'), 'the layers at the top left');
  assert.ok(group(top.querySelector('.rl-tm-tools-start'), 'Region'), 'the regions at the top left');
  assert.ok(group(top.querySelector('.rl-tm-tools-end'), 'Show as'), 'map or list at the top right');
  assert.ok(fullBtn(top.querySelector('.rl-tm-tools-end')), 'full screen at the top right');
  assert.ok(group(foot, 'Zoom'), 'the zoom at the foot');
  const svgEl = v.querySelector('svg.rl-tm-svg');
  for (const c of v.querySelectorAll('.rl-tm-corner')) assert.equal(c.closest('figure'), null, 'no control inside the drawing\'s figure');
  assert.equal(svgEl.querySelectorAll('button, select').length, 0, 'no control inside the drawing');
  const classic = territoryView(TMAP, SHAPES, { px: DESK, frame: 'mainland' });
  assert.ok(classic.querySelector('.rl-bar'), 'the Classic layout keeps its rows');
  assert.equal(classic.querySelectorAll('.rl-tm-corner, .rl-tm-stage, button.rl-tm-full').length, 0, 'and has no corners and no Full screen');
});

test('a control over the map takes the press: the corners let a press through only between controls', () => {
  assert.match(CSS_MAP, /\.rl-tm-corner\s*\{[^}]*pointer-events:\s*none/, 'the corner itself lets a press through to the map');
  assert.match(CSS_MAP, /\.rl-tm-corner [^{]*>\s*\*[^{]*\{[^}]*pointer-events:\s*auto/, 'a control in it takes the press');
  assert.match(CSS_MAP, /\.rl-tm-corner\s*\{[^}]*z-index:\s*[1-9]/, 'and is drawn over the map');
  const v = view();
  const zoom = group(v, 'Zoom');
  const picks = [];
  const v2 = view({ onView: (x) => picks.push(x) });
  buttons(group(v2, 'Zoom'), '2×')[0].click();
  assert.deepEqual(picks, [{ zoom: 2, centre: null }], 'a zoom button zooms, as it did');
  assert.ok(zoom.querySelectorAll('button').every((b) => b.getAttribute('aria-label')?.startsWith('Zoom ')));
});

test('on a phone the regions and the layers fold into one control each', () => {
  const frames = [];
  const layers = [];
  const v = view({ onFrame: (f) => frames.push(f), onLayer: (l) => layers.push(l) });
  const region = v.querySelector('select.rl-tm-fold[aria-label="Region"]');
  assert.ok(region, 'a region control');
  assert.deepEqual(region.querySelectorAll('option').map(words), ['Whole map', 'The Mainland', 'The North', 'The South']);
  assert.deepEqual(region.querySelectorAll('option[selected]').map(words), ['The Mainland'], 'the frame is the one chosen');
  region.dispatchEvent({ type: 'change', target: { value: 'north' } });
  assert.deepEqual(frames, ['north']);
  const layer = v.querySelector('select.rl-tm-fold[aria-label="Layer"]');
  assert.ok(layer, 'a layer control');
  assert.deepEqual(layer.querySelectorAll('option').map(words), group(v, 'Layer').querySelectorAll('button').map(words));
  layer.dispatchEvent({ type: 'change', target: { value: 'economy' } });
  assert.deepEqual(layers, ['economy']);
  assert.ok(group(v, 'Region').classList.contains('rl-tm-wide') && group(v, 'Layer').classList.contains('rl-tm-wide'), 'the rows of toggles are the wide screen\'s');
  assert.match(CSS_MAP, /@media \(max-width: 767px\)\s*\{[^@]*\.rl-tm-overlay \.rl-tm-wide\s*\{\s*display:\s*none/, 'on a phone the rows of toggles are not drawn');
  assert.match(CSS_MAP, /\.rl-tm-fold\s*\{[^}]*display:\s*none/, 'and the folded control is not drawn on a wide screen');
  assert.match(CSS_MAP, /@media \(max-width: 767px\)\s*\{[^@]*\.rl-tm-overlay \.rl-tm-fold\s*\{\s*display:\s*inline-block/, 'but is on a phone');
  assert.match(CSS_MAP, /\.rl-tm-fold\s*\{[^}]*min-height:\s*44px/, 'at a 44 px target');
  assert.match(CSS_MAP, /@media \(max-width: 767px\)\s*\{[^@]*\.rl-tm-overlay \.rl-tm-tools-end \.rl-filters > \[aria-pressed="true"\]\s*\{\s*display:\s*none/,
    'and of Map or List only the other one is drawn');
});

test('every control over the map is a 44 px target', () => {
  assert.match(CSS_MAP, /\.rl-tmap \.rl-filter\s*\{[^}]*min-height:\s*44px;\s*min-width:\s*44px/);
  assert.match(CSS_MAP, /\.rl-tm-full\s*\{[^}]*min-height:\s*44px;\s*min-width:\s*44px/);
});

// --- Rule 2: Full screen, and the F key on the map, ask the room for the whole viewport -------

test('the Full screen control asks the room for the whole viewport, and gives it back in full screen', () => {
  browser({ has: false });
  forgetFull();
  const asked = [];
  const out = inRoom(view({ onFull: (on) => asked.push(on) }), false);
  const btn = fullBtn(out);
  assert.equal(btn.getAttribute('type'), 'button');
  assert.equal(words(btn.querySelector('.rl-tm-full-in')), 'Full screen');
  assert.equal(words(btn.querySelector('.rl-tm-full-out')), 'Leave full screen');
  btn.click();
  assert.deepEqual(asked, [true]);
  const inside = inRoom(view({ onFull: (on) => asked.push(on) }), true);
  fullBtn(inside).click();
  assert.deepEqual(asked, [true, false], 'in full screen the same control leaves it');
  assert.match(CSS_MAP, /\.rl-tm-full \.rl-tm-full-out\s*\{\s*display:\s*none/, 'out of full screen it reads Full screen');
  assert.match(CSS_MAP, /\.rl-full \.rl-tm-full \.rl-tm-full-in\s*\{\s*display:\s*none/, 'in it, Leave full screen');
  assert.match(CSS_MAP, /\.rl-full \.rl-tm-full \.rl-tm-full-out\s*\{\s*display:\s*inline/);
  const list = inRoom(view({ mode: 'list', onFull: (on) => asked.push(on) }), true);
  assert.ok(fullBtn(list), 'the list keeps the way out of full screen');
});

test('F on the map enters full screen and leaves it; not with a modifier, and not from a field', () => {
  browser({ has: false });
  forgetFull();
  const asked = [];
  const v = inRoom(view({ onFull: (on) => asked.push(on) }), false);
  const map = v.querySelector('svg.rl-tm-svg');
  const ev = press(map, 'f');
  assert.deepEqual(asked, [true], 'F on the map asks for full screen');
  assert.equal(ev.defaultPrevented, true);
  press(map, 'F', { ctrlKey: true });
  press(map, 'f', { metaKey: true });
  press(map, 'f', { altKey: true });
  assert.deepEqual(asked, [true], 'not with a modifier');
  press(v.querySelector('select.rl-tm-fold'), 'f');
  assert.deepEqual(asked, [true], 'not from a field');
  const full = inRoom(view({ onFull: (on) => asked.push(on) }), true);
  press(full.querySelector('svg.rl-tm-svg'), 'F');
  assert.deepEqual(asked, [true, false], 'F in full screen leaves it');
  const classic = territoryView(TMAP, SHAPES, { px: DESK, frame: 'mainland', onFull: (on) => asked.push(on) });
  press(classic.querySelector('svg.rl-tm-svg'), 'f');
  assert.deepEqual(asked, [true, false], 'the Classic layout has no full screen');
});

test('Escape with no sheet open is the room\'s: the map leaves it alone', () => {
  const asked = [];
  const v = inRoom(view({ onFull: (on) => asked.push(on) }), true);
  const ev = press(v.querySelector('svg.rl-tm-svg'), 'Escape');
  assert.equal(ev.defaultPrevented, false, 'the room\'s own handler leaves full screen');
  assert.deepEqual(asked, []);
});

test('in full screen the map fills the viewport from edge to edge', () => {
  assert.match(CSS_MAP, /\.rl-tm-stage > \.rl-map-figure\s*\{[^}]*position:\s*absolute;\s*inset:\s*0;\s*border:\s*0;\s*border-radius:\s*0/);
  assert.match(CSS_ROOM, /\.rl-full \.rl-mapfirst \.rl-mapfirst-map,\s*\.rl-full \.rl-mapfirst\.sheeted \.rl-mapfirst-map\s*\{\s*padding:\s*0/, 'the room takes its padding off');
  assert.match(CSS_ROOM, /@media \(min-width: 1024px\)\s*\{[^@]*\.rl-full \.rl-needs\s*\{\s*display:\s*none/, 'the list beside the map goes from beside it');
  assert.match(CSS_ROOM, /\.rl-full \.rl-needs\.open\s*\{[^}]*position:\s*fixed/, 'and opens over the map');
  assert.match(CSS_ROOM, /\.rl-full \.rl-needsbar\s*\{[^}]*display:\s*flex/, 'What needs you and Done stay, over the map');
});

// --- Rule 3: the browser's own full screen where it is granted -------------------------------

test('entering asks the browser for its own full screen, and leaving gives it back', async () => {
  const asked = browser();
  forgetFull();
  const room = [];
  fullBtn(inRoom(view({ onFull: (on) => room.push(on) }), false)).click();
  assert.deepEqual(asked, ['enter']);
  assert.deepEqual(room, [true]);
  await tick();
  fullBtn(inRoom(view({ onFull: (on) => room.push(on) }), true)).click();
  assert.deepEqual(asked, ['enter', 'exit']);
  assert.deepEqual(room, [true, false]);
});

test('a browser that refuses, or has no full screen of its own, still gets the map filling the page and no error', async () => {
  for (const how of [{ refuse: true }, { has: false }]) {
    const asked = browser(how);
    forgetFull();
    const room = [];
    assert.doesNotThrow(() => fullBtn(inRoom(view({ onFull: (on) => room.push(on) }), false)).click());
    await tick();
    assert.deepEqual(room, [true], JSON.stringify(how));
    assert.deepEqual(asked, how.has === false ? [] : ['enter']);
    fullBtn(inRoom(view({ onFull: (on) => room.push(on) }), true)).click();
    assert.deepEqual(room, [true, false]);
    assert.ok(!asked.includes('exit'), 'nothing to give back');
  }
});

test('a full screen the map did not ask for is not left by the map', async () => {
  const asked = browser();
  forgetFull();
  document.fullscreenElement = document.documentElement;
  fullBtn(inRoom(view({ onFull: () => {} }), false)).click();
  fullBtn(inRoom(view({ onFull: () => {} }), true)).click();
  await tick();
  assert.deepEqual(asked, [], 'already full: not asked again, and not left');
});

test('when the room gives the viewport back itself (Escape), the browser\'s full screen is left too', async () => {
  const asked = browser();
  forgetFull();
  fullBtn(inRoom(view({ onFull: () => {} }), false)).click();
  await tick();
  inRoom(view({ onFull: () => {} }), true); // the room's full screen drawn: kept
  await tick();
  assert.deepEqual(asked, ['enter']);
  inRoom(view({ onFull: () => {} }), false); // the room drew the map out of full screen
  await tick();
  assert.deepEqual(asked, ['enter', 'exit']);
});

// --- Rule 4: zoom, centre, the picked piece and an open area sheet are kept --------------------

async function board(u, onFull, picks) {
  forgetShapes();
  const was = globalThis.fetch;
  globalThis.fetch = async (url) => ({ ok: true, status: 200, json: async () => (url === '/api/realism/map' ? { reply: '', refused: false, file: TMAP.file, map: structuredClone(SHAPES) } : {}) });
  try { await loadShapes(TMAP.file); } finally { globalThis.fetch = was; }
  const rv = { ...fixture, map: structuredClone(TMAP) };
  return () => theatreBoard(rv, u, { pick: (p) => picks.push(p), act: () => {}, open: () => {}, hooks: { overlay: true, onFull } });
}

test('zoom, centre, the picked piece and an open area sheet are kept on the way in and on the way out', async () => {
  browser({ has: false });
  forgetFull();
  const picks = [];
  const asked = [];
  const u = { piece: { kind: 'force', name: 'The Norra Levy' }, theatre: { mode: 'map', scope: 'reports', frame: 'mainland', zoom: 2, centre: [40, 150], area: 'norra_plain' } };
  const draw = await board(u, (on) => asked.push(on), picks);
  const state = (el) => ({
    box: el.querySelector('svg.rl-tm-svg').getAttribute('viewBox'),
    picked: el.querySelectorAll('.rl-tm-mark[aria-pressed="true"]').map((m) => m.getAttribute('data-key')),
    sheet: el.querySelector('.rl-area-sheet')?.getAttribute('data-area') ?? null,
  });
  const before = inRoom(draw(), false);
  const was = state(before);
  assert.ok(was.picked.length === 1 && was.sheet === 'norra_plain', JSON.stringify(was));
  fullBtn(before).click();
  press(inRoom(draw(), true).querySelector('svg.rl-tm-svg'), 'f');
  assert.deepEqual(asked, [true, false]);
  assert.deepEqual(picks, [], 'going in and out changes nothing the room keeps');
  assert.deepEqual(state(inRoom(draw(), true)), was, 'in full screen');
  assert.deepEqual(state(inRoom(draw(), false)), was, 'and out of it');
  assert.ok(inRoom(draw(), true).querySelector('.rl-tm-stage .rl-area-sheet'), 'the area sheet is over the map');
});

test('after the control or F the keyboard is where it was: on the control, or on the map', async () => {
  browser({ has: false });
  forgetFull();
  let next = null;
  const room = document.createElement('div');
  room.className = 'realism-screen';
  document.body.replaceChildren(room);
  const redraw = (full) => { room.className = full ? 'realism-screen rl-full' : 'realism-screen'; next = view({ onFull: redraw }); room.replaceChildren(next); };
  redraw(false);
  fullBtn(next).click();
  await tick();
  assert.equal(document.activeElement, fullBtn(next), 'the new Full screen control has the focus');
  press(next.querySelector('svg.rl-tm-svg'), 'f');
  await tick();
  assert.equal(document.activeElement, next.querySelector('svg.rl-tm-svg'), 'F leaves the focus on the map');
  assert.ok(!room.classList.contains('rl-full'));
});

// --- Rule 5: a sheet in full screen opens over the map; Escape closes it first -----------------

test('Escape in full screen with an area sheet open closes the sheet and keeps full screen', () => {
  const closed = [];
  const asked = [];
  const v = inRoom(view({ area: 'norra_plain', onArea: (a) => closed.push(a), onFull: (on) => asked.push(on) }), true);
  assert.ok(v.querySelector('.rl-tm-stage .rl-area-sheet'), 'the sheet is drawn over the map');
  const ev = press(v.querySelector('.rl-area-sheet button'), 'Escape');
  assert.deepEqual(closed, [null], 'the sheet closes');
  assert.equal(ev.defaultPrevented, true, 'and the room does not leave full screen on the same press');
  assert.deepEqual(asked, []);
  const ev2 = press(v.querySelector('svg.rl-tm-svg'), 'Escape');
  assert.equal(ev2.defaultPrevented, true, 'from the map too, while the sheet is open');
});

test('Escape with a report\'s sheet open closes the report first', () => {
  const levy = {
    key: 'rLevy', kind: 'levy', kind_name: 'Levy', strength_low: 1, strength_high: 4, bound_for: null, ring: null,
    area: { key: 'sudland_coast', name: TMAP.areas.find((a) => a.key === 'sudland_coast').name },
    seen: '1900-04-10', source: 'air', person: 'Brann Hollis', confidence: 'B', document: 'DOC-2',
  };
  const shut = [];
  const v = inRoom(territoryView({ ...TMAP, reports: [levy] }, SHAPES, {
    px: DESK, frame: 'mainland', overlay: true, report: 'rLevy', today: '1900-04-12', onReport: (r) => shut.push(r),
  }), true);
  assert.ok(v.querySelector('.rl-tm-stage .rl-rp-sheet'), 'the report\'s sheet is over the map');
  const ev = press(v.querySelector('svg.rl-tm-svg'), 'Escape');
  assert.deepEqual(shut, [null]);
  assert.equal(ev.defaultPrevented, true);
});

test('the sheets and the chip float over the map, clear of the zoom', () => {
  assert.match(CSS_MAP, /\.rl-tm-stage\s*\{[^}]*position:\s*relative;[^}]*justify-content:\s*flex-end/);
  assert.match(CSS_MAP, /\.rl-tm-stage > :not\(\.rl-map-figure\):not\(\.rl-tm-corner\)\s*\{[^}]*z-index:\s*2/);
  assert.match(CSS_MAP, /\.rl-tm-corner\s*\{[^}]*z-index:\s*3/, 'the controls over the sheets');
  assert.match(CSS_MAP, /\.rl-tm-stage\s*\{[^}]*contain:\s*size;\s*overflow:\s*hidden/, 'what floats never makes the map taller than the room gives it');
});

test('the colours over the map are the theme\'s tokens', () => {
  const block = CSS_MAP.slice(CSS_MAP.indexOf('/* the map full screen'));
  assert.ok(block.length > 100, 'the block is there');
  assert.doesNotMatch(block, /#[0-9a-f]{3,8}\b|rgb\(|hsl\(/i);
});
