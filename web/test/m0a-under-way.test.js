// Pieces under way are drawn on their way: an own piece on a step stands between the area it
// left and the area it is entering, at the share of the step's days gone, with a tag ("day 3 of
// 5 into The Gulf"); its course still to go is drawn as before and the part travelled fainter; an
// envoy is drawn the same on the Diplomatic layer; a course just sent draws itself once; a
// territory that changes hands fills evenly; the playback can place an own mark at a share of a
// step and run a clock of world days; travel is linear. An enemy report is never drawn in
// transit, and under reduced motion nothing moves. Every timing runs on a fake clock.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { territoryDrawing, forgetMarks } = await import('../js/views/realism-territory.js');
// imported apart, so that each rule's test fails by itself on a tree without the module
const motion = await import('../js/map/motion.js').catch(() => ({}));
const { SLIDE_MS } = await import('../js/realism-rules.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const CSS_TEXT = readFileSync(new URL('../css/c-map.css', import.meta.url), 'utf8');
const TMAP = fixture.territory_map;
const DESK = { width: 960, height: 740 };

const AREAS = Object.fromEntries(TMAP.areas.map((a) => [a.key, { key: a.key, name: a.name, place: null }]));
const tmap = () => structuredClone(TMAP);
const named = (map, name) => map.marks.find((m) => m.name === name);
const markNamed = (pic, name) => pic.querySelectorAll('g.rl-tm-mark').find((g) => g.getAttribute('aria-label').startsWith(`${name}:`));
const xyOf = (g) => [Number(g.getAttribute('data-x')), Number(g.getAttribute('data-y'))];

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
    waiting: () => queue.length,
  };
}

const draw = (map, opts = {}) => territoryDrawing(map, SHAPES, { px: DESK, today: '1900-04-04', ...opts });

/** A step from the Norra Hills (50, 50) into the Gulf (150, 150) begun 1 Apr and due 6 Apr: five days. */
const STEP = { path: [AREAS.the_gulf, AREAS.sudland_coast], step_began: '1900-04-01', step_due: '1900-04-06', step_days: 5, arrives: '1900-04-08' };

/** The toy map with `name` (an own piece) in `area`, under way on `course` (none when null). */
function underWayMap(course = STEP, name = 'The Norra Levy', area = 'norra_hills') {
  const map = tmap();
  Object.assign(named(map, name).piece, { area: AREAS[area], under_way: course ? structuredClone(course) : null });
  return map;
}

/** An enemy report in the Isle, given every field an own piece under way has. */
function withEnemy(map, area = 'isle') {
  map.marks.push({
    name: 'The Sud Column', key: 'r-sud', kind: 'piece', side: 'other', side_name: 'Sudland', certainty: 'reported', reported: '1900-04-03', source: 'a patrol', places: [], area: AREAS[area],
    piece: { key: 'r-sud', domain: 'land', area: AREAS[area], under_way: structuredClone(STEP) },
  });
  return map;
}

/** Record `animate` calls on every element while `fn` runs. */
function recording(fn) {
  const proto = Object.getPrototypeOf(document.createElementNS('http://www.w3.org/2000/svg', 'g'));
  const real = proto.animate;
  const got = [];
  proto.animate = function animate(frames, how) { got.push({ el: this, frames, how }); };
  try { fn(); } finally { if (real) proto.animate = real; else delete proto.animate; }
  return got;
}

function reduced(fn) {
  const was = globalThis.matchMedia;
  globalThis.matchMedia = (q) => ({ matches: q === '(prefers-reduced-motion: reduce)' });
  try { return fn(); } finally { globalThis.matchMedia = was; }
}

// --- rule 1: an own piece under way stands between its two areas, with its tag ------------------

