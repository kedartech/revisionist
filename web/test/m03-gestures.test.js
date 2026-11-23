// The map follows the finger: a drag moves the view in every frame, a release keeps it moving
// and slows it to a stop inside its frame, a pinch, the wheel and the plus and minus keys zoom
// smoothly between 1 and 8 around the point under them, labels are recomputed at most ten times
// a second during a gesture, a tap is a press that moves less than 8 px and lifts within
// 300 ms, the view is told when a gesture ends, and the arrow keys pan.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { gestures } = await import('../js/map/gestures.js');
const view = await import('../js/map/view.js');
const { territoryDrawing } = await import('../js/views/realism-territory.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const CSS_TEXT = readFileSync(new URL('../css/c-map.css', import.meta.url), 'utf8');
const TMAP = fixture.territory_map;

/** A frame of 300 by 200 units drawn into 300 by 200 px: one unit a pixel at zoom 1. */
const RECT = { x: 0, y: 0, w: 300, h: 200 };
const PX = { width: 300, height: 200 };

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
    /** Frames until nothing more is asked for (at most `max`). */
    settle(max = 400, ms = 16) {
      let n = 0;
      while (n < max && this.flush(ms)) n += 1;
      return n;
    },
    advance(ms) { t += ms; },
  };
}

const ev = (type, id, x, y, more = {}) => ({
  type, pointerId: id, clientX: x, clientY: y, target: null, defaultPrevented: false,
  preventDefault() { this.defaultPrevented = true; }, stopPropagation() {}, ...more,
});

/** A map root with gestures on it, recording what it is told. */
function rig(opts = {}) {
  const c = clock();
  const root = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  const live = [];
  const views = [];
  const taps = [];
  gestures(root, RECT, {
    zoom: 2, centre: [150, 100], now: c.now, frame: c.frame, reduced: false,
    onLive: (win, how) => live.push({ win, ...how }),
    onView: (v) => views.push(v),
    onTap: (xy) => taps.push(xy),
    ...opts,
  }, PX);
  const fire = (type, id, x, y, more) => root.dispatchEvent(ev(type, id, x, y, { target: root, ...more }));
  return { c, root, live, views, taps, fire };
}

const near = (a, b, eps = 1e-6) => Math.abs(a - b) < eps;

// --- Rule 1: the map moves with the finger in every frame, at every zoom --------------------

test('a drag moves the view with the finger in each frame, before the finger lifts', () => {
  for (const zoom of [2, 3.5, 8]) {
    const { c, live, views, fire } = rig({ zoom, centre: [150, 100] });
    const k = view.unitsPerPx(view.viewWindow(RECT, zoom, [150, 100]), PX);
    const x0 = view.viewWindow(RECT, zoom, [150, 100]).x;
    fire('pointerdown', 1, 150, 100);
    for (const dx of [-10, -20, -30]) {
      c.advance(16);
      fire('pointermove', 1, 150 + dx, 100);
      c.flush(0);
      assert.ok(live.length, `zoom ${zoom}: drawn before the finger lifts`);
      assert.ok(near(live.at(-1).win.x, x0 - dx * k), `zoom ${zoom}: moved ${dx} px, shown ${-dx * k} units on`);
    }
    assert.equal(views.length, 0, 'nothing told to the room until the gesture ends');
  }
});

test('the pointer moves of one frame are drawn once, in that frame', () => {
  const { c, live, fire } = rig();
  fire('pointerdown', 1, 150, 100);
  fire('pointermove', 1, 130, 100);
  fire('pointermove', 1, 120, 100);
  fire('pointermove', 1, 110, 100);
  assert.equal(c.flush(16), 1, 'one frame asked for');
  assert.equal(live.length, 1);
});

