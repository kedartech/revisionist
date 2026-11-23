// Drag a piece to order it: pressing on one of the seat's own pieces and moving more than 8 px
// picks it up (it lifts, its lit areas show, the map does not pan); while it is held the lit area
// under it is marked and the map scrolls when it is held near the edge; dropped on a lit area it
// gives the chip a tap gives; dropped anywhere else, or on Escape, it slides back and nothing is
// drafted; a piece under way, an enemy report and a piece the seat does not command cannot be
// picked up; picking and dropping are the map's two hooks for a tap, `onSelect` and `onTarget`.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };

// The fake document does not bubble: a test sends each pointer event to the drawing and then to
// the document, as a page does. Inline style and animations are recorded on every element.
const docListeners = new Map();
Object.assign(document, {
  addEventListener(type, fn) { docListeners.set(type, [...(docListeners.get(type) ?? []), fn]); },
  removeEventListener(type, fn) { docListeners.set(type, (docListeners.get(type) ?? []).filter((f) => f !== fn)); },
  dispatchEvent(ev) { for (const fn of [...(docListeners.get(ev.type) ?? [])]) fn.call(document, ev); return !ev.defaultPrevented; },
});
const Element = document.createElement('x').constructor;
Object.defineProperty(Element.prototype, 'style', {
  configurable: true,
  get() {
    this._css ??= {};
    const css = this._css;
    return { setProperty: (k, v) => { css[k] = v; }, removeProperty: (k) => { delete css[k]; }, get transform() { return css.transform ?? ''; } };
  },
});
Element.prototype.animate = function animate(keyframes, how) { (this._anims ??= []).push({ keyframes, how }); };

