// The playback moves the pieces: a wake plays as a clock of world days. Every own piece that
// moved in it moves at once, each for the days its step took, so a fleet crosses three zones
// while an army makes one step; the clock runs at about 0.4 seconds a world day and a wake is
// held to about 20 seconds by running it faster, with the day shown as it runs. A refused step
// moves the piece toward the area, stops it and shows the reason. A battle's rounds show at its
// area on their days, a territory changing hands fills on its day, papers, orders and stakes
// appear beside the map on their days, and a piece raised appears at its place on its day.
// Skip ends it at once; reduced motion shows every frame still. Every timing runs on a fake clock.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const play = await import('../js/views/realism-playback.js');
const { api } = await import('../js/api.js');
const { realismRoom } = await import('../js/views/realism-room.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');
const TMAP = fixture.territory_map;
const [HERALD, KITES, LEVY] = TMAP.marks;
const keyOf = (m) => m.piece?.key ?? m.key;

/** A fake clock and animation-frame queue: `flush(ms)` runs one frame `ms` later. */
function clock() {
  let t = 0;
  let queue = [];
  return {
    now: () => t,
    frame: (cb) => { queue.push(cb); return queue.length; },
    flush(ms = 20) {
      t += ms;
      const run = queue;
      queue = [];
      for (const cb of run) cb(t);
      return run.length;
    },
    waiting: () => queue.length,
    get t() { return t; },
  };
}

const move = (on, m, left, entered, days) => ({ kind: 'move', on, piece: keyOf(m), left, entered, days });
const page = (number, steps, extra = {}) => ({
  number, opened: `${number} May 1900`, days_passed: 1, papers: 0, filed: [], settled: [], steps, ...extra,
});
const player = (pages, more = {}) => play.wakePlayer({
  pages, map: TMAP, shapes: SHAPES, record: fixture.record, comeBack: 'When you come back: nothing is due.', reduced: false, ...more,
});
/** The seat's map as it stands after `steps`: each moved piece in the area it last entered. */
function mapAfter(steps) {
  const map = structuredClone(TMAP);
  for (const s of steps.filter((x) => x.kind === 'move')) {
    const m = map.marks.find((x) => keyOf(x) === s.piece);
    m.piece.area = { ...m.piece.area, key: s.entered, name: map.areas.find((a) => a.key === s.entered).name };
  }
  return map;
}
const markOf = (el, m) => el.querySelectorAll('g.rl-tm-mark').find((g) => g.getAttribute('data-key') === keyOf(m)) ?? null;
const xyOf = (g) => [Number(g.getAttribute('data-x')), Number(g.getAttribute('data-y'))];
const labelOf = (el, key) => {
  const l = el.querySelectorAll('.rl-tm-label').find((g) => g.getAttribute('data-area') === key);
  return [Number(l.getAttribute('data-x')), Number(l.getAttribute('data-y'))];
};
const near = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]) < 0.05;
const shown = (el) => el.querySelectorAll('li.rl-plb-step').filter((li) => !li.hasAttribute('hidden'));
const kindsShown = (el) => shown(el).map((li) => li.getAttribute('data-kind'));

/** Run the clock to its end in `ms` frames, recording each mark's place after every frame. */
function trace(c, el, marks, ms = 20, cap = 5000) {
  const seen = marks.map(() => []);
  const note = () => marks.forEach((m, i) => { const g = markOf(el, m); seen[i].push({ t: c.t, xy: g ? xyOf(g) : null }); });
  note();
  for (let n = 0; c.waiting() && n < cap; n += 1) { c.flush(ms); note(); }
  return seen;
}

/** How long a mark was moving: from the last frame it stood where it began to the first it reached where it ended. */
function movingFor(points) {
  const changes = points.filter((p, i) => i && p.xy && points[i - 1].xy && !near(p.xy, points[i - 1].xy));
  if (!changes.length) return 0;
  const first = points.indexOf(changes[0]);
  return changes.at(-1).t - points[first - 1].t;
}

// rule 1: a clock of world days; each piece moves for the days its step took, all at once