test('at zoom 1 the whole frame shows: a drag only gives a little at the edge, then comes back', () => {
  const { c, live, views, fire } = rig({ zoom: 1 });
  fire('pointerdown', 1, 150, 100);
  c.advance(20);
  fire('pointermove', 1, 300, 100);
  c.flush(0);
  const given = live.at(-1).win.x;
  assert.ok(given < 0 && given > -view.GIVE_PX, `gave ${given} units, under ${view.GIVE_PX}`);
  c.advance(400);
  fire('pointerup', 1, 300, 100);
  c.settle();
  assert.equal(live.at(-1).win.x, 0, 'back inside the frame');
  assert.deepEqual(views.at(-1), { zoom: 1, centre: [150, 100] });
});

// --- Rule 2: momentum, a stop inside the frame, a little give ------------------------------

/** A quick fling to the left: three moves of 30 px, 16 ms apart, then the lift. */
function fling(r, dx = -30) {
  r.fire('pointerdown', 1, 150, 100);
  for (let i = 1; i <= 3; i += 1) {
    r.c.advance(16);
    r.fire('pointermove', 1, 150 + dx * i, 100);
    r.c.flush(0);
  }
  r.c.advance(16);
  r.fire('pointerup', 1, 150 + dx * 3, 100);
}

test('on release the map keeps moving the way it was flung, slows and stops', () => {
  const r = rig({ zoom: 4, centre: [100, 100] });
  fling(r);
  const atLift = r.live.at(-1).win.x;
  assert.equal(r.views.length, 0, 'still moving: not told yet');
  const frames = r.c.settle();
  assert.ok(frames > 3, `kept moving for ${frames} frames`);
  const xs = r.live.map((l) => l.win.x);
  const after = xs.slice(xs.indexOf(atLift));
  const steps = after.slice(1).map((x, i) => x - after[i]);
  assert.ok(steps[0] > 0, 'on in the fling\'s direction');
  assert.ok(steps.at(-1) < steps[0], 'slowing');
  assert.ok(after.at(-1) > atLift + 10, 'carried well past where the finger lifted');
  assert.equal(r.views.length, 1, 'told once, when it stops');
  assert.equal(r.live.at(-1).end, true);
});

test('a fling never leaves the frame: it gives a little at the edge and comes back to it', () => {
  const r = rig({ zoom: 2, centre: [200, 100] });
  fling(r, -60);
  r.c.settle();
  const win = view.viewWindow(RECT, 2, [1e9, 100]);
  const most = Math.max(...r.live.map((l) => l.win.x));
  assert.ok(most > win.x, 'past the edge for a moment');
  assert.ok(most <= win.x + view.GIVE_PX * view.unitsPerPx(win, PX) + 1e-9, 'by no more than the give');
  assert.equal(r.live.at(-1).win.x, win.x, 'and stops on the edge');
  assert.deepEqual(r.views.at(-1).centre, [win.x + win.w / 2, 100]);
});

test('with reduced motion set the map stops where the finger lifts', () => {
  const r = rig({ zoom: 4, centre: [100, 100], reduced: true });
  fling(r);
  const atLift = r.live.at(-1).win.x;
  r.c.settle();
  assert.equal(r.live.at(-1).win.x, atLift, 'no momentum');
  assert.equal(r.views.length, 1, 'told at once');
});

test('a press during the slide catches the map where it is', () => {
  const r = rig({ zoom: 4, centre: [100, 100] });
  fling(r);
  r.c.flush(16);
  r.c.flush(16);
  const caught = r.live.at(-1).win.x;
  r.fire('pointerdown', 1, 150, 100);
  r.c.settle();
  assert.equal(r.live.at(-1).win.x, caught);
  assert.equal(r.views.length, 0, 'the gesture goes on under the finger');
});

// --- Rule 3: smooth zoom between 1 and 8 around the point under it ----------------------------

/** Where unit point `u` is drawn in window `win`, in px of PX. */
const screenOf = (win, [ux, uy]) => {
  const k = view.unitsPerPx(win, PX);
  return [(ux - win.x) / k + (PX.width - win.w / k) / 2, (uy - win.y) / k + (PX.height - win.h / k) / 2];
};

