// Pieces that slide and stack, with strength as pips (SLD): on the territory map an own piece
// shows its strength as solid pips against hollow ones and its posture as a word, the figure
// only when picked; pieces in one area stack as one marker with a count and fan out on a tap
// or Enter (Escape closes); a piece whose area changed since the last drawing slides there
// (at once under reduced motion); a piece under way shows its path dashed with its arrival,
// and an order still with a holder a dashed ghost at its goal: "with Stavka to 16 Oct".
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { fire, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { theatreBoard, forgetShapes } = await import('../js/views/realism-theatre.js');
const { territoryDrawing, forgetMarks } = await import('../js/views/realism-territory.js');
const rules = await import('../js/realism-rules.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const CSS_TEXT = readFileSync(new URL('../css/c-map.css', import.meta.url), 'utf8');
const TMAP = fixture.territory_map;
const DESK = { width: 960, height: 740 };

const AREAS = Object.fromEntries(TMAP.areas.map((a) => [a.key, { key: a.key, name: a.name, place: null }]));
const tmap = () => structuredClone(TMAP);
const named = (map, name) => map.marks.find((m) => m.name === name);
const draw = (map, opts = {}) => territoryDrawing(map, SHAPES, { px: DESK, ...opts });
const marksOf = (pic) => pic.querySelectorAll('g.rl-tm-mark');
const markNamed = (pic, name) => marksOf(pic).find((g) => g.getAttribute('aria-label').startsWith(`${name}:`));
const stacks = (pic) => pic.querySelectorAll('g.rl-tm-stack');
const key = (e) => ({ type: 'keydown', key: e, preventDefault() {}, stopPropagation() {} });

/** The toy map with the Levy moved to `area` (and so out of the Norra Plain's stack). */
function levyIn(area, piece = {}) {
  const map = tmap();
  const levy = named(map, 'The Norra Levy');
  Object.assign(levy.piece, { area: AREAS[area], ...piece });
  return map;
}

// --- the rules ------------------------------------------------------------------

test('a piece\'s strength is pips: solid to its strength, hollow to five or more; an envoy has none', () => {
  assert.deepEqual(rules.pipsOf({ domain: 'land', strength: 1 }), { filled: 1, slots: 5 });
  assert.deepEqual(rules.pipsOf({ domain: 'air', strength: 0 }), { filled: 0, slots: 5 });
  assert.deepEqual(rules.pipsOf({ domain: 'sea', strength: 7 }), { filled: 7, slots: 7 }, 'no pip is ever dropped');
  assert.equal(rules.pipsOf({ domain: 'envoy', strength: 0 }), null);
  assert.equal(rules.pipsOf(null), null, 'a reported mark has no piece and no pips');
  assert.equal(rules.PIP_SLOTS, 5);
});

test('posture is a word, and none is blank', () => {
  assert.equal(rules.postureWord('hold'), 'Hold');
  assert.equal(rules.postureWord('escort'), 'Escort');
  assert.equal(rules.postureWord(null), '');
  assert.throws(() => rules.postureWord('loiter'), /unknown word/);
});

test('an order still with a holder reads as the ghost says it', () => {
  assert.equal(rules.waitWords({ with_person: 'Stavka', until: '1941-10-16' }), 'with Stavka to 16 Oct');
  assert.equal(rules.waitWords({ with_person: 'Stavka', until: null }), 'with Stavka');
  assert.equal(rules.waitWords({ with_person: null, until: '1941-10-16' }), 'the order is moving to 16 Oct');
});

test('a course reads as the step it is on, then the rest, then the day it arrives', () => {
  const a = (name) => ({ key: name, name, place: null });
  assert.equal(rules.courseLine({ path: [a('The Gulf'), a('The Sudland Coast')], step_due: '1900-04-04', arrives: '1900-04-06' }),
    'Under way: on the step into The Gulf, in 4 Apr; then The Sudland Coast; arrives 6 Apr');
  assert.equal(rules.courseLine({ path: [a('The Isle')], step_due: '1900-04-05', arrives: '1900-04-05' }),
    'Under way: on the step into The Isle, in 5 Apr');
  assert.equal(rules.courseLine({ path: [], step_due: null, arrives: null }), '');
});

test('a mark slides only from where it stood when its area has changed', () => {
  const memory = new Map();
  assert.equal(rules.slideFrom(memory, 'm1', 'plain', [1, 2]), null, 'first seen: stands at once');
  assert.equal(rules.slideFrom(memory, 'm1', 'plain', [1, 2]), null, 'same area: no slide');
  assert.deepEqual(rules.slideFrom(memory, 'm1', 'isle', [9, 9]), [1, 2], 'a new area: from where it stood');
  assert.equal(rules.slideFrom(memory, 'm1', 'isle', [9, 9]), null, 'and once there it stays');
  assert.equal(rules.markKey({ key: 'mk', piece: { key: 'pk' } }), 'pk');
  assert.equal(rules.markArea({ piece: { area: { key: 'isle', name: 'The Isle' } } }), 'isle');
  assert.equal(rules.markArea({ places: [{ name: 'Sudby' }] }), 'Sudby');
});

// --- the drawing ------------------------------------------------------------------

test('an own piece draws its strength as pips and its posture as a word, the figure only when picked', () => {
  forgetMarks();
  const map = levyIn('isle', { strength: 3, posture: 'hold' });
  const pic = draw(map);
  const levy = markNamed(pic, 'The Norra Levy');
  const pips = levy.querySelector('g.rl-tm-pips');
  assert.equal(pips.getAttribute('data-filled'), '3');
  assert.equal(pips.querySelectorAll('rect').length, 5);
  assert.equal(pips.querySelectorAll('rect.rl-pip-empty').length, 2, 'two hollow pips past its strength');
  assert.equal(levy.querySelector('text.rl-mk-posture').textContent, 'Hold');
  assert.equal(levy.querySelector('text.rl-pip-num'), null, 'the number is on tap');
  assert.match(levy.getAttribute('aria-label'), /; Hold/);
  const picked = markNamed(draw(map, { selected: 'The Norra Levy' }), 'The Norra Levy');
  assert.equal(picked.querySelector('text.rl-pip-num').textContent, '3', 'picked: the figure beside the pips');
});

test('an envoy has no pips, and a reported mark is drawn as before', () => {
  forgetMarks();
  const map = tmap();
  const herald = named(map, 'The Norra Herald');
  herald.piece.area = AREAS.isle;
  const pic = draw(map);
  assert.equal(markNamed(pic, 'The Norra Herald').querySelector('g.rl-tm-pips'), null);
});

test('pieces in one area stack as one marker with a count; a lone piece does not', () => {
  forgetMarks();
  const pic = draw(tmap());
  assert.equal(marksOf(pic).length, 0, 'the three Norra pieces share the Norra Plain');
  const [stack] = stacks(pic);
  assert.equal(stack.getAttribute('data-count'), '3');
  assert.equal(stack.getAttribute('data-stack'), 'norra_plain');
  assert.equal(stack.querySelector('g.rl-tm-count text').textContent, '3');
  assert.equal(stack.getAttribute('role'), 'button');
  assert.equal(stack.getAttribute('aria-expanded'), 'false');
  assert.match(stack.getAttribute('aria-label'),
    /^3 pieces in The Norra Plain: The Norra Herald, The Norra Kites, The Norra Levy\. Open the stack$/);
  const apart = draw(levyIn('isle'));
  assert.equal(stacks(apart).length, 1, 'two left in the plain still stack');
  assert.equal(stacks(apart)[0].getAttribute('data-count'), '2');
  assert.ok(markNamed(apart, 'The Norra Levy'), 'the Levy alone on the Isle is its own marker');
});

test('a tap or Enter on a stack fans it; the fan shows each piece side by side; Escape or the closer closes it', () => {
  forgetMarks();
  const asked = [];
  const onFan = (k) => asked.push(k);
  const closed = draw(tmap(), { onFan });
  stacks(closed)[0].click();
  stacks(closed)[0].dispatchEvent(key('Enter'));
  assert.deepEqual(asked, ['norra_plain', 'norra_plain']);
  const fan = draw(tmap(), { onFan, fanned: 'norra_plain' });
  assert.equal(stacks(fan).length, 0);
  const shown = marksOf(fan);
  assert.equal(shown.length, 3);
  const offsets = shown.map((g) => g.querySelector('g[transform]').getAttribute('transform').match(/translate\((-?[\d.]+)/)[1]);
  assert.equal(new Set(offsets).size, 3, 'side by side, not on top of each other');
  assert.ok(shown.every((g) => g.getAttribute('tabindex') === '0' && g.getAttribute('data-stack') === 'norra_plain'));
  shown[1].dispatchEvent({ type: 'keyup', key: 'Escape', preventDefault() {}, stopPropagation() {} });
  const closer = fan.querySelector('g.rl-tm-fanclose');
  assert.equal(closer.getAttribute('aria-expanded'), 'true');
  assert.equal(closer.getAttribute('aria-label'), 'Close the stack of 3');
  closer.click();
  assert.deepEqual(asked.slice(2), [null, null]);
});

test('a picked piece keeps its stack fanned, so it can be seen picked', () => {
  forgetMarks();
  const pic = draw(tmap(), { selected: 'The Norra Kites' });
  assert.equal(stacks(pic).length, 0);
  assert.equal(markNamed(pic, 'The Norra Kites').getAttribute('aria-pressed'), 'true');
});

test('a piece whose area changed since the last drawing slides from where it stood; the rest stand', () => {
  forgetMarks();
  draw(levyIn('isle'));
  const was = draw(levyIn('isle'));
  assert.equal(was.querySelectorAll('[data-slide-from]').length, 0, 'nothing moved, nothing slides');
  const animated = [];
  const realAnimate = globalThis.Element?.prototype?.animate;
  const proto = Object.getPrototypeOf(document.createElementNS('http://www.w3.org/2000/svg', 'g'));
  proto.animate = function animate(frames, o) { animated.push({ frames, o }); };
  try {
    const now = draw(levyIn('sudland_coast'));
    const slid = now.querySelectorAll('g.rl-tm-slide[data-slide-from]');
    assert.equal(slid.length, 1);
    assert.equal(slid[0].getAttribute('data-slide-from'), '250 100', 'from the Isle\'s label point');
    assert.match(slid[0].querySelector('g.rl-tm-mark').getAttribute('aria-label'), /^The Norra Levy:/);
    assert.equal(animated.length, 1);
    assert.equal(animated[0].o.duration, rules.SLIDE_MS);
    assert.equal(animated[0].frames.at(-1).transform, 'translate(0px, 0px)');
  } finally {
    if (realAnimate) proto.animate = realAnimate; else delete proto.animate;
  }
});

test('under reduced motion a moved piece stands in its new area at once', () => {
  forgetMarks();
  draw(levyIn('isle'));
  const was = globalThis.matchMedia;
  globalThis.matchMedia = (q) => ({ matches: q === '(prefers-reduced-motion: reduce)' });
  try {
    const now = draw(levyIn('sudland_coast'));
    assert.equal(now.querySelectorAll('[data-slide-from]').length, 0);
  } finally { globalThis.matchMedia = was; }
  assert.match(CSS_TEXT, /@media \(prefers-reduced-motion: reduce\) \{ \.rl-tm-slide/);
});

test('a still drawing (a proof sheet) neither slides nor remembers', () => {
  forgetMarks();
  draw(levyIn('isle'), { still: true });
  const now = draw(levyIn('sudland_coast'));
  assert.equal(now.querySelectorAll('[data-slide-from]').length, 0, 'the still drawing left no memory');
});

test('a piece under way shows its path dashed through each area to its goal, with the day it arrives', () => {
  forgetMarks();
  const map = levyIn('norra_hills', {
    under_way: { path: [AREAS.the_gulf, AREAS.sudland_coast], step_due: '1900-04-04', arrives: '1900-04-06' },
  });
  const pic = draw(map);
  const [course] = pic.querySelectorAll('g.rl-tm-course');
  assert.equal(course.querySelector('polyline.rl-tm-path').getAttribute('points'), '50,50 150,150 50,150',
    'from the Norra Hills, through the Gulf, to the Sudland Coast (y flipped)');
  assert.ok(course.querySelector('polyline').classList.contains('rl-mk-arrow'), 'dashed like every order line');
  assert.equal(words(course.querySelector('text')), '6 Apr');
  assert.match(course.getAttribute('aria-label'), /^The Norra Levy: Under way: on the step into The Gulf, in 4 Apr; then The Sudland Coast; arrives 6 Apr$/);
  assert.match(markNamed(pic, 'The Norra Levy').getAttribute('aria-label'), /Under way: on the step into The Gulf/);
});

test('an order still with its holder shows a dashed ghost at the goal: "with Stavka to 16 Oct"', () => {
  forgetMarks();
  const map = levyIn('norra_hills', {
    waiting: { order: 'o-1', with_person: 'Stavka', until: '1900-10-16', withdrawable: true },
  });
  map.orders = [{
    order: 'o-1', force: 'The Norra Levy', mark: 'The Norra Levy', to: { name: 'The Isle', lat: null, lon: null, theatre: null },
    status: 'awaiting', with_person: 'Stavka', filed: '1900-04-01',
  }];
  const pic = draw(map);
  const order = pic.querySelector('g.rl-mk-order');
  assert.equal(order.getAttribute('aria-label'), 'The Norra Levy to The Isle: with Stavka to 16 Oct');
  const ghost = order.querySelector('g.rl-tm-ghost');
  assert.deepEqual([ghost.getAttribute('data-x'), ghost.getAttribute('data-y')], ['250', '100'], 'at the Isle, found by name');
  assert.equal(words(ghost.querySelector('text.rl-tm-ghost-note')), 'with Stavka to 16 Oct');
  assert.equal(ghost.querySelector('.rl-mk-shape').getAttribute('class'), 'rl-mk-shape');
  assert.match(CSS_TEXT, /\.rl-tm-ghost \.rl-mk-shape \{[^}]*stroke-dasharray/);
  assert.match(markNamed(pic, 'The Norra Levy').getAttribute('aria-label'), /Order with Stavka to 16 Oct$/);
  const line = order.querySelector('line.rl-mk-arrow');
  assert.deepEqual(['x1', 'y1', 'x2', 'y2'].map((a) => line.getAttribute(a)), ['50', '50', '250', '100']);
});

test('an order whose goal is nowhere on the map is left off', () => {
  forgetMarks();
  const map = tmap();
  map.orders = [{ order: 'o-2', force: 'X', mark: null, to: { name: 'Nowhere', lat: null, lon: null, theatre: null }, status: 'awaiting', with_person: null, filed: '1900-04-01' }];
  assert.equal(draw(map).querySelectorAll('g.rl-mk-order').length, 0);
});

// --- the room -----------------------------------------------------------------------

test('in the room a stack fans in place and focus moves into it; Escape closes it and focus returns to the stack', async () => {
  forgetShapes();
  forgetMarks();
  const was = globalThis.fetch;
  globalThis.fetch = async (url) => ({ ok: true, status: 200, json: async () => (url === '/api/realism/map' ? { reply: '', refused: false, file: TMAP.file, map: SHAPES } : {}) });
  try {
    const r = { ...fixture, map: tmap() };
    const u = { piece: null, theatre: { mode: 'map', scope: 'reports' } };
    const first = theatreBoard(r, u, { pick: () => {}, act: () => {} });
    document.body.append(first);
    await new Promise((ok) => setTimeout(ok, 0));
    await new Promise((ok) => setTimeout(ok, 0));
    first.remove();
    const view = theatreBoard(r, u, { pick: () => {}, act: () => {} });
    document.body.append(view);
    const stack = view.querySelector('g.rl-tm-stack');
    assert.ok(stack, 'the stack is drawn');
    fire(stack, 'click');
    assert.equal(view.querySelectorAll('g.rl-tm-stack').length, 0, 'fanned');
    assert.equal(view.querySelectorAll('g.rl-tm-mark').length, 3);
    assert.ok(document.activeElement.classList.contains('rl-tm-mark'), 'focus on the first fanned piece');
    document.activeElement.dispatchEvent({ type: 'keyup', key: 'Escape', preventDefault() {}, stopPropagation() {} });
    assert.equal(view.querySelectorAll('g.rl-tm-stack').length, 1, 'closed again');
    assert.ok(document.activeElement.classList.contains('rl-tm-stack'), 'focus back on the stack');
    view.remove();
  } finally { globalThis.fetch = was; }
});

test('a lit area under a stack stays clickable: the lit targets are drawn over every mark', () => {
  forgetMarks();
  const picked = [];
  const plain = { name: 'Norrhavn', lat: 150, lon: 150, theatre: null };
  const pic = draw(tmap(), { targets: [{ place: plain, value: 'norrhavn', days: '5 days', chosen: false }], onTarget: (v) => picked.push(v) });
  const layers = pic.querySelectorAll('g.rl-tm-stack, g.rl-map-target');
  assert.ok(layers.at(-1).classList.contains('rl-map-target'), 'the target comes after the stack in drawing order');
  assert.ok(layers.some((g) => g.classList.contains('rl-tm-stack')));
  layers.at(-1).click();
  assert.deepEqual(picked, ['norrhavn']);
});

test('marks are keyed by their piece\'s key, not their name: a renamed piece still slides, a new piece under an old name does not', () => {
  forgetMarks();
  draw(levyIn('isle'));
  const renamed = levyIn('sudland_coast');
  named(renamed, 'The Norra Levy').name = 'The Norra Guard';
  const now = draw(renamed);
  const slid = now.querySelectorAll('g.rl-tm-slide[data-slide-from]');
  assert.equal(slid.length, 1, 'the same key: the same piece');
  assert.equal(slid[0].querySelector('g.rl-tm-mark').getAttribute('data-key'), named(TMAP, 'The Norra Levy').piece.key);
  forgetMarks();
  draw(levyIn('isle'));
  const other = levyIn('sudland_coast');
  named(other, 'The Norra Levy').piece.key = 'm-another-piece';
  assert.equal(draw(other).querySelectorAll('[data-slide-from]').length, 0, 'another key under the old name stands at once');
});

test('a fanned stack stays fanned when the room draws the board again (a poll)', async () => {
  forgetShapes();
  forgetMarks();
  const was = globalThis.fetch;
  globalThis.fetch = async (url) => ({ ok: true, status: 200, json: async () => (url === '/api/realism/map' ? { reply: '', refused: false, file: TMAP.file, map: SHAPES } : {}) });
  try {
    const r = { ...fixture, map: tmap() };
    const u = { piece: null, theatre: { mode: 'map', scope: 'reports' } };
    const first = theatreBoard(r, u, { pick: () => {}, act: () => {} });
    document.body.append(first);
    await new Promise((ok) => setTimeout(ok, 0));
    await new Promise((ok) => setTimeout(ok, 0));
    first.remove();
    const view = theatreBoard(r, u, { pick: () => {}, act: () => {} });
    document.body.append(view);
    fire(view.querySelector('g.rl-tm-stack'), 'click');
    view.remove();
    const again = theatreBoard(r, u, { pick: () => {}, act: () => {} });
    assert.equal(again.querySelectorAll('g.rl-tm-stack').length, 0, 'still fanned');
    assert.equal(again.querySelectorAll('g.rl-tm-mark').length, 3);
  } finally { globalThis.fetch = was; }
});
