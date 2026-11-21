// The score you can see: the stakes strip opens with one line per aim, then the degree of the
// win as sent, the drift from history and the days to the season's end; a decided contest shows
// its winner; the Board's pin carries the same aims as chips, drawn once; tapping an aim opens
// its drill-down.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { realismRoom } = await import('../js/views/realism-room.js');
const { stakesStrip, aimList } = await import('../js/views/realism-stakes.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');
const stakes = () => structuredClone(fixture.stakes);

function room(over = {}) {
  const doc = installDom();
  api.realism = async () => ({});
  const rv = { ...fixture, documents: fixture.listing, wake_tick: 1, ...over };
  const me = { account: { handle: 'josh' }, game: { id: `g-${Math.random()}`, name: 'Autumn 1941', view: { realism: rv, seat: { name: 'Franklin D. Roosevelt' } } } };
  const root = realismRoom({ me, refresh: async () => {}, go: () => {} });
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  return root;
}

const aimRows = (el) => el.querySelectorAll('.rl-aim');
const aimTexts = (el) => aimRows(el).map((r) => words(r.querySelector('.rl-aim-text')));
const chip = (row) => words(row.querySelector('.rl-aim-chip'));

test('the fixture carries aims in each status, a degree, a drift, the season days and a decided contest', () => {
  const s = fixture.stakes;
  assert.ok(s.aims.length >= 2);
  assert.ok(new Set(s.aims.map((a) => a.status)).size >= 2, 'more than one status');
  assert.ok(s.decided.length > 0 && 'season_days_left' in s && 'drift' in s && 'degree' in s);
});

test('rule 1: one line per aim, in the data\'s order, each with its status chip', () => {
  const s = stakes();
  const strip = stakesStrip(s);
  const rows = aimRows(strip);
  assert.equal(rows.length, s.aims.length);
  assert.deepEqual(aimTexts(strip), s.aims.map((a) => a.text));
  const word = { met: 'Met', at_risk: 'At risk', failed: 'Failed' };
  s.aims.forEach((a, i) => assert.equal(chip(rows[i]), word[a.status], a.text));
  rows.forEach((r, i) => assert.equal(r.getAttribute('data-status'), s.aims[i].status));
});

test('rule 1: the aim lines come before the tiles, then the degree, the drift and the days to the season\'s end', () => {
  const s = stakes();
  s.degree = 'win';
  s.drift = 3;
  s.season_days_left = 48;
  const strip = stakesStrip(s);
  const order = strip.children.map((k) => k.getAttribute('class'));
  assert.ok(order.indexOf('rl-aims') < order.indexOf('rl-score'), 'aims, then the score line');
  assert.ok(order.indexOf('rl-score') < order.indexOf('rl-stakes-list'), 'then the tiles');
  const facts = strip.querySelectorAll('.rl-score-item').map((e) => words(e));
  assert.equal(facts.length, 3);
  assert.match(facts[0], /win/i);
  assert.match(facts[1], /drift/i);
  assert.match(facts[1], /3/);
  assert.match(facts[2], /48 days/);
});

test('the season\'s end shows from the days sent, one day, and the last day; none sent, no line', () => {
  const at = (n) => stakesStrip({ ...stakes(), season_days_left: n }).querySelector('.rl-score-end');
  assert.match(words(at(48)), /Season ends in 48 days/);
  assert.match(words(at(1)), /Season ends in 1 day$/);
  assert.match(words(at(0)), /Season ends today/);
  assert.equal(at(null), null);
  assert.equal(at(undefined), null);
});

test('the degree is the one the data sends: full win, win, or no line; the client counts nothing', () => {
  const degree = (v, aims) => stakesStrip({ ...stakes(), aims: aims ?? stakes().aims, degree: v }).querySelector('.rl-score-degree');
  assert.match(words(degree('full win')), /full win/i);
  assert.match(words(degree('win')), /win/i);
  assert.equal(degree(null), null);
  const allMet = stakes().aims.map((a) => ({ ...a, status: 'met' }));
  assert.equal(degree(null, allMet), null, 'three met aims with no degree sent draw no degree');
  const noneMet = stakes().aims.map((a) => ({ ...a, status: 'failed' }));
  assert.match(words(degree('win', noneMet)), /win/i, 'the degree sent is shown whatever the aims say');
});

test('no points total anywhere on the strip', () => {
  const text = words(stakesStrip(stakes()));
  assert.doesNotMatch(text, /\bpoints?\b|\bscore:|\btotal\b/i);
});

test('rule 2: a contest tile keeps its lean and a decided contest shows its winner', () => {
  const s = stakes();
  const strip = stakesStrip(s);
  const tiles = strip.querySelectorAll('.rl-stake');
  const decided = tiles.filter((t) => t.getAttribute('data-kind') === 'decided');
  assert.equal(decided.length, s.decided.length);
  assert.equal(words(decided[0].querySelector('.rl-stake-name')), s.decided[0].name);
  assert.match(words(decided[0].querySelector('.rl-stake-winner')), new RegExp(`Won by ${s.decided[0].winner}`));
  assert.equal(decided[0].querySelector('.rl-stake-days'), null, 'no days left on a decided contest');
  const open = tiles.filter((t) => t.getAttribute('data-kind') === 'contest');
  assert.equal(open.length, s.contests.length);
  assert.ok(open.every((t) => !t.querySelector('.rl-stake-winner')), 'an open contest names no winner');
  assert.ok(open.some((t) => t.querySelector('.rl-stake-lean')), 'a lean still shows');
});

test('a decided contest with no named winner says it was decided', () => {
  const s = { contests: [], mandates: [], decided: [{ name: 'X', sides: ['A', 'B'], winner: null }] };
  assert.match(words(stakesStrip(s).querySelector('.rl-stake-winner')), /Decided/);
});

