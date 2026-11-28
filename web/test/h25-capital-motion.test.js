// Orders and blocs move on the Capital board, one test or more per rule, on a fake clock, on a
// seat built here with an assembly of three blocs and the neutrality bill on its way: 1. an
// order's marker on its track stands along the step that holds it at days held over the step's
// usual days (at the step's start, with its days held in words, while the usual days are a gap),
// and slides to the next stop when it is passed on; 2. an order that is held stops with its lock
// shown; 3. when a count changes, the blocs' parts of the track slide to their new widths and the
// count runs from the old number to the new; 4. an offer filed draws its part of the track in
// from the bloc that takes it; 5. a promise that came due marks itself once on the board and on
// the timeline. Reduced motion shows the end state of each.
// Mutants: a marker placed past its stop when held longer than usual; a held order drawn as on
// its way; a count run to a number the server did not send; a promise marked on every draw.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { beforeEach, mock, test } from 'node:test';

import { capitalLines } from './capital-line.js';
import { installDom, words } from './dom-fake.js';

const proto = Object.getPrototypeOf(installDom().createElement('div'));
// the fake has no CSSOM, no layout and no animations: each element keeps what is set on its
// style, a track's bar stands 100 px wide at 100 px a step, and `animate` is recorded
let played = [];
Object.defineProperty(proto, 'style', {
  configurable: true,
  get() {
    this._style ??= { props: {}, setProperty(k, v) { this.props[k] = String(v); }, getPropertyValue(k) { return this.props[k] ?? ''; } };
    return this._style;
  },
});
proto.animate = function animate(frames, opts) { played.push({ el: this, frames, opts }); return { cancel() {} }; };
proto.getBoundingClientRect = function rect() {
  const li = this.parentNode;
  const i = li?.parentNode ? li.parentNode.children.indexOf(li) : 0;
  return { left: 100 * i, width: 100, top: 0, height: 4 };
};
let reduce = false;
globalThis.matchMedia = (q) => ({ matches: reduce && q.includes('reduce'), media: q });
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
globalThis.requestAnimationFrame = (f) => setTimeout(() => f(0), 16);