test('a step\'s share is the whole days gone since it began over its days, held between 0 and 1', () => {
  assert.deepEqual(motion.stepShare?.(STEP, '1900-04-04'), { gone: 3, days: 5, share: 0.6 });
  assert.deepEqual(motion.stepShare(STEP, '1900-04-01'), { gone: 0, days: 5, share: 0 });
  assert.deepEqual(motion.stepShare(STEP, '1900-04-09'), { gone: 5, days: 5, share: 1 }, 'never past the area it enters');
  assert.deepEqual(motion.stepShare(STEP, '1900-03-30'), { gone: 0, days: 5, share: 0 }, 'never behind the area it left');
  assert.equal(motion.stepShare({ ...STEP, step_began: null }, '1900-04-04'), null, 'no day it began: no share');
  assert.equal(motion.stepShare(STEP, null), null, 'no today: no share');
  assert.equal(motion.stepShare({ ...STEP, step_due: STEP.step_began }, '1900-04-04'), null, 'a step of no days');
  assert.equal(motion.stepTag({ gone: 3, days: 5 }, 'Smolensk'), 'day 3 of 5 into Smolensk');
  assert.equal(motion.stepTag({ gone: 0, days: 5 }, 'Smolensk'), 'day 1 of 5 into Smolensk', 'the day it began is its first');
});

test('an own piece under way is drawn between the area it left and the one it enters, at the share of its days gone', () => {
  forgetMarks();
  for (const [today, xy, tag] of [
    ['1900-04-02', [70, 70], 'day 1 of 5 into The Gulf'],
    ['1900-04-04', [110, 110], 'day 3 of 5 into The Gulf'],
    ['1900-04-05', [130, 130], 'day 4 of 5 into The Gulf'],
  ]) {
    const levy = markNamed(draw(underWayMap(), { today }), 'The Norra Levy');
    assert.deepEqual(xyOf(levy), xy, `${today}: from (50, 50) toward (150, 150)`);
    assert.ok(levy.querySelector('text.rl-tm-tag'), 'the mark carries its tag');
    assert.equal(words(levy.querySelector('text.rl-tm-tag')), tag);
    assert.match(levy.getAttribute('aria-label'), new RegExp(`; ${tag}`));
  }
});

test('a piece under way stands apart from the pieces in the area it left', () => {
  forgetMarks();
  const pic = draw(underWayMap(STEP, 'The Norra Levy', 'norra_plain'));
  const levy = markNamed(pic, 'The Norra Levy');
  assert.ok(levy, 'drawn as a mark of its own, not in the Norra Plain\'s stack');
  assert.equal(pic.querySelector('g.rl-tm-stack').getAttribute('data-count'), '2', 'the Herald and the Kites stay stacked');
});

test('a piece whose step has no day it began stands in the area it left, as before, with no tag', () => {
  forgetMarks();
  const levy = markNamed(draw(underWayMap({ ...STEP, step_began: null, step_days: null })), 'The Norra Levy');
  assert.deepEqual(xyOf(levy), [50, 50]);
  assert.equal(levy.querySelector('text.rl-tm-tag'), null);
});

test('an enemy report is never drawn in transit: it stands at the area its page names, with no tag', () => {
  forgetMarks();
  const sud = markNamed(draw(withEnemy(tmap())), 'The Sud Column');
  assert.deepEqual(xyOf(sud), [250, 100], 'at the Isle\'s label point');
  assert.equal(sud.querySelector('text.rl-tm-tag'), null);
  assert.equal(motion.underWay?.({ ...withEnemy(tmap()).marks.at(-1) }, new Map([['isle', [250, 100]], ['the_gulf', [150, 150]]]), '1900-04-04'), null);
});

test('an enemy report that moved keeps its short slide', () => {
  forgetMarks();
  draw(withEnemy(tmap(), 'isle'));
  const got = recording(() => draw(withEnemy(tmap(), 'sudland_coast')));
  const slid = got.filter((a) => a.el.getAttribute('data-slide-from'));
  assert.equal(slid.length, 1);
  assert.equal(slid[0].how.duration, SLIDE_MS);
  assert.equal(slid[0].how.easing, 'ease-in-out');
});

// --- rule 2: the course to go as before, the part travelled fainter -----------------------------