test('two pieces with steps of 1 and 5 days are on screen moving for times in that ratio, both at once', () => {
  installDom();
  const c = clock();
  const steps = [move('1900-04-03', LEVY, 'norra_plain', 'norra_hills', 1), move('1900-04-07', KITES, 'norra_plain', 'the_gulf', 5)];
  const el = player([page(2, steps)], { clock: c, map: mapAfter(steps) });
  const [levy, kites] = trace(c, el, [LEVY, KITES]);
  const a = movingFor(levy);
  const b = movingFor(kites);
  assert.ok(a > 0 && b > 0, `both moved: ${a} ${b}`);
  assert.ok(Math.abs(b / a - 5) < 0.3, `5 to 1, got ${b} to ${a}`);
  // both set off on the clock's first day: the one-day step is done before the five-day one is a quarter along
  const firstMoved = (pts) => pts.findIndex((p, i) => i && !near(p.xy, pts[i - 1].xy));
  assert.equal(firstMoved(levy), firstMoved(kites));
});

test('a piece travels linearly from the area it left toward the one it entered, at the share of its days gone', () => {
  installDom();
  const c = clock();
  const el = player([page(2, [move('1900-04-06', KITES, 'norra_plain', 'the_gulf', 4)])], { clock: c });
  const from = labelOf(el, 'norra_plain');
  const to = labelOf(el, 'the_gulf');
  assert.ok(near(xyOf(markOf(el, KITES)), from), 'at the start it stands where it left');
  c.flush(play.DAY_MS * 2); // two of its four days
  const mid = xyOf(markOf(el, KITES));
  assert.ok(near(mid, [(from[0] + to[0]) / 2, (from[1] + to[1]) / 2]), `half way: ${mid}`);
});

test('a fleet crosses three zones while an army makes one step', () => {
  installDom();
  const c = clock();
  const steps = [
    move('1900-04-02', HERALD, 'norra_plain', 'the_gulf', 1),
    move('1900-04-03', HERALD, 'the_gulf', 'open_sea', 1),
    move('1900-04-04', HERALD, 'open_sea', 'isle', 1),
    move('1900-04-04', LEVY, 'norra_plain', 'norra_hills', 3),
  ];
  const el = player([page(2, steps)], { clock: c, map: mapAfter(steps) });
  const at = (key) => labelOf(el, key);
  const herald = () => xyOf(markOf(el, HERALD));
  c.flush(play.DAY_MS);
  assert.ok(near(herald(), at('the_gulf')), 'day one: the first zone');
  c.flush(play.DAY_MS);
  assert.ok(near(herald(), at('open_sea')), 'day two: the second');
  const levy = xyOf(markOf(el, LEVY));
  assert.ok(!near(levy, at('norra_hills')) && !near(levy, at('norra_plain')), 'the army is still on its step');
  c.flush(play.DAY_MS);
  assert.ok(near(herald(), at('isle')), 'day three: the third');
});

// rule 2: about 0.4 s a world day, a wake held to about 20 s, the day shown as it runs

test('the clock runs at 0.4 seconds a world day and a long wake is held to 20 seconds', () => {
  assert.equal(play.DAY_MS, 400);
  assert.equal(play.WAKE_MS, 20_000);
  assert.equal(play.msPerDay(10), 400);
  assert.equal(play.msPerDay(100), 200);
  installDom();
  const c = clock();
  let ended = 0;
  player([page(2, [move('1900-06-09', KITES, 'norra_plain', 'the_gulf', 100)])], { clock: c, onEnd: () => { ended += 1; } });
  let n = 0;
  while (c.waiting() && n < 5000) { c.flush(100); n += 1; }
  assert.ok(c.t >= 20_000 && c.t <= 20_200, `held to 20 s: ${c.t}`);
});