const cap = await import('../js/views/realism-capital.js');
const tracks = await import('../js/views/realism-tracks.js');
const { needLines } = await import('../js/views/realism-needs.js');
const { timelineStrip } = await import('../js/views/realism-timeline.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));

const ORDER = 'o-neutrality';
const MEASURE = 'neutrality';
const DUES = { key: 'dues', sentence: 'Harbour dues lifted within the season', points: 2, days: 30, loss: 5 };

/**
 * The seat's view on 1900-04-10: Norra with an assembly of three blocs, the neutrality bill
 * four days with Sam Rayburn (a step of about eight), its vote at 120 yea and 40 nay (150 carry
 * it), Bloc One naming one price, no offer made and no promise. `change` edits it.
 */
function seat(change = () => {}) {
  const rv = structuredClone(fixture);
  rv.map = structuredClone(fixture.territory_map);
  rv.clock = { ...rv.clock, world_date: '1900-04-10' };
  rv.locks = null;
  rv.conferences = { conferences: [] };
  rv.stakes = { ...rv.stakes, contests: [], mandates: [] };
  rv.court.paths[0].steps[0].orders[0].held_days = 4;
  const assembly = [['b0', 'Bloc Zero', 100], ['b1', 'Bloc One', 60], ['b2', 'Bloc Two', 40]]
    .map(([group, name, seats]) => ({ group, name, seats, support: 50 }));
  rv.home = {
    ...structuredClone(fixture.home),
    groups: assembly.map((b) => ({ key: b.group, name: b.name, kind: 'party', support: 50, last_moved: null, feeds: { votes: 1 } })),
    chambers: [{ key: 'assembly', blocs: assembly, measures: [{ order_id: ORDER, key: MEASURE, title: 'Revising the Neutrality Act', votes: [{
      vote: 'assembly', yeas: 120, nays: 40, carries: 150,
      blocs: [{ group: 'b0', yeas: 90, nays: 0 }, { group: 'b1', yeas: 20, nays: 30 }, { group: 'b2', yeas: 10, nays: 10 }],
    }] }] }],
    themes: [],
    offers: [{ key: MEASURE, title: 'Revising the Neutrality Act', blocs: [
      { group: 'b0', name: 'Bloc Zero', prices: [], live: null },
      { group: 'b1', name: 'Bloc One', prices: [DUES], live: null },
      { group: 'b2', name: 'Bloc Two', prices: [], live: null },
    ] }],
    promises: [],
  };
  change(rv);
  rv.capitals = capitalLines(rv);
  return rv;
}

const vote = (rv) => rv.home.chambers[0].measures[0].votes[0];
const bill = (rv) => rv.court.paths[0];

/** The board drawn into the page, as the room draws it on each new view with the same kept state. */
function board(rv, state = { q: `vote:${ORDER}` }) {
  installDom();
  const el = cap.capitalBoard(rv, state, {});
  document.body.append(el);
  return el;
}

const marker = (el) => el.querySelector(`.rl-cap-path .rl-trk-marker[data-order="${ORDER}"]`);
const segOf = (m) => m.closest('li.rl-trk-seg');
const yea = (el, g) => el.querySelector(`.rl-cap-trackbox svg rect.rl-cap-yea[data-group="${g}"]`);
const playedOn = (el) => played.filter((p) => p.el === el);
const count = (el) => words(el.querySelector('.rl-cap-trackbox .rl-cap-count'));

beforeEach(() => {
  played = [];
  reduce = false;
  tracks.forgetDrawn();
  mock.timers.reset();
  mock.timers.enable({ apis: ['setTimeout'] });
});

// rule 1: an order's marker stands along its step, and slides to the next stop when passed on

test('an order\'s marker stands along the step that holds it at days held over the step\'s usual days', () => {
  const el = board(seat());
  const m = marker(el);
  assert.ok(m, 'the measure\'s order is a marker on its path\'s track');
  assert.equal(segOf(m).getAttribute('data-name'), 'Sam Rayburn');
  assert.equal(m.style.getPropertyValue('--rl-trk-at'), '50%', 'four days held of about eight');
  assert.match(words(el.querySelector('.rl-cap-where')), /With Sam Rayburn: 4 days held of about 8/);
});

test('an order held longer than its step\'s usual days stands at its stop, never past it', () => {
  const el = board(seat((rv) => { bill(rv).steps[0].orders[0].held_days = 30; }));
  const m = marker(el);
  assert.equal(segOf(m).getAttribute('data-name'), 'Sam Rayburn', 'still on the step that holds it');
  assert.equal(m.style.getPropertyValue('--rl-trk-at'), '100%');
  assert.match(words(el.querySelector('.rl-cap-where')), /30 days held of about 8/);
});

test('while the step\'s usual days are a gap, the marker stands at its start with its days held in words', () => {
  const el = board(seat((rv) => { bill(rv).steps[0].days = null; bill(rv).steps[0].orders[0].held_days = 31; }));
  assert.equal(marker(el).style.getPropertyValue('--rl-trk-at'), '0%');
  assert.match(words(el.querySelector('.rl-cap-where')), /With Sam Rayburn: 31 days held; no time stated/);
});

test('an order passed on slides from where it stood to the next stop', () => {
  const state = { q: `vote:${ORDER}` };
  board(seat(), state);
  assert.equal(played.length, 0, 'nothing moves the first time it is drawn');
  const el = board(seat((rv) => {
    const [o] = bill(rv).steps[0].orders.splice(0, 1);
    bill(rv).steps[1].orders.push({ ...o, held_days: 0 });
  }), state);
  const m = marker(el);
  assert.equal(segOf(m).getAttribute('data-name'), 'House committee clerk');
  mock.timers.tick(20);
  const [slide] = playedOn(m);
  assert.ok(slide, 'the marker slides');
  // from half along the first step (50 px) to the start of the second (100 px)
  assert.equal(slide.frames[0].transform, 'translateX(-50px)');
  assert.equal(slide.frames.at(-1).transform, 'none');
  assert.ok(slide.opts.duration > 0);
});

test('a marker further along its step slides there; a redraw with nothing changed moves nothing', () => {
  const state = { q: `vote:${ORDER}` };
  board(seat((rv) => { bill(rv).steps[0].orders[0].held_days = 2; }), state);
  const el = board(seat((rv) => { bill(rv).steps[0].orders[0].held_days = 6; }), state);
  mock.timers.tick(20);
  assert.equal(playedOn(marker(el))[0]?.frames[0].transform, 'translateX(-50px)', 'from a quarter to three quarters');
  played = [];
  board(seat((rv) => { bill(rv).steps[0].orders[0].held_days = 6; }), state);
  mock.timers.tick(20);
  assert.equal(played.length, 0);
});

test('with reduced motion the marker stands at its new place and nothing slides', () => {
  reduce = true;
  const state = { q: `vote:${ORDER}` };
  board(seat(), state);
  const el = board(seat((rv) => { bill(rv).steps[0].orders[0].held_days = 8; }), state);
  mock.timers.tick(20);
  assert.equal(marker(el).style.getPropertyValue('--rl-trk-at'), '100%');
  assert.equal(played.length, 0);
});

// rule 2: an order that is held stops with its lock shown

const HELD = { id: 'h-levy', words: 'March (Force Norra levy, To Isle)', who: 'Ilse Varg', reason: 'Held until Ilse Varg allows it.', held: '1900-04-02', asked: false, piece: null };

test('a held order stops at the one who holds it, with its lock shown, and goes no further', () => {
  const state = { q: 'held:h-levy' };
  const withHeld = (rv) => { rv.locks = { held: [HELD], asks: [] }; };
  board(seat(withHeld), state);
  const el = board(seat((rv) => { withHeld(rv); rv.clock.world_date = '1900-04-12'; }), state);
  const m = el.querySelector('.rl-cap-held .rl-trk-marker[data-order="h-levy"]');
  assert.ok(m, 'the held order is a marker on its track');
  assert.ok(m.classList.contains('locked'));
  assert.ok(m.querySelector('.rl-trk-lock'), 'its lock is shown');
  assert.equal(segOf(m).getAttribute('data-name'), 'Ilse Varg');
  assert.equal(m.style.getPropertyValue('--rl-trk-at'), '0%');
  const after = el.querySelectorAll('.rl-cap-held li.rl-trk-seg').slice(-1)[0];
  assert.equal(after.querySelector('.rl-trk-marker'), null, 'nothing past the lock');
  mock.timers.tick(20);
  assert.equal(played.length, 0, 'a held order does not move');
  assert.match(words(el.querySelector('.rl-cap-held')), /Held since 2 April 1900/);
});

// rule 3: a count that changed slides its blocs' parts and runs its number

test('when a count changes, the blocs\' parts slide to their new widths and the count runs from the old number to the new', () => {
  const state = { q: `vote:${ORDER}` };
  board(seat(), state);
  const el = board(seat((rv) => {
    Object.assign(vote(rv), { yeas: 150 });
    vote(rv).blocs[1] = { group: 'b1', yeas: 50, nays: 0 };
    vote(rv).nays = 10;
  }), state);
  const b1 = yea(el, 'b1');
  assert.equal(b1.getAttribute('width'), '25', 'its end width, 50 of 200');
  const [slide] = playedOn(b1);
  assert.ok(slide, 'the bloc\'s part slides');
  // was 20 of 200 at 45; now 50 of 200 at 45
  assert.equal(slide.frames[0].transform, 'translateX(45px) scaleX(0.4) translateX(-45px)');
  assert.equal(slide.frames.at(-1).transform, 'none');
  assert.equal(playedOn(yea(el, 'b0')).length, 0, 'a part that did not change does not move');
  assert.equal(count(el), '120 yea · 40 nay', 'the count starts at the old number');
  mock.timers.tick(slide.opts.duration / 2);
  const mid = count(el).match(/^(\d+) yea · (\d+) nay$/);
  assert.ok(Number(mid[1]) > 120 && Number(mid[1]) < 150, 'it runs');
  mock.timers.tick(slide.opts.duration);
  assert.equal(count(el), '150 yea · 10 nay', 'and ends on the count the server sent');
});

test('with reduced motion the new count stands at once and no part slides', () => {
  reduce = true;
  const state = { q: `vote:${ORDER}` };
  board(seat(), state);
  const el = board(seat((rv) => { vote(rv).yeas = 150; vote(rv).blocs[1].yeas = 50; }), state);
  assert.equal(count(el), '150 yea · 40 nay');
  assert.equal(played.length, 0);
});

// rule 4: an offer filed draws its part in from the bloc that takes it

test('an offer filed draws its bloc\'s part of the track in from the bloc', () => {
  const state = { q: `vote:${ORDER}` };
  board(seat(), state);
  const el = board(seat((rv) => { rv.home.offers[0].blocs[1].live = { price: 'dues', points: 2, mine: true }; }), state);
  const [drawIn] = playedOn(yea(el, 'b1'));
  assert.ok(drawIn, 'its part is drawn in');
  assert.equal(drawIn.frames[0].opacity, 0);
  assert.match(drawIn.frames[0].transform, /^translateY\(\d+px\)$/, 'up from the blocs under the track');
  assert.equal(drawIn.frames.at(-1).transform, 'none');
  assert.equal(playedOn(yea(el, 'b0')).length, 0, 'no other bloc\'s part');
  played = [];
  board(seat((rv) => { rv.home.offers[0].blocs[1].live = { price: 'dues', points: 2, mine: true }; }), state);
  assert.equal(played.length, 0, 'once, when it is filed');
});

test('with reduced motion an offer filed stands in its place', () => {
  reduce = true;
  const state = { q: `vote:${ORDER}` };
  board(seat(), state);
  board(seat((rv) => { rv.home.offers[0].blocs[1].live = { price: 'dues', points: 2, mine: true }; }), state);
  assert.equal(played.length, 0);
});

// rule 5: a promise that came due marks itself once, on the board and on the timeline

const promised = (day, standing = 'due') => (rv) => {
  rv.clock.world_date = day;
  rv.home.promises = [{ offer_id: 'f1', group: 'b1', name: 'Bloc One', title: 'Revising the Neutrality Act', sentence: DUES.sentence, standing, due: '1900-04-11', filed: '1900-04-01' }];
};
const promiseOn = (el) => el.querySelector('.rl-cap-promise[data-offer="f1"]');

test('a promise that came due marks itself once on the board', () => {
  const state = { q: `vote:${ORDER}` };
  const before = board(seat(promised('1900-04-10')), state);
  assert.equal(promiseOn(before).hasAttribute('data-came-due'), false);
  const el = board(seat(promised('1900-04-11')), state);
  assert.ok(promiseOn(el).hasAttribute('data-came-due'));
  assert.equal(playedOn(promiseOn(el)).length, 1);
  played = [];
  const again = board(seat(promised('1900-04-11', 'kept')), state);
  assert.equal(promiseOn(again).hasAttribute('data-came-due'), false, 'once');
  assert.equal(played.length, 0);
});

test('a promise first seen on the day it comes due marks itself; one long past does not', () => {
  assert.ok(promiseOn(board(seat(promised('1900-04-11')))).hasAttribute('data-came-due'));
  tracks.forgetDrawn();
  assert.equal(promiseOn(board(seat(promised('1900-04-20')))).hasAttribute('data-came-due'), false);
});

test('a promise that came due marks itself once on the timeline', () => {
  const strip = (rv) => timelineStrip(rv, needLines(rv));
  const mark = (s) => s.querySelector('svg.rl-tl-mark[data-tl-key="need:promise:f1"]');
  assert.equal(mark(strip(seat(promised('1900-04-10')))).hasAttribute('data-came-due'), false);
  const s = strip(seat(promised('1900-04-11')));
  assert.ok(mark(s).hasAttribute('data-came-due'));
  assert.equal(playedOn(mark(s)).length, 1);
  assert.equal(mark(strip(seat(promised('1900-04-11')))).hasAttribute('data-came-due'), false, 'once');
});

test('with reduced motion a promise that came due is marked without moving', () => {
  reduce = true;
  board(seat(promised('1900-04-10')));
  const el = board(seat(promised('1900-04-11')));
  assert.ok(promiseOn(el).hasAttribute('data-came-due'));
  assert.equal(played.length, 0);
});