test('a pinch zooms smoothly with the fingers\' spread, around the point between them', () => {
  const r = rig({ zoom: 1, centre: [150, 100] });
  r.fire('pointerdown', 1, 90, 60);
  r.fire('pointerdown', 2, 110, 60);
  r.fire('pointermove', 1, 85, 60);
  r.fire('pointermove', 2, 115, 60);
  r.c.flush(16);
  const win = r.live.at(-1).win;
  assert.ok(near(RECT.w / win.w, 1.5), `spread 1.5 times: zoom ${RECT.w / win.w}, not a step`);
  const [sx, sy] = screenOf(win, [100, 60]);
  assert.ok(near(sx, 100) && near(sy, 60), 'the point between the fingers stays under them');
  r.fire('pointermove', 1, 0, 60);
  r.fire('pointermove', 2, 300, 60);
  r.c.flush(16);
  assert.ok(near(RECT.w / r.live.at(-1).win.w, 8), 'never past 8');
  r.fire('pointerup', 1, 0, 60);
  r.fire('pointerup', 2, 300, 60);
  r.c.settle();
  assert.equal(r.views.at(-1).zoom, 8);
});

test('the wheel zooms smoothly over several frames around the pointer, and is told once', () => {
  const r = rig({ zoom: 1, centre: [150, 100] });
  r.fire('wheel', 0, 60, 40, { deltaY: -400, deltaMode: 0 });
  r.c.settle();
  const zooms = r.live.map((l) => RECT.w / l.win.w);
  assert.ok(zooms.length > 3, 'over several frames');
  assert.ok(zooms.some((z) => z > 1.05 && z < zooms.at(-1) - 0.05), 'through the zooms between');
  assert.ok(zooms.at(-1) > 1.5 && zooms.at(-1) <= 8);
  const u = [60, 40];
  const [sx, sy] = screenOf(r.live.at(-1).win, u);
  assert.ok(near(sx, 60, 1e-3) && near(sy, 40, 1e-3), 'the point under the pointer stays under it');
  assert.equal(r.views.length, 1);
  assert.ok(near(r.views[0].zoom, zooms.at(-1)));
});

test('the plus and minus keys zoom smoothly around the middle; reduced motion jumps', () => {
  const r = rig({ zoom: 2, centre: [150, 100] });
  r.root.dispatchEvent(ev('keydown', 0, 0, 0, { key: '+', target: r.root }));
  r.c.settle();
  assert.ok(r.live.length > 2, 'animated');
  assert.ok(near(r.views.at(-1).zoom, 2 * view.KEY_ZOOM, 1e-6));
  assert.deepEqual(r.views.at(-1).centre, [150, 100]);
  r.root.dispatchEvent(ev('keydown', 0, 0, 0, { key: '-', target: r.root }));
  r.c.settle();
  assert.ok(near(r.views.at(-1).zoom, 2, 1e-6));
  const q = rig({ zoom: 2, centre: [150, 100], reduced: true });
  q.root.dispatchEvent(ev('keydown', 0, 0, 0, { key: '+', target: q.root }));
  q.c.settle();
  assert.equal(q.live.length, 1, 'one step, no animation');
});

test('zoom is kept between 1 and 8; the buttons keep their three stops', () => {
  assert.equal(view.MAX_ZOOM, 8);
  assert.deepEqual(view.ZOOMS, [1, 2, 4]);
  assert.equal(view.viewWindow(RECT, 20).w, RECT.w / 8);
  assert.equal(view.viewWindow(RECT, 0.2).w, RECT.w);
  assert.equal(view.viewWindow(RECT, 3).w, 100, 'a zoom between the stops is kept');
});

// --- Rule 4: labels recomputed at most ten times a second during a gesture ----------------

test('labels are recomputed at most ten times a second during a gesture, and when it ends', () => {
  const r = rig({ zoom: 4, centre: [100, 100], reduced: true });
  r.fire('pointerdown', 1, 150, 100);
  for (let i = 1; i <= 30; i += 1) {
    r.c.advance(16);
    r.fire('pointermove', 1, 150 - i * 10, 100);
    r.c.flush(0);
  }
  const during = r.live.filter((l) => l.labels && !l.end).length;
  assert.equal(r.live.length, 30);
  assert.ok(during >= 1 && during <= 5, `${during} label passes in 480 ms`);
  r.fire('pointerup', 1, -150, 100);
  assert.equal(r.live.at(-1).labels, true);
});