test('the day shows as it runs, in words and as a bar', () => {
  installDom();
  const c = clock();
  const el = player([page(2, [move('1900-04-06', KITES, 'norra_plain', 'the_gulf', 4)])], { clock: c });
  const day = () => words(el.querySelector('.rl-plb-day'));
  assert.match(day(), /2 April 1900/);
  assert.match(day(), /day 1 of 4/);
  c.flush(play.DAY_MS * 2 + 10);
  assert.match(day(), /4 April 1900/);
  assert.match(day(), /day 3 of 4/);
  const fill = el.querySelector('.rl-plb-day rect.rl-plb-clock-fill');
  assert.ok(fill, 'the days gone are a bar');
  assert.ok(Math.abs(Number(fill.getAttribute('width')) - 50.5) < 2, fill.getAttribute('width'));
});

// rule 3: a refused step moves toward the area, stops, and shows the reason

test('a refused step moves the piece toward the area, stops it short and shows the reason', () => {
  installDom();
  const c = clock();
  const halt = { kind: 'halt', on: '1900-04-05', piece: keyOf(KITES), area: 'norra_plain', to: 'the_gulf', reason: 'too little fuel' };
  const el = player([page(2, [halt, { kind: 'paper', on: '1900-04-07', paper: 'p', title: 'Later' }])], { clock: c });
  const from = labelOf(el, 'norra_plain');
  const to = labelOf(el, 'the_gulf');
  const [pts] = trace(c, el, [KITES], 20, 60);
  const moved = pts.filter((p) => !near(p.xy, from));
  assert.ok(moved.length, 'it set off toward the area');
  assert.ok(pts.every((p) => !near(p.xy, to)), 'it never reached the area');
  const dist = (p) => Math.hypot(p.xy[0] - from[0], p.xy[1] - from[1]);
  const stopped = Math.max(...pts.map(dist));
  assert.ok(stopped <= Math.hypot(to[0] - from[0], to[1] - from[1]) * play.HALT_SHARE + 0.05);
  const li = el.querySelectorAll('li.rl-plb-step').find((x) => x.getAttribute('data-kind') === 'halt');
  assert.match(words(li), /too little fuel/);
  assert.ok(markOf(el, KITES).classList.contains('rl-plb-refused') || !c.waiting(), 'the stopped piece is marked');
});

// rule 4: a battle's rounds at its area on their days; a territory changing hands fills on its day

test('a battle\'s rounds show at its area on their days, its losses drawn as pips', () => {
  installDom();
  const c = clock();
  const el = player([page(2, [move('1900-04-16', LEVY, 'norra_plain', 'norra_hills', 3)])], { clock: c, battles: fixture.battles });
  const area = () => el.querySelectorAll('path.rl-area[data-area="sudland_coast"]')[0];
  assert.ok(!area().classList.contains('rl-plb-battle'), 'no fighting before its first day');
  assert.equal(kindsShown(el).filter((k) => k === 'round').length, 0);
  c.flush(play.DAY_MS + 10); // 14 April, the first round
  assert.ok(area().classList.contains('rl-plb-battle'));
  assert.equal(kindsShown(el).filter((k) => k === 'round').length, 1);
  c.flush(play.DAY_MS);
  const rounds = shown(el).filter((li) => li.getAttribute('data-kind') === 'round');
  assert.equal(rounds.length, 2);
  assert.match(words(rounds[0]), /The Sudland Coast/);
  assert.equal(rounds[0].querySelectorAll('.rl-plb-pip.rl-plb-lost').length, 1);
  assert.equal(rounds[1].querySelectorAll('.rl-plb-pip.rl-plb-lost').length, 1);
  assert.equal(rounds[1].querySelectorAll('.rl-plb-pip.rl-plb-foe').length, 0);
});

test('a round outside the wake\'s days is not played', () => {
  installDom();
  const el = player([page(2, [move('1900-04-03', LEVY, 'norra_plain', 'norra_hills', 1)])], { reduced: true, battles: fixture.battles });
  assert.equal(el.querySelectorAll('li.rl-plb-step[data-kind="round"]').length, 0);
});