test('the course still to go starts at the piece and the part travelled is a fainter line from the area it left', () => {
  forgetMarks();
  const course = draw(underWayMap()).querySelector('g.rl-tm-course');
  assert.equal(course.querySelector('polyline.rl-tm-path').getAttribute('points'), '110,110 150,150 50,150', 'from the piece, through the Gulf, to the Sudland Coast');
  assert.ok(course.querySelector('polyline.rl-tm-path').classList.contains('rl-mk-arrow'), 'dashed, as before');
  const gone = course.querySelector('polyline.rl-tm-gone');
  assert.equal(gone?.getAttribute('points'), '50,50 110,110');
  assert.match(CSS_TEXT, /\.rl-tm-gone \{[^}]*opacity: 0\.[0-9]+/, 'fainter than the line to go');
});

test('a piece under way with no day it began draws no travelled line', () => {
  forgetMarks();
  const course = draw(underWayMap({ ...STEP, step_began: null })).querySelector('g.rl-tm-course');
  assert.equal(course.querySelector('polyline.rl-tm-path').getAttribute('points'), '50,50 150,150 50,150');
  assert.equal(course.querySelector('polyline.rl-tm-gone'), null);
});

// --- rule 3: an envoy on the Diplomatic layer --------------------------------------------------

test('an envoy under way is drawn on its way on the Diplomatic layer, with its tag and its course', () => {
  forgetMarks();
  const map = underWayMap({ ...STEP, path: [AREAS.the_gulf] }, 'The Norra Herald', 'norra_hills');
  const pic = draw(map, { layer: 'diplomatic' });
  const herald = markNamed(pic, 'The Norra Herald');
  assert.deepEqual(xyOf(herald), [110, 110]);
  assert.equal(words(herald.querySelector('text.rl-tm-tag')), 'day 3 of 5 into The Gulf');
  const courses = pic.querySelectorAll('g.rl-tm-course');
  assert.equal(courses.length, 1, 'the envoy\'s course alone');
  assert.match(courses[0].getAttribute('aria-label'), /^The Norra Herald:/);
  assert.equal(courses[0].querySelector('polyline.rl-tm-gone').getAttribute('points'), '50,50 110,110');
});

test('a force under way is not drawn on the Diplomatic layer', () => {
  forgetMarks();
  const pic = draw(underWayMap(), { layer: 'diplomatic' });
  assert.equal(markNamed(pic, 'The Norra Levy'), undefined);
  assert.equal(pic.querySelectorAll('g.rl-tm-course').length, 0);
});

// --- rule 4: a course just sent draws itself once ----------------------------------------------

test('when a move is sent its course draws itself from the piece to its goal once, in 600 ms', () => {
  forgetMarks();
  assert.equal(motion.COURSE_DRAW_MS, 600);
  const c = clock();
  draw(underWayMap(null), { clock: { now: c.now, frame: c.frame } });
  const path = () => pic.querySelector('g.rl-tm-course polyline.rl-tm-path');
  const pic = draw(underWayMap({ ...STEP, step_began: '1900-04-04', step_due: '1900-04-09' }), { clock: { now: c.now, frame: c.frame } });
  assert.equal(path().getAttribute('points'), '50,50 50,50', 'it starts at the piece');
  c.flush(150);
  assert.equal(path().getAttribute('points'), '50,50 92.68,92.68', 'a quarter of its length a quarter of the way in');
  c.flush(300);
  assert.equal(path().getAttribute('points'), '50,50 150,150 110.36,150', 'three quarters, round the corner');
  c.flush(150);
  assert.equal(path().getAttribute('points'), '50,50 150,150 50,150', 'whole at 600 ms');
  assert.equal(c.waiting(), 0, 'and then it stops');
  const again = draw(underWayMap({ ...STEP, step_began: '1900-04-04', step_due: '1900-04-09' }), { clock: { now: c.now, frame: c.frame } });
  assert.equal(again.querySelector('g.rl-tm-course polyline.rl-tm-path').getAttribute('points'), '50,50 150,150 50,150', 'once: the next drawing shows it whole');
  assert.equal(c.waiting(), 0);
});