test('the strip draws with aims alone, and not without any of them', () => {
  assert.ok(stakesStrip({ aims: stakes().aims }));
  assert.equal(stakesStrip({ contests: [], mandates: [], decided: [], aims: [] }), null);
});

test('rule 4: an aim opens its drill-down on a tap; the chips are the default', () => {
  const s = stakes();
  const strip = stakesStrip(s);
  const row = aimRows(strip)[1];
  const a = s.aims[1];
  const toggle = row.querySelector('button');
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  const more = row.querySelector('.rl-aim-more');
  assert.ok(more.hasAttribute('hidden'), 'closed by default');
  toggle.click();
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  assert.ok(!more.hasAttribute('hidden'));
  const text = words(more);
  assert.ok(text.includes(a.rule), 'the success rule');
  assert.ok(text.includes(a.reason), 'the reason for its status');
  for (const leaf of a.leaves) for (const e of leaf.evidence) assert.ok(text.includes(e), 'the evidence');
  assert.match(text, /13 November 1941/, 'the deadline');
  toggle.click();
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  assert.ok(more.hasAttribute('hidden'));
});

test('rule 4: a period reads from its opening to its deadline; a hidden leaf is marked as uncertain', () => {
  const aim = {
    aim: 1, text: 'T', source: 'post', status: 'at_risk', rule: 'R.', opens: '1941-12-01', deadline: '1942-01-05',
    leaves: [{ reads: 'hidden thing', seen: 'uncertain', holds: false, evidence: [] }, { reads: 'open thing', seen: 'public', holds: true, evidence: ['It is so.'] }],
    reason: 'Not yet.',
  };
  const more = aimList([aim]).querySelector('.rl-aim-more');
  const text = words(more);
  assert.match(text, /1 December 1941/);
  assert.match(text, /5 January 1942/);
  const leaves = more.querySelectorAll('.rl-aim-leaf');
  assert.equal(leaves.length, 2);
  assert.ok(leaves[0].querySelector('.rl-aim-uncertain'), 'the hidden leaf is marked');
  assert.match(words(leaves[0]), /hidden from you/i);
  assert.equal(leaves[1].querySelector('.rl-aim-uncertain'), null, 'a seen leaf is not');
});

test('an aim with no deadline and no opening names no period', () => {
  const aim = { aim: 1, text: 'T', status: 'met', rule: 'R.', opens: null, deadline: null, leaves: [], reason: 'It holds now.' };
  assert.equal(aimList([aim]).querySelector('.rl-aim-period'), null);
});

test('an open drill-down stays open when the room draws again', () => {
  const s = stakes();
  aimRows(stakesStrip(s))[0].querySelector('button').click();
  const again = aimRows(stakesStrip(s))[0];
  assert.equal(again.querySelector('button').getAttribute('aria-expanded'), 'true');
  again.querySelector('button').click();
});

test('only the seat\'s own aims are drawn: the strip holds the data\'s aims and nothing else', () => {
  const s = stakes();
  s.aims = [s.aims[0]];
  const strip = stakesStrip(s);
  assert.deepEqual(aimTexts(strip), [s.aims[0].text]);
  const other = fixture.stakes.aims.slice(1).map((a) => a.text);
  const all = words(strip);
  for (const t of other) assert.ok(!all.includes(t), t);
  assert.equal(aimRows(stakesStrip({ ...s, aims: undefined, contests: s.contests })).length, 0);
});

test('rule 3: on the Board the pinned aims carry the chips and the strip does not draw them again', () => {
  const root = room();
  buttons(root.querySelector('.rl-viewswitch'), 'Board')[0].click();
  const pin = root.querySelector('.rl-pin');
  assert.ok(pin, 'the pin');
  assert.deepEqual(aimTexts(pin), fixture.stakes.aims.map((a) => a.text));
  aimRows(pin).forEach((r, i) => assert.ok(chip(r), `chip ${i}`));
  assert.equal(aimRows(root).length, fixture.stakes.aims.length, 'each aim once on the page');
  assert.equal(root.querySelectorAll('.rl-aims').length, 1);
  assert.ok(root.querySelector('.rl-stakes .rl-score'), 'the strip keeps the score line');
  assert.equal(root.querySelector('.rl-stakes .rl-aims'), null);
});

test('on the Desk view the strip draws the aim lines', () => {
  const root = room();
  buttons(root.querySelector('.rl-viewswitch'), 'Desk')[0].click();
  assert.equal(aimRows(root.querySelector('.rl-stakes')).length, fixture.stakes.aims.length);
  assert.equal(root.querySelector('.rl-pin'), null);
});

test('the Board\'s pin falls back to the plain aims when the seat has no scored aims', () => {
  const root = room({ stakes: { contests: [], mandates: [] } });
  buttons(root.querySelector('.rl-viewswitch'), 'Board')[0].click();
  const pin = root.querySelector('.rl-pin');
  assert.equal(aimRows(pin).length, 0);
  assert.ok(words(pin).includes(fixture.desk.aims[0]));
});

test('the file builds text nodes only, and its styles use tokens only and keep the page inside the viewport', () => {
  assert.doesNotMatch(read('js/views/realism-stakes.js'), /innerHTML|outerHTML|insertAdjacentHTML|style=/);
  const css = read('css/c-stakes.css').replace(/\/\*[\s\S]*?\*\//g, '');
  for (const sel of ['.rl-aims', '.rl-aim-chip', '.rl-aim-more', '.rl-score', '.rl-stake-winner']) assert.ok(css.includes(sel), sel);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(/, 'tokens only');
  assert.match(css, /min-height: 44px/, 'a touch target');
  assert.match(css, /overflow-wrap: anywhere/, 'long text wraps inside the viewport');
});