test('a territory changing hands fills on its day, not before', () => {
  installDom();
  const c = clock();
  const map = structuredClone(TMAP);
  map.areas.find((a) => a.key === 'isle').holder = { key: 's', name: 'Sudland', relation: 'enemy' };
  const holder = { kind: 'holder', on: '1900-04-05', area: 'isle', holder: { key: 's', name: 'Sudland', relation: 'enemy' }, was: { key: 'n', name: 'Norra', relation: 'own' } };
  const el = player([page(2, [move('1900-04-06', LEVY, 'norra_plain', 'norra_hills', 4), holder])], { clock: c, map });
  const tone = () => el.querySelectorAll('path.rl-hold[data-area="isle"]')[0];
  assert.equal(tone().getAttribute('fill-opacity'), '0');
  c.flush(play.DAY_MS * 2);
  assert.equal(tone().getAttribute('fill-opacity'), '0', 'two days in: not yet');
  c.flush(play.DAY_MS + 10);
  c.flush(300);
  const mid = Number(tone().getAttribute('fill-opacity'));
  assert.ok(mid > 0 && mid < 1, `filling: ${mid}`);
  for (let n = 0; n < 100 && c.waiting(); n += 1) c.flush(50);
  assert.equal(tone().getAttribute('fill-opacity'), null);
});

// rule 5: papers, orders and stakes keep their lines beside the map, each on its day

test('papers, orders and stakes appear beside the map each on its day, in the order of the days', () => {
  installDom();
  const c = clock();
  const order = fixture.record.orders[0];
  const steps = [
    { kind: 'stake', on: '1900-04-06', name: 'The Gulf crossing', what: 'moved' },
    { kind: 'paper', on: '1900-04-03', paper: 'p1', title: 'The harbour count' },
    move('1900-04-06', LEVY, 'norra_plain', 'norra_hills', 5),
    { kind: 'order', on: '1900-04-04', order: order.id, what: 'filed' },
  ];
  const el = player([page(2, steps)], { clock: c });
  assert.deepEqual(kindsShown(el), []);
  c.flush(play.DAY_MS + 10);
  assert.deepEqual(kindsShown(el), []);
  c.flush(play.DAY_MS);
  assert.deepEqual(kindsShown(el), ['paper']);
  c.flush(play.DAY_MS);
  assert.deepEqual(kindsShown(el), ['paper', 'order']);
  c.flush(play.DAY_MS * 2);
  assert.deepEqual(kindsShown(el), ['paper', 'order', 'move', 'stake']);
  assert.match(words(el.querySelector('.rl-plb-now')), /The Gulf crossing/);
});

// rule 6: a piece raised appears at its place on its day

test('a piece raised appears at its place on its day', () => {
  installDom();
  const c = clock();
  const raised = { kind: 'raised', on: '1900-04-04', piece: keyOf(KITES), name: 'The Norra Kites', place: 'Nordhafen', area: 'norra_plain' };
  const el = player([page(2, [move('1900-04-06', LEVY, 'norra_plain', 'norra_hills', 5), raised])], { clock: c });
  const kites = () => markOf(el, KITES);
  assert.equal(kites().getAttribute('visibility'), 'hidden');
  c.flush(play.DAY_MS * 2 + 10);
  assert.equal(kites().getAttribute('visibility'), 'hidden');
  c.flush(play.DAY_MS);
  assert.equal(kites().getAttribute('visibility'), null);
  assert.ok(near(xyOf(kites()), labelOf(el, 'norra_plain')));
  const li = el.querySelectorAll('li.rl-plb-step').find((x) => x.getAttribute('data-kind') === 'raised');
  assert.equal(words(li.querySelector('.rl-plb-cap')), 'The Norra Kites was raised at Nordhafen');
});

// keeps: Skip ends it at once; reduced motion is still; only the steps sent are played

