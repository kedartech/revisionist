// The office question on screen (OFB), one test or more per rule, on the seat fixture's Norra:
// 1. the home sheet shows the holder's footing, how far from his line and for how long, and the
// Capital board keeps it in view at its top; 2. an open question is a panel with the office, why
// it opened, the day it sits and who decides it, a chamber's count for a vote and a table of the
// members for a council or one person; 3. a member files his sealed choice, changes it, and reads
// it back as the server sends it; 4. each election ahead is a line with its day and the seats as
// they would fall; 5. once decided the public result takes the panel's place. Also: the office is
// a question in the Capital list, the needs list carries a member's unfiled choice, and the phone
// width keeps the panel in one column.
// Mutants: another member's choice drawn; a footing worked out by the client; the panel kept once
// the result is public; a choice drawn the server did not read back.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { fire, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { realismRoom } = await import('../js/views/realism-room.js');
const { setRoomLayout } = await import('../js/views/realism-sheets.js');
const cap = await import('../js/views/realism-capital.js');
const office = await import('../js/views/realism-office.js');
const { homeSheet } = await import('../js/views/realism-home.js');
const { needLines } = await import('../js/views/realism-needs.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');
const Q = fixture.home.office[0].question_id;

/** An open question on Kara Lind's post, decided `way`; the seat a member when `mine`. */
const question = (way, change = {}) => ({
  ...structuredClone(fixture.home.office[0]),
  way,
  chamber: way === 'vote' ? 'assembly' : null,
  deciders: way === 'council' ? ['Kara Lind', 'Ilse Brandt', 'Otto Wern'] : way === 'person' ? ['Ilse Brandt'] : [],
  count: way === 'vote' ? { yeas: 40, nays: 10 } : null,
  ...change,
});

/** The seat's view on the fixture, with the home block's office keys replaced by `home`. */
function seat(home = {}) {
  const rv = structuredClone(fixture);
  rv.map = structuredClone(fixture.territory_map);
  rv.documents = structuredClone(fixture.listing);
  rv.wake_tick = 1;
  rv.style = 'free';
  rv.battles = [];
  rv.clock = { ...rv.clock, world_date: '1900-04-10' };
  rv.wake = { ...rv.wake, deadline: '2999-01-01T00:00:00+00:00', you_committed: false, humans: 1, committed: 0 };
  rv.home = { ...structuredClone(fixture.home), office: [], footing: [], results: [], elections: [], ...home };
  return rv;
}

/** The board alone, with a record of what its controls asked of the room. */
function board(rv, state = {}) {
  installDom();
  const asked = [];
  const on = Object.fromEntries(['board', 'person', 'map', 'ask', 'openAsk', 'conference', 'speak', 'full', 'officeVote'].map((k) => [k, (...a) => asked.push([k, ...a])]));
  const el = cap.capitalBoard(rv, state, on);
  document.body.append(el);
  return { el, asked };
}

const FOOT = fixture.home.footing[0];

// 1. the holder's footing
test('the home sheet shows the holder how far under his line he stands and for how long', () => {
  installDom();
  const el = homeSheet(seat({ footing: [FOOT] }).home, {});
  const foot = el.querySelector('.rl-office-footing');
  assert.ok(foot, 'the footing is drawn');
  assert.match(words(foot), /General of the Norra Levy: Support 20, 10 under its line of 30, 15 days under/);
});

test('above his line the footing says how far over, with no days under', () => {
  installDom();
  const el = homeSheet(seat({ footing: [{ ...FOOT, support: 42.5, days: 0 }] }).home, {});
  assert.match(words(el.querySelector('.rl-office-footing')), /Support 42.5, 12.5 over its line of 30/);
  assert.doesNotMatch(words(el.querySelector('.rl-office-footing')), /days? under/);
});

test('the days under are the server\'s: the client counts none of its own', () => {
  installDom();
  // support under the line with days 0 (the day it fell): no days are made up
  const el = homeSheet(seat({ footing: [{ ...FOOT, days: 0 }] }).home, {});
  assert.doesNotMatch(words(el.querySelector('.rl-office-footing')), /days? under/);
});

test('the Capital board keeps the holder\'s footing in view at its top', () => {
  const { el } = board(seat({ footing: [FOOT] }));
  const foot = el.querySelector('.rl-office-footing');
  assert.ok(foot, 'the footing is drawn on the board');
  const kids = [...el.children];
  assert.ok(kids.indexOf(foot) <= 1, 'it stands at the top, under the head');
  assert.match(words(foot), /15 days under/);
});