// --- Rule 5: a tap is still a tap ---------------------------------------------------------

test('a press that moves less than 8 px and lifts within 300 ms is a tap; others are not', () => {
  const r = rig({ zoom: 1 });
  r.fire('pointerdown', 1, 100, 50);
  r.c.advance(120);
  r.fire('pointermove', 1, 105, 50);
  r.fire('pointerup', 1, 105, 50);
  assert.deepEqual(r.taps, [[105, 50]]);
  r.fire('pointerdown', 1, 100, 50);
  r.fire('pointermove', 1, 108, 50);
  r.fire('pointerup', 1, 108, 50);
  assert.equal(r.taps.length, 1, '8 px is a drag');
  r.c.settle();
  r.fire('pointerdown', 1, 100, 50);
  r.c.advance(301);
  r.fire('pointerup', 1, 100, 50);
  assert.equal(r.taps.length, 1, 'held too long');
});

test('a tap after a pan picks the point under the view as it now is', () => {
  const r = rig({ zoom: 2, centre: [150, 100], reduced: true });
  r.fire('pointerdown', 1, 150, 100);
  r.c.advance(16);
  r.fire('pointermove', 1, 100, 100);
  r.c.advance(16);
  r.fire('pointerup', 1, 100, 100);
  r.c.settle();
  r.c.advance(500);
  r.fire('pointerdown', 1, 150, 100);
  r.fire('pointerup', 1, 150, 100);
  const k = view.unitsPerPx(view.viewWindow(RECT, 2), PX);
  assert.deepEqual(r.taps, [[150 + 50 * k, 100]]);
});

test('a click that ends a pan is not passed on to the mark under the finger', () => {
  const r = rig({ zoom: 2, reduced: true });
  r.fire('pointerdown', 1, 150, 100);
  r.fire('pointermove', 1, 120, 100);
  r.fire('pointerup', 1, 120, 100);
  const click = ev('click', 1, 120, 100, { target: r.root });
  r.root.dispatchEvent(click);
  assert.equal(click.defaultPrevented, true);
  r.fire('pointerdown', 1, 150, 100);
  r.fire('pointerup', 1, 150, 100);
  const tap = ev('click', 1, 150, 100, { target: r.root });
  r.root.dispatchEvent(tap);
  assert.equal(tap.defaultPrevented, false, 'a tap\'s click goes through');
});

// --- Rule 6: the view is told when a gesture ends -----------------------------------------

test('the view is told once, when the gesture ends, and not for a tap', () => {
  const r = rig({ zoom: 2, centre: [150, 100], reduced: true });
  r.fire('pointerdown', 1, 150, 100);
  r.fire('pointerup', 1, 150, 100);
  assert.equal(r.views.length, 0);
  r.fire('pointerdown', 1, 150, 100);
  r.fire('pointermove', 1, 130, 100);
  r.fire('pointermove', 1, 110, 100);
  assert.equal(r.views.length, 0);
  r.fire('pointerup', 1, 110, 100);
  assert.equal(r.views.length, 1);
  const k = view.unitsPerPx(view.viewWindow(RECT, 2), PX);
  assert.deepEqual(r.views[0], { zoom: 2, centre: [150 + 40 * k, 100] });
});

// --- Rule 7: the arrow keys pan when the map has the focus and no piece is picked ---------