const { territoryDrawing, forgetMarks } = await import('../js/views/realism-territory.js');
const { theatreBoard, forgetShapes } = await import('../js/views/realism-theatre.js');
const { boxOf, territoryProjection } = await import('../js/realism-rules.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const CSS_TEXT = readFileSync(new URL('../css/c-map.css', import.meta.url), 'utf8');
const TMAP = fixture.territory_map;
const PROJ = territoryProjection(SHAPES.coords, boxOf(SHAPES.box));
/** A map point ([lon, lat]) in the drawing's units. */
const proj = (xy) => PROJ.point(xy);
const PX = { width: 300, height: 200 };
const LEVY = 'The Norra Levy';
const KITES = 'The Norra Kites';
const HERALD = 'The Norra Herald';

/** A fake clock and animation-frame queue: `flush(ms)` runs one frame `ms` later. */
function clock() {
  let t = 0;
  let queue = [];
  return {
    now: () => t,
    frame: (cb) => { queue.push(cb); return queue.length; },
    flush(ms = 16) {
      t += ms;
      const run = queue;
      queue = [];
      for (const cb of run) cb(t);
      return run.length;
    },
    advance(ms) { t += ms; },
  };
}

const ev = (type, id, x, y, more = {}) => ({
  type, pointerId: id, clientX: x, clientY: y, button: 0, target: null, defaultPrevented: false,
  preventDefault() { this.defaultPrevented = true; }, stopPropagation() {}, ...more,
});

/** The toy map with the levy alone on the plain (the kites and the herald moved to the hills), changed by `change`. */
function toyMap(change = () => {}) {
  const map = structuredClone(TMAP);
  for (const m of map.marks) {
    if (m.name !== LEVY && m.piece) m.piece.area = { key: 'norra_hills', name: 'The Norra Hills', place: null };
  }
  change(map);
  return map;
}

/** The lit areas of piece `name` on `map`, as the room hands them to the map. */
function litOf(map, name) {
  const m = map.marks.find((x) => x.name === name);
  return (m?.piece?.moves ?? []).map((mv) => {
    const [lon, lat] = SHAPES.areas[mv.area.key].label;
    return { place: { name: mv.area.name, lon, lat }, value: mv.area.key, area: mv.area.key, days: '2 days', chosen: false, lock: null };
  });
}

/**
 * A small room around one territory drawing, as the theatre does it: a pick redraws the map with
 * the piece selected and its lit areas, and a view told redraws it at that view. `got` records
 * what the map told the room.
 */
function board(map, { zoom = 1, centre = null, selected = null, lit = litOf, fanned = null, reduced = false } = {}) {
  const c = clock();
  globalThis.matchMedia = (q) => ({ matches: reduced && q.includes('reduce') });
  forgetMarks();
  const figure = document.createElement('figure');
  document.body.append(figure);
  const got = { selects: [], targets: [], views: [], live: 0, draws: 0 };
  const r = { c, got, figure, pic: null, sel: selected, view: { zoom, centre } };
  r.draw = () => {
    got.draws += 1;
    r.pic = territoryDrawing(map, SHAPES, {
      px: PX, zoom: r.view.zoom, centre: r.view.centre, selected: r.sel, fanned, now: c.now, frame: c.frame,
      targets: r.sel ? lit(map, r.sel) : [],
      onSelect: (name) => { got.selects.push(name); r.sel = name; r.draw(); },
      onTarget: (value) => { got.targets.push(value); },
      onView: (v) => { got.views.push(v); r.view = v; r.draw(); },
    });
    figure.replaceChildren(r.pic);
  };
  r.draw();
  /** A pointer event as a page delivers it: to the drawing now under the finger, then the document. */
  r.send = (type, x, y, more = {}) => {
    const e = ev(type, 1, x, y, { target: r.pic, ...more });
    if (type === 'pointerdown') r.down = true;
    if (type === 'pointerup' || type === 'pointercancel') r.down = false;
    r.at = [x, y];
    r.pic.dispatchEvent(e);
    document.dispatchEvent(e);
    return e;
  };
  r.done = () => { figure.remove(); globalThis.matchMedia = undefined; };
  return r;
}

/** Where point `[ux, uy]` (the drawing's units) is on screen, in the drawing as it now is. */
function screenOf(pic, [ux, uy]) {
  const [x, y, w, h] = pic.getAttribute('viewBox').split(' ').map(Number);
  const k = Number(pic.getAttribute('data-k'));
  return [(ux - x) / k + (PX.width - w / k) / 2, (uy - y) / k + (PX.height - h / k) / 2];
}

const pxAt = (g) => [Number(g.getAttribute('data-x')), Number(g.getAttribute('data-y'))];
// while the view moves the marks and lit areas ride in a layer of their own beside the drawing
const layerOf = (pic) => (pic.parentNode && pic.parentNode.querySelector('svg.rl-tm-live')) || pic;
const markOf = (pic, name) => layerOf(pic).querySelectorAll('g.rl-tm-mark').find((g) => g.getAttribute('aria-label')?.startsWith(`${name}:`));
const targetOf = (pic, key) => layerOf(pic).querySelectorAll('g.rl-map-target').find((g) => g.getAttribute('data-area') === key);
const areaOf = (pic, key) => pic.querySelectorAll('path.rl-area').find((p) => p.getAttribute('data-area') === key);
/** The screen point of a piece's glyph: its area's label point, lifted as the drawing lifts it. */
const pieceAt = (pic, name) => {
  const [x, y] = screenOf(pic, pxAt(markOf(pic, name)));
  return [x, y - 50];
};
const lifted = (pic, name) => markOf(pic, name)?.classList.contains('rl-tm-lifted') ?? false;
const shift = (pic, name) => markOf(pic, name)?.parentNode._css?.transform ?? '';

/** Press on piece `name` and move by (dx, dy) in steps of 4 px, a frame between each. */
function pressAndMove(r, name, dx, dy) {
  const [x, y] = pieceAt(r.pic, name);
  r.send('pointerdown', x, y, { target: markOf(r.pic, name).querySelector('rect') });
  const steps = Math.max(Math.ceil(Math.hypot(dx, dy) / 4), 1);
  for (let i = 1; i <= steps; i += 1) {
    r.c.advance(16);
    r.send('pointermove', x + (dx * i) / steps, y + (dy * i) / steps);
    r.c.flush(0);
  }
  return [x + dx, y + dy];
}

/** Carry piece `name` to the screen point `[tx, ty]`: picked up first unless the finger is already down. */
function carryTo(r, name, [tx, ty]) {
  if (!r.down) pressAndMove(r, name, 10, 0);
  const [x, y] = r.at;
  for (let i = 1; i <= 10; i += 1) {
    r.c.advance(16);
    r.send('pointermove', x + ((tx - x) * i) / 10, y + ((ty - y) * i) / 10);
    r.c.flush(16);
  }
}

// --- Rule 1: a press on an own piece that moves more than 8 px picks it up ------------------

test('pressing on an own piece and moving more than 8 px picks it up: it lifts, its lit areas show, the map does not pan', () => {
  const r = board(toyMap(), { zoom: 2, centre: [150, 50] });
  const before = r.pic.getAttribute('viewBox');
  const [x, y] = pressAndMove(r, LEVY, 7, 0);
  assert.deepEqual(r.got.selects, [], 'under 8 px: not yet picked up');
  r.c.advance(16);
  r.send('pointermove', x + 5, y);
  r.c.flush(16);
  assert.deepEqual(r.got.selects, [LEVY], 'picked through the map\'s own hook');
  assert.ok(r.pic.querySelectorAll('g.rl-map-target').length > 0, 'its lit areas show');
  assert.ok(lifted(r.pic, LEVY), 'it lifts');
  for (let i = 0; i < 5; i += 1) {
    r.c.advance(16);
    r.send('pointermove', 100 + i * 10, 100);
    r.c.flush(16);
  }
  assert.equal(r.pic.getAttribute('viewBox'), before, 'the map has not moved');
  assert.equal(r.pic.style.transform, '', 'the land has not moved either');
  assert.deepEqual(r.got.views, [], 'no view told');
  assert.match(shift(r.pic, LEVY), /^translate\(/, 'the piece follows the finger');
  r.send('pointerup', 140, 100);
  r.done();
});

test('the held piece follows the finger in the drawing\'s units, wherever it is held', () => {
  const r = board(toyMap(), { zoom: 2, centre: [150, 50] });
  const [x, y] = pieceAt(r.pic, LEVY);
  pressAndMove(r, LEVY, 10, 0);
  r.c.advance(16);
  r.send('pointermove', x + 30, y + 20);
  r.c.flush(16);
  const k = Number(r.pic.getAttribute('data-k'));
  const [, dx, dy] = shift(r.pic, LEVY).match(/translate\(([-\d.]+)px, ([-\d.]+)px\)/).map(Number);
  assert.ok(Math.abs(dx - 30 * k) < 0.05 && Math.abs(dy - 20 * k) < 0.05, `moved ${dx}, ${dy} units for 30, 20 px at ${k} a px`);
  const over = layerOf(r.pic).querySelector('g.rl-tm-over');
  assert.equal(over.childNodes.at(-1), markOf(r.pic, LEVY).parentNode, 'drawn over the lit rings and every other mark');
  r.send('pointerup', x + 30, y + 20);
  r.done();
});

test('a piece already picked is picked up without being picked again', () => {
  const r = board(toyMap(), { selected: LEVY, zoom: 2, centre: [150, 50] });
  const draws = r.got.draws;
  const before = r.pic.getAttribute('viewBox');
  const [x, y] = pressAndMove(r, LEVY, 12, 0);
  assert.deepEqual(r.got.selects, []);
  assert.equal(r.got.draws, draws, 'not drawn again');
  assert.ok(lifted(r.pic, LEVY));
  // the same drawing goes on carrying it: the map does not pan under it
  for (let i = 1; i <= 4; i += 1) { r.c.advance(16); r.send('pointermove', x - i * 10, y + i * 5); r.c.flush(16); }
  assert.equal(r.pic.style.transform, '', 'the land has not moved');
  assert.equal(r.pic.getAttribute('viewBox'), before);
  r.send('pointerup', x - 40, y + 20);
  for (let i = 0; i < 100 && r.c.flush(16); i += 1);
  assert.equal(r.pic.getAttribute('viewBox'), before, 'nor after the lift');
  assert.deepEqual(r.got.views, []);
  r.done();
});

// --- Rule 2: the lit area under it is marked; the edge scrolls ---------------------------------

test('while it is held, the area under it is marked when it is lit, and only then', () => {
  const r = board(toyMap());
  const [x, y] = pieceAt(r.pic, LEVY);
  pressAndMove(r, LEVY, 12, 0);
  const isle = screenOf(r.pic, pxAt(targetOf(r.pic, 'isle')));
  carryTo(r, LEVY, isle);
  assert.equal(targetOf(r.pic, 'isle').classList.contains('under'), true, 'the lit place is marked');
  assert.equal(areaOf(r.pic, 'isle').classList.contains('rl-drop-over'), true, 'and its area');
  assert.equal(r.pic.querySelectorAll('.rl-drop-over').length, 1, 'and no other area');
  assert.equal(layerOf(r.pic).querySelectorAll('.under').length, 1, 'nor any other lit place');
  const hills = screenOf(r.pic, proj(SHAPES.areas.norra_hills.label));
  r.c.advance(16);
  r.send('pointermove', ...hills);
  r.c.flush(16);
  assert.equal(r.pic.querySelectorAll('.under').length, 0, 'the hills are not lit: nothing marked');
  assert.equal(r.pic.querySelectorAll('.rl-drop-over').length, 0);
  assert.equal(areaOf(r.pic, 'norra_hills').classList.contains('rl-drop-over'), false);
  r.send('pointerup', x, y);
  assert.equal(r.pic.querySelectorAll('.under').length + r.pic.querySelectorAll('.rl-drop-over').length, 0, 'the marks go with the drop');
  r.done();
});

test('held near the edge of the map, the map scrolls that way, and the view is told once, at the drop', () => {
  const r = board(toyMap(), { zoom: 2, centre: [150, 50] });
  const x0 = Number(r.pic.getAttribute('viewBox').split(' ')[0]);
  pressAndMove(r, LEVY, 12, 0);
  const [, y] = pieceAt(r.pic, LEVY);
  r.c.advance(16);
  r.send('pointermove', PX.width - 4, y);
  for (let i = 0; i < 20; i += 1) r.c.flush(16);
  assert.deepEqual(r.got.views, [], 'not told while the piece is held');
  r.send('pointerup', PX.width - 4, y);
  assert.equal(r.got.views.length, 1, 'told once, at the drop');
  const x1 = Number(r.pic.getAttribute('viewBox').split(' ')[0]);
  assert.ok(x1 > x0 + 1, `the view moved right: ${x0} to ${x1}`);
  r.done();
});

test('away from the edge the map holds still while the piece is carried', () => {
  const r = board(toyMap(), { zoom: 2, centre: [150, 50] });
  pressAndMove(r, LEVY, 12, 0);
  r.c.advance(16);
  r.send('pointermove', 150, 100);
  for (let i = 0; i < 10; i += 1) r.c.flush(16);
  r.send('pointerup', 150, 100);
  assert.deepEqual(r.got.views, []);
  r.done();
});

// --- Rule 3: dropped on a lit area, the chip a tap gives -----------------------------------------

test('dropped on a lit area it is that area\'s target, through the same hook a tap uses', () => {
  const r = board(toyMap());
  pressAndMove(r, LEVY, 12, 0);
  const isle = screenOf(r.pic, pxAt(targetOf(r.pic, 'isle')));
  carryTo(r, LEVY, isle);
  r.send('pointerup', ...isle);
  assert.deepEqual(r.got.targets, ['isle'], 'the lit area under it');
  assert.equal(shift(r.pic, LEVY), '', 'the piece is back in its place on the board');
  assert.equal(lifted(r.pic, LEVY), false);
  // a tap on the same lit place gives the same value
  targetOf(r.pic, 'isle').click();
  assert.deepEqual(r.got.targets, ['isle', 'isle']);
  r.done();
});

test('a drop anywhere in a lit area counts, not only on its ring', () => {
  const r = board(toyMap());
  pressAndMove(r, LEVY, 12, 0);
  // the Sudland Coast holds map point (85, 15); its label is elsewhere
  const at = screenOf(r.pic, proj([85, 15]));
  const coast = screenOf(r.pic, pxAt(targetOf(r.pic, 'sudland_coast')));
  assert.ok(Math.hypot(at[0] - coast[0], at[1] - coast[1]) > 22, 'away from the ring');
  carryTo(r, LEVY, at);
  r.send('pointerup', ...at);
  assert.deepEqual(r.got.targets, ['sudland_coast']);
  r.done();
});

test('the click that ends a carry is not passed on to what lies under the finger', () => {
  const r = board(toyMap());
  pressAndMove(r, LEVY, 12, 0);
  const isle = screenOf(r.pic, pxAt(targetOf(r.pic, 'isle')));
  carryTo(r, LEVY, isle);
  r.send('pointerup', ...isle);
  const click = ev('click', 1, ...isle);
  document.dispatchEvent(click);
  assert.equal(click.defaultPrevented, true, 'the click after the drop is swallowed');
  const next = ev('click', 1, ...isle);
  document.dispatchEvent(next);
  assert.equal(next.defaultPrevented, false, 'and only that one');
  r.done();
});

// --- Rule 4: anywhere else, or Escape: it slides back, nothing drafted ---------------------------

test('dropped on an area that is not lit, it slides back and nothing is drafted', () => {
  const r = board(toyMap());
  pressAndMove(r, LEVY, 12, 0);
  const hills = screenOf(r.pic, proj(SHAPES.areas.norra_hills.label));
  carryTo(r, LEVY, hills);
  const wrap = markOf(r.pic, LEVY).parentNode;
  const was = shift(r.pic, LEVY);
  assert.match(was, /^translate\(/);
  r.send('pointerup', ...hills);
  assert.deepEqual(r.got.targets, [], 'nothing drafted');
  assert.equal(shift(r.pic, LEVY), '', 'back in its place');
  assert.equal(lifted(r.pic, LEVY), false);
  assert.equal(wrap._anims?.length, 1, 'it slides back');
  assert.equal(wrap._anims[0].keyframes[0].transform, was, 'from where it was dropped');
  assert.equal(wrap._anims[0].keyframes.at(-1).transform, 'translate(0px, 0px)');
  r.done();
});

test('dropped off the map, it slides back and nothing is drafted, whatever lit area lies beyond the edge', () => {
  const r = board(toyMap(), { zoom: 2, centre: [150, 50] });
  pressAndMove(r, LEVY, 12, 0);
  // below the drawing, where the Sudland Coast would be drawn if the map went on
  const off = [30, PX.height + 30];
  const k = Number(r.pic.getAttribute('data-k'));
  const [x0, y0] = r.pic.getAttribute('viewBox').split(' ').map(Number);
  assert.equal(PROJ.invert([x0 + off[0] * k, y0 + off[1] * k]).every((v) => v > 0 && v < 100), true, 'over the lit coast');
  r.send('pointermove', ...off);
  r.send('pointerup', ...off);
  assert.deepEqual(r.got.targets, []);
  assert.equal(shift(r.pic, LEVY), '');
  r.done();
});

test('a lit area under something that covers the map (a sheet) is neither marked nor dropped on', () => {
  const r = board(toyMap());
  pressAndMove(r, LEVY, 12, 0);
  const isle = screenOf(r.pic, pxAt(targetOf(r.pic, 'isle')));
  const sheet = document.createElement('section');
  document.body.append(sheet);
  document.elementFromPoint = (x, y) => (Math.hypot(x - isle[0], y - isle[1]) < 30 ? sheet : r.pic);
  try {
    carryTo(r, LEVY, isle);
    assert.equal(targetOf(r.pic, 'isle').classList.contains('under'), false, 'not marked');
    r.send('pointerup', ...isle);
    assert.deepEqual(r.got.targets, [], 'nothing drafted');
    assert.equal(shift(r.pic, LEVY), '');
  } finally {
    delete document.elementFromPoint;
    sheet.remove();
    r.done();
  }
});

test('Escape while it is held: it slides back, nothing is drafted, and the lift that follows is no drop', () => {
  const r = board(toyMap());
  pressAndMove(r, LEVY, 12, 0);
  const isle = screenOf(r.pic, pxAt(targetOf(r.pic, 'isle')));
  carryTo(r, LEVY, isle);
  const esc = {
    type: 'keydown', key: 'Escape', target: r.pic, defaultPrevented: false, stopped: false,
    preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; },
  };
  document.dispatchEvent(esc);
  assert.equal(esc.defaultPrevented, true);
  assert.equal(esc.stopped, true, 'the Escape is the carry\'s alone: a sheet open over the map stays open');
  assert.equal(shift(r.pic, LEVY), '');
  assert.equal(markOf(r.pic, LEVY).parentNode._anims?.length, 1, 'it slides back');
  r.send('pointerup', ...isle);
  assert.deepEqual(r.got.targets, [], 'nothing drafted');
  r.done();
});

test('a new press of the pointer whose lift never came puts the piece back, and the map answers it', () => {
  const r = board(toyMap(), { zoom: 2, centre: [150, 50] });
  pressAndMove(r, LEVY, 12, 0);
  // no pointerup: the page lost it; the next press is the same pointer
  const before = r.pic.getAttribute('viewBox');
  r.send('pointerdown', 150, 150, { target: r.pic });
  assert.equal(shift(r.pic, LEVY), '', 'the piece is back in its place');
  for (let i = 1; i <= 4; i += 1) { r.c.advance(16); r.send('pointermove', 150 + i * 10, 150); r.c.flush(16); }
  r.send('pointerup', 190, 150);
  for (let i = 0; i < 100 && r.c.flush(16); i += 1);
  assert.notEqual(r.pic.getAttribute('viewBox'), before, 'the press pans the map');
  assert.deepEqual(r.got.targets, []);
  r.done();
});

test('with reduced motion set it goes back at once, with no slide', () => {
  const r = board(toyMap(), { reduced: true });
  pressAndMove(r, LEVY, 12, 0);
  const hills = screenOf(r.pic, proj(SHAPES.areas.norra_hills.label));
  carryTo(r, LEVY, hills);
  r.send('pointerup', ...hills);
  assert.equal(shift(r.pic, LEVY), '');
  assert.equal(markOf(r.pic, LEVY).parentNode._anims, undefined, 'no slide');
  assert.deepEqual(r.got.targets, []);
  r.done();
});

// --- Rule 5: what cannot be picked up --------------------------------------------------------------

/** Press on `el` at its screen point and move 30 px: whether it was picked up, and whether the map panned. */
function tryDrag(r, el, at) {
  const before = r.pic.getAttribute('viewBox');
  const live = [];
  r.send('pointerdown', ...at, { target: el });
  for (let i = 1; i <= 6; i += 1) {
    r.c.advance(16);
    r.send('pointermove', at[0] + i * 5, at[1]);
    r.c.flush(16);
    live.push(r.pic.style.transform);
  }
  r.send('pointerup', at[0] + 30, at[1]);
  for (let i = 0; i < 100 && r.c.flush(16); i += 1);
  return { picked: r.got.selects.length > 0, panned: live.some(Boolean) || r.pic.getAttribute('viewBox') !== before };
}

test('a piece under way cannot be picked up: the press pans the map', () => {
  const map = toyMap((m) => { m.marks.find((x) => x.name === LEVY).piece.under_way = { path: [{ key: 'isle', name: 'The Isle' }], arrives: '1900-04-09' }; });
  const r = board(map, { zoom: 2, centre: [150, 50] });
  const got = tryDrag(r, markOf(r.pic, LEVY).querySelector('rect'), pieceAt(r.pic, LEVY));
  assert.deepEqual(got, { picked: false, panned: true });
  r.done();
});

test('a piece the seat does not command cannot be picked up', () => {
  // an own-side mark the seat's forms do not name has no piece
  const map = toyMap((m) => { const x = m.marks.find((k) => k.name === LEVY); x.piece = null; x.places = [{ name: 'Norra', lat: 150, lon: 150, theatre: null }]; });
  const r = board(map, { zoom: 2, centre: [150, 50] });
  const el = markOf(r.pic, LEVY);
  assert.ok(el, 'drawn');
  const got = tryDrag(r, el.querySelector('rect'), screenOf(r.pic, pxAt(el)));
  assert.deepEqual(got, { picked: false, panned: true });
  r.done();
});

test('an enemy report cannot be picked up', () => {
  const enemy = {
    key: 'm-sud', name: 'Sudland Levy', kind: 'army', side: 'other', side_name: 'Sudland', certainty: 'reported',
    places: [{ name: 'Sudby', lat: 40, lon: 60, theatre: null }], area: { key: 'sudland_coast', name: 'The Sudland Coast' },
    reported: '1900-04-01', source: 'Ilse', document: 'd-1', strength: 3, piece: null,
  };
  const r = board(toyMap((m) => m.marks.push(enemy)), { zoom: 2, centre: [100, 80] });
  const el = markOf(r.pic, 'Sudland Levy');
  assert.ok(el, 'the report is drawn');
  const got = tryDrag(r, el.querySelector('rect'), screenOf(r.pic, pxAt(el)));
  assert.deepEqual(got, { picked: false, panned: true });
  r.done();
});

test('a closed stack is not a piece: a press on it pans the map', () => {
  const r = board(structuredClone(TMAP), { zoom: 2, centre: [150, 50] });
  const stack = r.pic.querySelector('g.rl-tm-stack');
  assert.ok(stack);
  const base = stack.querySelector('g.rl-tm-stack-base');
  const got = tryDrag(r, base.querySelector('rect'), screenOf(r.pic, pxAt(base)));
  assert.deepEqual(got, { picked: false, panned: true });
  r.done();
});

test('a piece fanned out of its stack can be picked up', () => {
  const r = board(structuredClone(TMAP), { fanned: 'norra_plain' });
  pressAndMove(r, KITES, 12, 0);
  assert.deepEqual(r.got.selects, [KITES]);
  r.send('pointerup', 0, 0);
  r.done();
});

test('a drawing for show only offers nothing to pick up', () => {
  const pic = territoryDrawing(toyMap(), SHAPES, { px: PX, still: true });
  assert.equal(pic.querySelectorAll('[data-grab]').length, 0);
});

// --- Rule 6, and the paths that stay -------------------------------------------------------------

test('a tap on a piece still picks it, and a tap on a lit area still chooses it', () => {
  const r = board(toyMap());
  const [x, y] = pieceAt(r.pic, LEVY);
  r.send('pointerdown', x, y, { target: markOf(r.pic, LEVY).querySelector('rect') });
  r.c.advance(50);
  r.send('pointermove', x + 2, y);
  r.send('pointerup', x + 2, y);
  markOf(r.pic, LEVY).click();
  assert.deepEqual(r.got.selects, [LEVY]);
  assert.equal(lifted(r.pic, LEVY), false, 'a tap does not lift it');
  targetOf(r.pic, 'isle').click();
  assert.deepEqual(r.got.targets, ['isle']);
  r.done();
});

test('the arrow keys and Enter still pick and put down a piece', () => {
  const r = board(toyMap(), { selected: LEVY });
  const mark = markOf(r.pic, LEVY);
  mark.dispatchEvent({ type: 'keydown', key: 'ArrowRight', preventDefault() {}, stopPropagation() {} });
  const t = document.activeElement;
  assert.ok(t.classList.contains('rl-map-target'));
  t.dispatchEvent({ type: 'keydown', key: 'Enter', preventDefault() {}, stopPropagation() {} });
  assert.equal(r.got.targets.length, 1);
  r.done();
});

test('a locked move is lit with its lock while a piece is carried, and a drop there gives its chip', () => {
  const lockedLit = (map, name) => litOf(map, name).map((t) => (t.area === 'isle' ? { ...t, lock: 'Ilse' } : t));
  const r = board(toyMap(), { lit: lockedLit });
  pressAndMove(r, LEVY, 12, 0);
  const isle = targetOf(r.pic, 'isle');
  assert.ok(isle.classList.contains('locked'));
  assert.ok(isle.querySelector('.rl-tm-lock'), 'its padlock');
  const at = screenOf(r.pic, pxAt(isle));
  carryTo(r, LEVY, at);
  r.send('pointerup', ...at);
  assert.deepEqual(r.got.targets, ['isle']);
  r.done();
});

test('the piece held is drawn lifted and lets the pointer through; the marked area is drawn from the tokens', () => {
  assert.match(CSS_TEXT, /\.rl-tm-lifted \{[^}]*pointer-events: none/);
  assert.match(CSS_TEXT, /\.rl-map-target\.under \.rl-target-ring \{[^}]*var\(--/);
  assert.match(CSS_TEXT, /\.rl-area\.rl-drop-over \{[^}]*var\(--/);
});

// --- In the room: the theatre's own hooks, the chip, and no order without the confirm ----------

const MOVE = {
  name: 'move_piece', label: 'Move a piece', summary: 'Send a piece to another area.', pipeline: 'field_order',
  params: [
    { name: 'force', label: 'Which piece', kind: 'enum', lo: null, hi: null, places: [], choices: [
      { value: 'norra_levy', label: LEVY }, { value: 'norra_kites', label: KITES }, { value: 'norra_herald', label: HERALD }] },
    { name: 'to', label: 'To', kind: 'enum', lo: null, hi: null, places: [], choices: [
      { value: 'isle', label: 'The Isle' }, { value: 'sudland_coast', label: 'The Sudland Coast' },
      { value: 'the_gulf', label: 'The Gulf' }, { value: 'open_sea', label: 'The Open Sea' }] },
  ],
};

/** The theatre's board around the toy map, redrawn on every pick as the room does. */
async function room() {
  globalThis.matchMedia = () => ({ matches: false });
  // a phone's window, so that the room's drawing is guessed at the tests' 300 by 200 px
  globalThis.innerWidth = PX.width + 24;
  globalThis.innerHeight = PX.height * 2;
  const map = toyMap();
  const rv = {
    ...fixture, map, desk: { ...fixture.desk, levers: [MOVE] },
    court: { load_limit: 2, ring: [], chambers: [], paths: [] },
    clock: { ...fixture.clock, world_date: '1900-04-02' }, orders: { orders: [] },
  };
  const ui = { piece: null, theatre: { mode: 'map', scope: 'reports' } };
  const acts = [];
  const was = globalThis.fetch;
  globalThis.fetch = async (url) => ({ ok: true, status: 200, json: async () => (url === '/api/realism/map' ? { reply: '', refused: false, file: TMAP.file, map: SHAPES } : {}) });
  const r = {
    ui, acts, view: null,
    draw() {
      r.view?.remove();
      r.view = theatreBoard(rv, ui, {
        pick: (p) => { if (p.theatre) ui.theatre = p.theatre; if (p.piece !== undefined) ui.piece = p.piece; r.draw(); },
        act: (message, action, body) => { acts.push({ message, action, body }); },
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
  r.pic = () => r.view.querySelector('svg.rl-tm-svg');
  r.send = (type, x, y, more = {}) => {
    const e = ev(type, 1, x, y, { target: r.pic(), ...more });
    r.pic().dispatchEvent(e);
    document.dispatchEvent(e);
  };
  return r;
}

test('in the room: a drag picks the piece, lights its moves, and a drop on one opens the confirm chip; nothing is filed until Send it', async () => {
  const r = await room();
  const [x, y] = pieceAt(r.pic(), LEVY);
  r.send('pointerdown', x, y, { target: markOf(r.pic(), LEVY).querySelector('rect') });
  r.send('pointermove', x + 12, y);
  assert.equal(r.ui.piece?.name, LEVY, 'picked through the room\'s own pick');
  assert.ok(r.pic().querySelectorAll('g.rl-map-target').length >= 2, 'its moves are lit in the drawing the room drew');
  const isle = screenOf(r.pic(), pxAt(targetOf(r.pic(), 'isle')));
  r.send('pointermove', ...isle);
  assert.ok(targetOf(r.pic(), 'isle').classList.contains('under'), 'the new drawing marks the lit area under it');
  assert.ok(lifted(r.pic(), LEVY), 'and holds the piece lifted');
  r.send('pointerup', ...isle);
  const chip = r.view.querySelector('.rl-pup-chip');
  assert.ok(chip, 'the confirm chip');
  assert.match(words(chip), /The Isle/);
  assert.deepEqual(r.acts, [], 'nothing filed by the drop');
  chip.querySelectorAll('button').find((b) => words(b) === 'Send it').click();
  assert.equal(r.acts.length, 1, 'filed only by the confirm');
  assert.equal(r.acts[0].action, 'lever');
  assert.deepEqual(r.acts[0].body.params, { force: 'norra_levy', to: 'isle' });
  r.view.remove();
  globalThis.matchMedia = undefined;
});

test('in the room: a drop on an area that is not lit drafts nothing and opens no chip', async () => {
  const r = await room();
  const [x, y] = pieceAt(r.pic(), LEVY);
  r.send('pointerdown', x, y, { target: markOf(r.pic(), LEVY).querySelector('rect') });
  r.send('pointermove', x + 12, y);
  const hills = screenOf(r.pic(), proj(SHAPES.areas.norra_hills.label));
  r.send('pointermove', ...hills);
  r.send('pointerup', ...hills);
  assert.equal(r.view.querySelector('.rl-pup-chip'), null);
  assert.deepEqual(r.acts, []);
  assert.equal(r.ui.theatre.goal ?? null, null);
  r.view.remove();
  globalThis.matchMedia = undefined;
});
