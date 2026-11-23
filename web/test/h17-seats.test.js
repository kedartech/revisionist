// Chamber seats and measure counts as bars (SBR), one test or more per plan rule: 1. a chamber is
// one bar split by bloc in proportion to its seats, with a line at the count the server sends for
// its open vote and that count written by it (no line with no measure on its way); 2. an open
// measure is a bar of yeas, seats not yet counted and nays with the same line, the count by bloc
// on a tap; 3. a segment opens its bloc's card; 4. a chamber of one bloc draws one segment, and a
// segment too narrow for its number carries it in its name only.
// Mutants: the line at half the seats and not at the carrying count; a segment sized by support
// and not by seats.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { fire, installDom, words } from './dom-fake.js';

installDom();
const home = await import('../js/views/realism-home.js');
const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');

/** A home block with one chamber of `seats` (one number per bloc) and one open measure counted `yeas` to `nays`, the line at `carries`. */
function floor(seats, { yeas = 0, nays = 0, carries = 120, support = null, measure = true } = {}) {
  const h = structuredClone(fixture.home);
  const keys = seats.map((_, i) => `b${i}`);
  h.groups = keys.map((k, i) => ({ key: k, name: `Bloc ${i}`, kind: 'party', support: support ? support[i] : 50, last_moved: null, feeds: {} }));
  const blocs = keys.map((k, i) => ({ group: k, name: `Bloc ${i}`, seats: seats[i], support: support ? support[i] : 50 }));
  h.chambers = [{
    key: 'assembly', blocs,
    measures: measure ? [{
      order_id: 'o1', key: 'levy', title: 'Levy act',
      votes: [{ vote: 'assembly', yeas, nays, carries, blocs: keys.map((k) => ({ group: k, yeas: 0, nays: 0 })) }],
    }] : [],
  }];
  return h;
}
const chamberOf = (h) => home.homeSheet(h).querySelector('[data-chamber="assembly"]');
const widths = (el) => el.querySelectorAll('.rl-home-seg').map((r) => Number(r.getAttribute('width')));
const near = (a, b) => Math.abs(a - b) < 1e-6;

for (const seats of [[200], [90, 60, 50], [60, 50, 40, 20, 14, 10, 6]]) {
  test(`rule 1: a chamber of ${seats.length} bloc(s) is one bar split by seats, with the line at the count sent`, () => {
    const total = seats.reduce((a, b) => a + b, 0);
    const bar = chamberOf(floor(seats, { carries: 120, support: seats.map((_, i) => 10 + i * 9) })).querySelector('.rl-home-seatbar');
    const w = widths(bar);
    assert.equal(w.length, seats.length);
    seats.forEach((n, i) => assert.ok(near(w[i], (100 * n) / total), `segment ${i} is ${n} of ${total}`));
    const line = bar.querySelector('.rl-home-carry');
    assert.ok(line);
    assert.ok(near(Number(line.getAttribute('x1')), (100 * 120) / total), 'at the sent count, not at half the seats');
    assert.match(words(bar.querySelector('.rl-home-seatnote')), /120 carry the vote/);
  });
}

test('rule 1: a chamber with no measure on its way draws no line and writes no count', () => {
  const bar = chamberOf(floor([90, 60, 50], { measure: false })).querySelector('.rl-home-seatbar');
  assert.equal(bar.querySelector('.rl-home-carry'), null);
  assert.doesNotMatch(words(bar.querySelector('.rl-home-seatnote')), /carry/);
});