test('a seat that holds no post sees no footing anywhere', () => {
  installDom();
  assert.equal(homeSheet(seat().home, {}).querySelector('.rl-office-footing'), null);
  assert.equal(board(seat()).el.querySelector('.rl-office-footing'), null);
});

test('his office is a question in the Capital list, and an open question on it is drawn there', () => {
  const rv = seat({ footing: [{ ...FOOT, question: Q }], office: [question('vote')] });
  const qs = cap.capitalQuestions(rv);
  const row = qs.find((x) => x.key === `office:${Q}`);
  assert.ok(row, 'the open question is in the list');
  assert.equal(row.kindWords, 'An office question');
  const { el } = board(rv);
  assert.ok(el.querySelector(`.rl-cap-list button[data-key="office:${Q}"]`));
});

test('with no question open, the holder\'s office still stands in the list as his footing', () => {
  const qs = cap.capitalQuestions(seat({ footing: [FOOT] }));
  const row = qs.find((x) => x.kind === 'footing');
  assert.ok(row, 'the office is in the list');
  assert.equal(row.title, 'General of the Norra Levy');
});

// 2. the question as a panel
test('a vote: the panel names the office, why, the day it sits, who decides and the chamber\'s count', () => {
  const { el } = board(seat({ office: [question('vote')] }), { q: `office:${Q}` });
  const p = el.querySelector('.rl-office-panel');
  assert.ok(p, 'the panel is drawn');
  const w = words(p);
  assert.match(w, /Whether Kara Lind stays as General of the Norra Levy/);
  assert.match(w, /an incident put it in doubt/);
  assert.match(w, /sits 12 April 1900/);
  assert.match(w, /A vote of the chamber/);
  assert.match(w, /40 to remove, 10 to keep/);
  assert.equal(p.querySelector('.rl-office-members'), null, 'no table for a vote');
});

test('a council: the panel is a table of its members, each choice sealed', () => {
  const { el } = board(seat({ office: [question('council')] }), { q: `office:${Q}` });
  const rows = el.querySelectorAll('.rl-office-members li');
  assert.deepEqual(rows.map((r) => r.getAttribute('data-member')), ['Kara Lind', 'Ilse Brandt', 'Otto Wern']);
  for (const r of rows) assert.match(words(r), /Sealed until the sitting/);
  assert.equal(el.querySelector('.rl-office-count'), null, 'no count for a council');
});

test('one person: the panel names the one who decides', () => {
  const { el } = board(seat({ office: [question('person')] }), { q: `office:${Q}` });
  assert.match(words(el.querySelector('.rl-office-table')), /One person decides\s*Ilse Brandt/);
});

test('mutant: another member\'s choice is never drawn, even with the seat\'s own filed', () => {
  const { el } = board(seat({ office: [question('council', { mine: true, choice: true })] }), { q: `office:${Q}` });
  for (const r of el.querySelectorAll('.rl-office-members li')) {
    assert.doesNotMatch(words(r), /remove|keep|filed/i, `${r.getAttribute('data-member')} shows no choice`);
  }
});

// 3. the member's sealed choice
test('a member files his choice: Remove sends office-vote with remove true', () => {
  const { el, asked } = board(seat({ office: [question('council', { mine: true })] }), { q: `office:${Q}` });
  assert.match(words(el.querySelector('.rl-office-mine')), /Your choice: not filed/);
  fire(el.querySelector('button[data-key="office-remove"]'), 'click');
  assert.deepEqual(asked.at(-1), ['officeVote', { question: Q, remove: true }]);
});

test('the choice reads back as the server sends it, and Keep changes it', () => {
  const { el, asked } = board(seat({ office: [question('council', { mine: true, choice: true })] }), { q: `office:${Q}` });
  assert.equal(el.querySelector('button[data-key="office-remove"]').getAttribute('aria-pressed'), 'true');
  assert.equal(el.querySelector('button[data-key="office-keep"]').getAttribute('aria-pressed'), 'false');
  assert.match(words(el.querySelector('.rl-office-mine')), /Your choice: remove/);
  fire(el.querySelector('button[data-key="office-keep"]'), 'click');
  assert.deepEqual(asked.at(-1), ['officeVote', { question: Q, remove: false }]);
});

test('mutant: a click draws no choice of its own; only the server\'s read-back presses a button', () => {
  const { el } = board(seat({ office: [question('council', { mine: true })] }), { q: `office:${Q}` });
  fire(el.querySelector('button[data-key="office-remove"]'), 'click');
  assert.equal(el.querySelector('button[data-key="office-remove"]').getAttribute('aria-pressed'), 'false');
});