test('a new order\'s line draws itself from the piece to its goal once', () => {
  forgetMarks();
  const c = clock();
  const order = { order: 'o-7', force: 'The Norra Levy', mark: 'The Norra Levy', to: { name: 'The Isle', lat: null, lon: null, theatre: null }, status: 'awaiting', with_person: null, filed: '1900-04-04' };
  draw(underWayMap(null), { clock: { now: c.now, frame: c.frame } });
  const sent = underWayMap(null);
  sent.orders = [order];
  const pic = draw(sent, { clock: { now: c.now, frame: c.frame } });
  const end = () => ['x1', 'y1', 'x2', 'y2'].map((a) => pic.querySelector('g.rl-mk-order line.rl-mk-arrow').getAttribute(a));
  assert.deepEqual(end(), ['50', '50', '50', '50'], 'it starts at the piece');
  c.flush(300);
  assert.deepEqual(end(), ['50', '50', '150', '75']);
  c.flush(300);
  assert.deepEqual(end(), ['50', '50', '250', '100'], 'whole at 600 ms, at the Isle');
  assert.equal(c.waiting(), 0);
  draw(sent, { clock: { now: c.now, frame: c.frame } });
  assert.equal(c.waiting(), 0, 'drawn again, it stands whole');
});

test('a new order\'s line draws itself in a room framed on a region', () => {
  forgetMarks();
  const c = clock();
  const order = { order: 'o-8', force: 'The Norra Levy', mark: 'The Norra Levy', to: { name: 'The Isle', lat: null, lon: null, theatre: null }, status: 'awaiting', with_person: null, filed: '1900-04-04' };
  draw(underWayMap(null), { frame: '', clock: { now: c.now, frame: c.frame } });
  const sent = underWayMap(null);
  sent.orders = [order];
  const pic = draw(sent, { frame: '', clock: { now: c.now, frame: c.frame } });
  assert.equal(pic.querySelector('g.rl-mk-order line.rl-mk-arrow').getAttribute('x2'), '50', 'the room\'s region is not the clock');
  c.flush(600);
  assert.equal(pic.querySelector('g.rl-mk-order line.rl-mk-arrow').getAttribute('x2'), '250');
});

test('an order sent again to a new goal draws its line again', () => {
  forgetMarks();
  const c = clock();
  const order = { order: 'o-9', force: 'The Norra Levy', mark: 'The Norra Levy', to: { name: 'The Isle', lat: null, lon: null, theatre: null }, status: 'awaiting', with_person: null, filed: '1900-04-04' };
  const sent = underWayMap(null);
  sent.orders = [order];
  draw(sent, { clock: { now: c.now, frame: c.frame } });
  draw(sent, { clock: { now: c.now, frame: c.frame } });
  assert.equal(c.waiting(), 0, 'the same order drawn again stands whole');
  const again = underWayMap(null);
  again.orders = [{ ...order, to: { ...order.to, name: 'The Gulf' } }];
  draw(again, { clock: { now: c.now, frame: c.frame } });
  assert.ok(c.waiting() > 0, 'its new goal is drawn to');
});

test('courses and orders on the first drawing stand whole: nothing was just sent', () => {
  forgetMarks();
  const c = clock();
  const map = underWayMap();
  map.orders = [{ order: 'o-8', force: 'The Norra Kites', mark: 'The Norra Kites', to: { name: 'The Isle', lat: null, lon: null, theatre: null }, status: 'awaiting', with_person: null, filed: '1900-04-04' }];
  draw(map, { clock: { now: c.now, frame: c.frame } });
  assert.equal(c.waiting(), 0);
});

test('a still drawing first leaves the next live drawing with nothing just sent', () => {
  forgetMarks();
  const c = clock();
  draw(underWayMap(), { still: true });
  draw(underWayMap(), { clock: { now: c.now, frame: c.frame } });
  assert.equal(c.waiting(), 0);
});