test('rule 1: the line is the count the server sent and nothing the client works out', () => {
  const h = floor([90, 60, 50], { yeas: 10, nays: 10, carries: 77 });
  const line = chamberOf(h).querySelector('.rl-home-seatbar .rl-home-carry');
  assert.ok(near(Number(line.getAttribute('x1')), 38.5));
  delete h.chambers[0].measures[0].votes[0].carries;
  const bare = chamberOf(h);
  assert.equal(bare.querySelector('.rl-home-carry'), null);
  assert.doesNotMatch(words(bare.querySelector('.rl-home-line')), /carry it/);
  assert.ok(!/needed\s*\(/.test(read('js/views/realism-home.js')), 'no client majority count');
});

test('rule 2: an open measure is a bar of yeas, seats not yet counted and nays with the same line', () => {
  const total = 200;
  const m = chamberOf(floor([90, 60, 50], { yeas: 70, nays: 50, carries: 120 })).querySelector('.rl-home-measure');
  const segs = m.querySelectorAll('.rl-home-vseg');
  assert.deepEqual(segs.map((s) => s.getAttribute('data-kind')), ['yeas', 'open', 'nays']);
  assert.deepEqual(segs.map((s) => Number(s.getAttribute('width'))), [35, 40, 25]);
  assert.deepEqual(segs.map((s) => Number(s.getAttribute('x'))), [0, 35, 75]);
  assert.ok(near(Number(m.querySelector('.rl-home-carry').getAttribute('x1')), (100 * 120) / total));
  assert.equal(words(m.querySelector('.rl-home-line')), '120 yeas carry it. Counted today: 70 yea, 50 nay: short by 50');
});

test('rule 2: the count by bloc shows on a tap of the bar and hides on the next', () => {
  const m = chamberOf(floor([90, 60, 50], { yeas: 70, nays: 50 })).querySelector('.rl-home-measure');
  const tokens = m.querySelector('.rl-home-tokens');
  const bar = m.querySelector('.rl-home-votebar');
  assert.ok(tokens.hasAttribute('hidden'));
  fire(bar, 'click');
  assert.equal(bar.getAttribute('aria-expanded'), 'true');
  assert.ok(!tokens.hasAttribute('hidden'));
  assert.equal(tokens.querySelectorAll('.rl-home-token').length, 3);
  fire(bar, 'click');
  assert.ok(tokens.hasAttribute('hidden'));
});

test('rule 3: a segment opens its bloc\'s card, by tap and by Enter, and a second tap closes it', () => {
  const bar = chamberOf(floor([90, 60, 50])).querySelector('.rl-home-seatbar');
  const [first, second] = bar.querySelectorAll('.rl-home-seg');
  const card = bar.querySelector('.rl-home-bloccard');
  assert.ok(card.hasAttribute('hidden'));
  fire(second, 'click');
  assert.ok(!card.hasAttribute('hidden'));
  assert.equal(card.querySelector('.rl-home-group').getAttribute('data-group'), 'b1');
  first.dispatchEvent({ type: 'keydown', key: 'Enter', preventDefault() {} });
  assert.equal(card.querySelector('.rl-home-group').getAttribute('data-group'), 'b0');
  assert.equal(first.getAttribute('aria-pressed'), 'true');
  assert.equal(second.getAttribute('aria-pressed'), 'false');
  fire(first, 'click');
  assert.ok(card.hasAttribute('hidden'));
});

test('rule 3: a segment is keyboard-reachable and named', () => {
  const seg = chamberOf(floor([90, 60, 50])).querySelector('.rl-home-seg');
  assert.equal(seg.getAttribute('tabindex'), '0');
  assert.equal(seg.getAttribute('role'), 'button');
  assert.equal(seg.getAttribute('aria-label'), 'Bloc 0, 90 seats. Open its card');
});

test('rule 4: a chamber of one bloc draws one segment across the bar', () => {
  const bar = chamberOf(floor([200])).querySelector('.rl-home-seatbar');
  assert.deepEqual(widths(bar), [100]);
});

test('rule 4: a segment too narrow for its number carries it in its name only', () => {
  const bar = chamberOf(floor([170, 24, 6])).querySelector('.rl-home-seatbar');
  const segs = bar.querySelectorAll('.rl-home-seg');
  assert.equal(segs[0].getAttribute('data-narrow'), null);
  assert.equal(segs[2].getAttribute('data-narrow'), 'true');
  assert.equal(segs[2].getAttribute('aria-label'), 'Bloc 2, 6 seats. Open its card');
  assert.equal(words(bar.querySelector('.rl-home-seatnote')), 'Bloc 0 170 · Bloc 1 24 · Bloc 2 · 120 carry the vote');
});

test('the css draws the bars from tokens only', () => {
  const css = read('css/c-home.css');
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(/);
});