test('a seat that does not decide has no choice to make', () => {
  const { el } = board(seat({ office: [question('council')] }), { q: `office:${Q}` });
  assert.equal(el.querySelector('.rl-office-choice'), null);
});

test('in the room the choice goes out as office-vote and the answer is read back', async () => {
  const doc = installDom();
  setRoomLayout('map');
  const sent = [];
  const rv = seat({ office: [question('council', { mine: true })] });
  api.realism = async (action, body) => { sent.push([action, body]); return { reply: 'Your choice is sealed. No one sees it before the sitting.' }; };
  api.catchup = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  const game = { id: `h07-${Math.random()}`, name: 'Norra', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'Kara Lind' } } };
  const ctx = { me: { account: { handle: 'josh' }, game }, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {}, signOut: () => {} };
  const root = realismRoom(ctx);
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  const line = needLines(rv).find((l) => l.kind === 'office');
  assert.ok(line, 'the unfiled choice is in the needs list');
  fire(doc.body.querySelector('.rl-board-switch button[data-board="capital"]') ?? doc.body.querySelector('[data-board="capital"]'), 'click');
  const btn = doc.body.querySelector(`.rl-cap button[data-key="office:${Q}"]`);
  assert.ok(btn, 'the question is in the Capital list');
  fire(btn, 'click');
  fire(doc.body.querySelector('button[data-key="office-remove"]'), 'click');
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(sent.find(([a]) => a === 'office-vote'), ['office-vote', { question: Q, remove: true }]);
});

// 4. the elections ahead
test('each election ahead is a line with its day and the seats as they would fall', () => {
  installDom();
  const el = homeSheet(seat({ elections: structuredClone(fixture.home.elections) }).home, {});
  const lines = el.querySelectorAll('.rl-office-elections li');
  assert.equal(lines.length, 1);
  assert.match(words(lines[0]), /1 May 1900, the term of Chancellor of Norra ends/);
  assert.match(words(lines[0]), /The Greens 60 → 64, The Greys 40 → 36/);
});

// 5. the public result
test('once decided, the public result takes the panel\'s place', () => {
  const r = structuredClone(fixture.home.results[0]);
  const { el } = board(seat({ office: [question('council', { mine: true })], results: [r] }), { q: `office:${Q}` });
  assert.equal(el.querySelector('.rl-office-panel'), null, 'mutant: the panel is not kept');
  assert.equal(el.querySelector('.rl-office-choice'), null);
  assert.match(words(el.querySelector('.rl-office-result')), /Kara Lind is kept as General of the Norra Levy, decided 17 April 1900; no question may sit on the post before 17 May 1900/);
});

test('a result the server no longer lists as open still stands in the list and on the home sheet', () => {
  const rv = seat({ results: [{ ...fixture.home.results[0], removed: true }] });
  assert.ok(cap.capitalQuestions(rv).find((x) => x.key === `office:${Q}`));
  installDom();
  assert.match(words(homeSheet(rv.home, {})), /Kara Lind is removed as General of the Norra Levy/);
});

test('the needs list carries an unfiled choice only: filed, or not the seat\'s, it is not there', () => {
  const need = (q) => needLines(seat({ office: [q] })).filter((l) => l.kind === 'office');
  assert.equal(need(question('council', { mine: true })).length, 1);
  assert.equal(need(question('council', { mine: true, choice: false })).length, 0);
  assert.equal(need(question('council')).length, 0);
});

test('another nation\'s home block draws no office question', () => {
  const rv = seat({ office: [question('vote')], footing: [FOOT] });
  rv.home.nation = { ...rv.home.nation, relation: 'other' };
  assert.deepEqual(office.officeQuestions(rv.home), []);
  assert.deepEqual(office.footingOf(rv.home), []);
});

// phone width
test('at phone width the panel and the footing keep to one column', () => {
  const css = read('css/c-capital.css');
  const phone = css.slice(css.indexOf('@media (max-width: 767px)'));
  assert.ok(css.includes('@media (max-width: 767px)'), 'the board has a phone block');
  assert.match(phone, /\.rl-office-choice[^{]*\{[^}]*flex-direction:\s*column/);
  assert.match(css, /\.rl-office-footing[^{]*\{[^}]*overflow-wrap:\s*anywhere/);
});

test('the client sends office-vote by the one generic call and names it', () => {
  assert.match(read('js/api.js'), /office-vote/);
});