test('under reduced motion a course just sent stands whole at once', () => {
  forgetMarks();
  const c = clock();
  draw(underWayMap(null), { clock: { now: c.now, frame: c.frame } });
  const pic = reduced(() => draw(underWayMap(), { clock: { now: c.now, frame: c.frame } }));
  assert.equal(pic.querySelector('g.rl-tm-course polyline.rl-tm-path').getAttribute('points'), '110,110 150,150 50,150');
  assert.equal(c.waiting(), 0);
});

// --- rule 5: a territory that changes hands fills evenly ---------------------------------------

/** The toy map with the Isle held by `holder` (`relation` to the seat). */
function isleHeld(holder, relation) {
  const map = tmap();
  Object.assign(map.areas.find((a) => a.key === 'isle'), { holder: { name: holder, relation } });
  return map;
}

test('a territory that changes hands fills evenly with its new holder\'s tone', () => {
  forgetMarks();
  const c = clock();
  const opts = { clock: { now: c.now, frame: c.frame } };
  draw(isleHeld('Norra', 'own'), opts);
  const first = draw(isleHeld('Norra', 'own'), opts);
  assert.equal(first.querySelector('path.rl-hold').getAttribute('fill-opacity'), null, 'unchanged: drawn at once');
  assert.equal(c.waiting(), 0);
  const pic = draw(isleHeld('Sudland', 'enemy'), opts);
  const hold = pic.querySelector('path.rl-hold');
  assert.ok(hold.classList.contains('rl-hold-enemy'));
  assert.equal(hold.getAttribute('fill-opacity'), '0');
  c.flush(300);
  assert.equal(hold.getAttribute('fill-opacity'), '0.5', 'the whole area at once, evenly, linear in time');
  c.flush(300);
  assert.equal(hold.getAttribute('fill-opacity'), null, 'full at the end');
  assert.equal(c.waiting(), 0);
  assert.equal(hold.getAttribute('data-from'), null, 'nothing says the side the taker came from');
});

test('a territory first seen, or under reduced motion, is filled at once', () => {
  forgetMarks();
  const c = clock();
  const opts = { clock: { now: c.now, frame: c.frame } };
  assert.equal(draw(isleHeld('Norra', 'own'), opts).querySelector('path.rl-hold').getAttribute('fill-opacity'), null);
  const pic = reduced(() => draw(isleHeld('Sudland', 'enemy'), opts));
  assert.equal(pic.querySelector('path.rl-hold').getAttribute('fill-opacity'), null);
  assert.equal(c.waiting(), 0);
});

// --- rule 6: the playback's hooks ----------------------------------------------------------------