test('Skip ends the playback at once: every line shows, every piece stands where the map has it, and the clock stops', () => {
  installDom();
  const c = clock();
  let ended = 0;
  const el = player([page(2, [move('1900-04-07', KITES, 'norra_plain', 'the_gulf', 5)]), page(3, [move('1900-04-12', LEVY, 'norra_plain', 'norra_hills', 2)])], { clock: c, onEnd: () => { ended += 1; } });
  const home = labelOf(el, 'norra_plain');
  c.flush(play.DAY_MS * 2);
  assert.ok(!near(xyOf(markOf(el, KITES)), home));
  buttons(el, 'Skip')[0].click();
  assert.equal(ended, 1);
  assert.ok(el.querySelectorAll('ol.rl-plb-frames li').every((li) => !li.hasAttribute('hidden')));
  assert.ok(near(xyOf(markOf(el, KITES)), home), 'back where the map stands it');
  c.flush(play.DAY_MS);
  assert.ok(near(xyOf(markOf(el, KITES)), home), 'nothing moves after Skip');
  assert.equal(c.waiting(), 0, 'no frame is asked for after Skip');
  for (let n = 0; n < 20; n += 1) c.flush(play.DAY_MS);
  assert.ok(near(xyOf(markOf(el, KITES)), home));
  assert.equal(ended, 1);
});

test('several wakes play in turn, the next once the last has run its days', () => {
  installDom();
  const c = clock();
  const el = player([page(2, [move('1900-04-03', KITES, 'norra_plain', 'the_gulf', 1)]), page(3, [move('1900-04-12', LEVY, 'norra_plain', 'norra_hills', 2)], { days_passed: 4 })], { clock: c });
  const wakesShown = () => el.querySelectorAll('li.rl-plb-wake').filter((li) => !li.hasAttribute('hidden')).length;
  assert.equal(wakesShown(), 1);
  for (let n = 0; n < 30; n += 1) c.flush(20);
  assert.equal(wakesShown(), 2);
  assert.ok(near(xyOf(markOf(el, LEVY)), labelOf(el, 'norra_plain')), 'the second wake starts its piece where it left');
});

test('under reduced motion every frame stands still and no frame is asked for', () => {
  installDom();
  const c = clock();
  const el = player([page(2, [move('1900-04-07', KITES, 'norra_plain', 'the_gulf', 5)])], { clock: c, reduced: true });
  assert.equal(c.waiting(), 0);
  assert.ok(el.classList.contains('still'));
  assert.ok(el.querySelectorAll('ol.rl-plb-frames li').every((li) => !li.hasAttribute('hidden')));
  assert.equal(el.querySelector('.rl-plb-day'), null);
});

test('only the steps sent are played: a piece with no step never moves', () => {
  installDom();
  const c = clock();
  const el = player([page(2, [move('1900-04-07', KITES, 'norra_plain', 'the_gulf', 5)])], { clock: c });
  const [herald] = trace(c, el, [HERALD]);
  assert.equal(movingFor(herald), 0);
});

// catch-up: the room plays each wake it holds the same way, with the seat's own battles

test('the room\'s playback of a wake carries the rounds of the seat\'s own battles fought in it', async () => {
  const doc = installDom();
  const id = `h24-${Math.random()}`;
  globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
  api.realism = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  api.catchup = async (body = {}) => (body.first === 3
    ? { first: 3, last: 3, pages: [page(3, [move('1900-04-16', LEVY, 'norra_plain', 'norra_hills', 3)])] }
    : { first: 3, last: 2, pages: [] });
  const rv = { ...structuredClone(fixture), documents: fixture.listing, map: TMAP, wake_tick: 1 };
  rv.record.wake.days_passed = 6;
  const game = { id, name: 'Toy', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'Ilse' } } };
  const ctx = { me: { account: { handle: 'josh' }, game }, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {} };
  doc.body.append(realismRoom(ctx));
  for (let n = 0; n < 4; n += 1) await new Promise((resolve) => setTimeout(resolve, 0));
  const played = doc.body.querySelector('section.rl-plb');
  assert.ok(played, 'the wake plays');
  assert.equal(played.querySelectorAll('li.rl-plb-step[data-kind="round"]').length, 2);
  delete globalThis.localStorage;
});

// the look: motion's own sheet, linked from the page, with colours from the tokens only

test('the playback\'s motion has its own sheet, linked from the page, with no colour of its own', () => {
  const css = read('css/c-motion.css');
  assert.match(read('index.html'), /<link rel="stylesheet" href="\/css\/c-motion.css">/);
  assert.match(css, /\.rl-plb-day/);
  assert.match(css, /\.rl-plb-pip/);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/);
  assert.match(css, /prefers-reduced-motion/);
});