test('the arrow keys pan the map; not while a piece is picked', () => {
  const r = rig({ zoom: 2, centre: [150, 100] });
  r.root.dispatchEvent(ev('keydown', 0, 0, 0, { key: 'ArrowRight', target: r.root }));
  r.c.settle();
  assert.ok(r.views.at(-1).centre[0] > 150, 'right');
  r.root.dispatchEvent(ev('keydown', 0, 0, 0, { key: 'ArrowUp', target: r.root }));
  r.c.settle();
  assert.ok(r.views.at(-1).centre[1] < 100, 'up');
  const picked = rig({ zoom: 2, centre: [150, 100], selected: 'Fleet' });
  const key = ev('keydown', 0, 0, 0, { key: 'ArrowRight', target: picked.root });
  picked.root.dispatchEvent(key);
  picked.c.settle();
  assert.equal(picked.views.length, 0);
  assert.equal(key.defaultPrevented, false, 'the key is left for the piece');
  const taken = ev('keydown', 0, 0, 0, { key: 'ArrowRight', target: r.root, defaultPrevented: true });
  const before = r.views.length;
  r.root.dispatchEvent(taken);
  r.c.settle();
  assert.equal(r.views.length, before, 'a key a lit area took is not a pan');
});

// --- The drawing: land moved as one picture, marks drawn over it at their size -------------

test('during a drag the land is moved as one picture and the marks are drawn over it at their size', () => {
  const figure = document.createElement('figure');
  document.body.append(figure);
  const views = [];
  const pic = territoryDrawing(TMAP, SHAPES, { px: { width: 300, height: 200 }, zoom: 2, onView: (v) => views.push(v) });
  figure.append(pic);
  // the page's CSP refuses a style attribute: inline style goes through the CSS object model
  const css = {};
  pic.style = { setProperty: (k, v) => { css[k] = v; }, removeProperty: (k) => { delete css[k]; } };
  const marks = pic.querySelectorAll('.rl-tm-label').length;
  assert.ok(marks > 0);
  const rest = pic.getAttribute('viewBox');
  pic.dispatchEvent(ev('pointerdown', 1, 150, 100, { target: pic }));
  pic.dispatchEvent(ev('pointermove', 1, 120, 100, { target: pic }));
  assert.equal(pic.getAttribute('viewBox'), rest, 'the land keeps its drawing');
  assert.equal(css.transform, 'translate(-30px, 0px) scale(1)');
  assert.equal(css['transform-origin'], '0 0');
  assert.equal(pic.getAttribute('style'), null, 'no style attribute, which the page\'s CSP refuses');
  const over = figure.querySelector('svg.rl-tm-live');
  assert.ok(over, 'the marks have a layer of their own');
  assert.equal(over.getAttribute('style'), null, 'nor on the layer');
  assert.equal(over.querySelectorAll('.rl-tm-label').length, marks);
  const [ox, , ow] = over.getAttribute('viewBox').split(' ').map(Number);
  const [rx, , rw] = rest.split(' ').map(Number);
  assert.equal(ow, rw);
  assert.ok(near(ox, rx + 30 * Number(pic.getAttribute('data-k'))), 'the marks\' layer shows the view as it now is');
  const k = Number(over.getAttribute('data-k'));
  const m = over.querySelector('.rl-tm-label');
  assert.match(m.getAttribute('transform'), new RegExp(`scale\\(${k}\\)$`), 'marks drawn at their pixel size');
  pic.dispatchEvent(ev('pointerup', 1, 120, 100, { target: pic }));
  assert.equal(figure.querySelector('svg.rl-tm-live'), null, 'the layer goes when the gesture ends');
  assert.equal(pic.querySelectorAll('.rl-tm-label').length, marks, 'the marks are back in the drawing');
  assert.deepEqual(css, {}, 'the land is back in place');
  assert.notEqual(pic.getAttribute('viewBox'), rest, 'the drawing now shows the new view');
  assert.equal(views.length, 1);
  figure.remove();
});

test('the drawing can take the focus, and its land may show past its box while it moves', () => {
  const pic = territoryDrawing(TMAP, SHAPES, { px: { width: 300, height: 200 } });
  assert.equal(pic.getAttribute('tabindex'), '0');
  assert.match(CSS_TEXT, /\.rl-tm-svg\.rl-tm-moving \{[^}]*overflow: visible/);
  assert.match(CSS_TEXT, /\.rl-tm-live \{[^}]*pointer-events: none/);
  assert.match(CSS_TEXT, /\.rl-tmap \.rl-map-figure \{[^}]*position: relative/);
});