test('the playback can place an own mark at any share of a step between two areas', () => {
  forgetMarks();
  const pic = draw(underWayMap(null, 'The Norra Levy', 'norra_hills'));
  const key = named(tmap(), 'The Norra Levy').piece.key;
  assert.deepEqual(motion.placeMark?.(pic, key, 'norra_hills', 'isle', 0.25), [100, 62.5]);
  const levy = markNamed(pic, 'The Norra Levy');
  assert.deepEqual(xyOf(levy), [100, 62.5]);
  assert.match(levy.getAttribute('transform'), /^translate\(100 62\.5\) scale\(/);
  assert.equal(motion.placeMark(pic, key, 'norra_hills', 'nowhere', 0.5), null, 'an area not drawn');
});

test('the playback cannot place an enemy report', () => {
  forgetMarks();
  const pic = draw(withEnemy(tmap()));
  assert.equal(motion.placeMark?.(pic, 'r-sud', 'isle', 'the_gulf', 0.5), null);
  assert.deepEqual(xyOf(markNamed(pic, 'The Sud Column')), [250, 100]);
});

test('a clock of world days runs linearly at its rate, then ends once', () => {
  const c = clock();
  const days = [];
  let ended = 0;
  motion.worldClock?.({ days: 5, msPerDay: 400, onDay: (d) => days.push(d), onEnd: () => { ended += 1; } }, { now: c.now, frame: c.frame });
  assert.deepEqual(days, [0]);
  c.flush(1000);
  assert.equal(days.at(-1), 2.5);
  c.flush(500);
  assert.equal(days.at(-1), 3.75);
  c.flush(500);
  assert.equal(days.at(-1), 5);
  assert.equal(ended, 1);
  assert.equal(c.waiting(), 0);
});

test('a still clock of world days goes straight to its end', () => {
  const days = [];
  let ended = 0;
  motion.worldClock?.({ days: 7, msPerDay: 400, onDay: (d) => days.push(d), onEnd: () => { ended += 1; } }, { still: true });
  assert.deepEqual([days, ended], [[7], 1]);
});

test('a stopped clock goes no further', () => {
  const c = clock();
  const days = [];
  const run = motion.worldClock?.({ days: 4, msPerDay: 100, onDay: (d) => days.push(d) }, { now: c.now, frame: c.frame });
  c.flush(100);
  run.stop();
  c.flush(100);
  assert.deepEqual(days, [0, 1]);
});

// --- rule 7: travel is linear ------------------------------------------------------------------

test('an own piece that moved slides there linearly, so that it reads as a rate', () => {
  forgetMarks();
  draw(underWayMap(null, 'The Norra Levy', 'isle'));
  const got = recording(() => draw(underWayMap(null, 'The Norra Levy', 'sudland_coast')));
  const slid = got.filter((a) => a.el.getAttribute('data-slide-from'));
  assert.equal(slid.length, 1);
  assert.equal(slid[0].how.easing, 'linear');
});

test('a share of a line is that share of its length, from its first point', () => {
  assert.deepEqual(motion.partOf?.([[0, 0], [10, 0], [10, 10]], 0.75), [[0, 0], [10, 0], [10, 5]]);
  assert.deepEqual(motion.partOf([[0, 0], [10, 0]], 0), [[0, 0], [0, 0]], 'nothing drawn yet: a line of no length');
  assert.deepEqual(motion.partOf([[0, 0], [10, 0]], 1), [[0, 0], [10, 0]]);
  assert.deepEqual(motion.between([0, 0], [10, 20], 0.3), [3, 6]);
});

// --- reduced motion: every piece where it stands, with its tag, and nothing moves ----------------

test('under reduced motion a piece under way stands where its days put it, with its tag, and nothing moves', () => {
  forgetMarks();
  const c = clock();
  draw(underWayMap(null, 'The Norra Levy', 'isle'), { clock: { now: c.now, frame: c.frame } });
  let pic = null;
  const got = recording(() => { pic = reduced(() => draw(underWayMap(), { clock: { now: c.now, frame: c.frame } })); });
  const levy = markNamed(pic, 'The Norra Levy');
  assert.deepEqual(xyOf(levy), [110, 110]);
  assert.equal(words(levy.querySelector('text.rl-tm-tag')), 'day 3 of 5 into The Gulf');
  assert.equal(got.length, 0);
  assert.equal(c.waiting(), 0);
});

test('a still drawing (the playback\'s frames) draws a piece on its way but neither draws a course on nor fills', () => {
  forgetMarks();
  const c = clock();
  draw(underWayMap(null), { clock: { now: c.now, frame: c.frame }, still: true });
  draw(isleHeld('Norra', 'own'), { still: true });
  const pic = draw(underWayMap(), { clock: { now: c.now, frame: c.frame }, still: true });
  const key = named(tmap(), 'The Norra Levy').piece.key;
  const levy = pic.querySelectorAll('g.rl-tm-mark').find((g) => g.getAttribute('data-key') === key);
  assert.deepEqual(xyOf(levy), [110, 110]);
  assert.equal(words(levy.querySelector('text.rl-tm-tag')), 'day 3 of 5 into The Gulf');
  draw(isleHeld('Sudland', 'enemy'), { clock: { now: c.now, frame: c.frame }, still: true });
  assert.equal(c.waiting(), 0);
});
