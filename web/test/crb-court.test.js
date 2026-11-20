// The court board: one row per path the seat's forms travel, a square per decision step in
// order and a small mark for a clerical step; each order in flight a token on its holder's
// square; the circle and chain on no path grouped by bloc; each chamber's seats by party with
// the line that carries a vote and its public votes. A picked square or chip shows the
// person's figure card with the two moves the seat has on them.
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
const { courtBoard } = await import('../js/views/realism-court.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));

/** A roster line as the server sends it, with nothing known beyond the name. */
const line = (person, name, more = {}) => ({
  person, name, office: null, stance: null, trend: null, over: [], at_war: false, last_answer: null,
  regard: { step: null, word: 'Unknown', as_of: null, confidence: null },
  reliability: { step: null, word: 'Untested', as_of: null, confidence: null },
  holds: [], load: 0, tally: null, pace: null, standing: null, bloc: null, channel: null, power: null,
  ...more,
});

const HULL = 'WQ1FF1C63737PE82A3M9Y5EZ5S';
const STIMSON = 'XR21GGDNXQNFPX7ZKQPDJSEVEN';
const KNOX = 'YJ0YXV37N7JATQDHK3NAM3DRGX';
const RAYBURN = 'ABAZ0TGFM42G2BDHEC49BPG0B7';
const STARK = 'VAKP5F7QBGTN3YCP8CKDF4TN1E';
const HOPKINS = 'KCGWPP4ACP8FAQ882NJAGZB8H5';

/** Roosevelt's view: the fixture's court, reach and stakes, with roster lines for his people. */
function wide() {
  const r = structuredClone(fixture);
  r.people = {
    opponents: [],
    yours: [
      line(HULL, 'Cordell Hull', { bloc: 'Department of State' }),
      line(STIMSON, 'Henry L. Stimson', { bloc: 'War Department' }),
      line(KNOX, 'Frank Knox', { bloc: 'Navy Department' }),
      line(HOPKINS, 'Harry L. Hopkins', {
        bloc: 'White House', office: 'Special assistant to the President',
        loyalty: { step: 5, word: 'Devoted', as_of: null, confidence: null },
      }),
      line(STARK, 'Harold R. Stark', { bloc: 'Navy Department' }),
    ],
    others: [],
  };
  return r;
}

/** A thin seat (Tojo's shape): two paths, a short ring, no chamber. */
function thin() {
  const r = wide();
  r.court = {
    paths: [
      { id: 'p-army', name: 'An army order', forms: ['Move an army'], steps: [
        { person: 'S1', name: 'Hajime Sugiyama', office: 'Chief of the Army General Staff', kind: 'decision', days: null, you: false,
          orders: [{ id: 'o-1', label: 'Move an army', since: '1941-10-20', held_days: 0 }] },
      ] },
      { id: 'p-cab', name: 'A cabinet decision', forms: ['Put it to the cabinet'], steps: [
        { person: 'T1', name: 'Hideki Tojo', office: 'Prime Minister of Japan', kind: 'decision', days: 3, you: true, orders: [] },
      ] },
    ],
    ring: [{ person: 'K1', name: 'Kōichi Kido', office: 'Lord Keeper of the Privy Seal', channel: 'in_person' }],
    chambers: [],
    load_limit: 2,
  };
  return r;
}

const ui = (piece = null) => ({ view: 'board', board: 'court', piece, theatre: { mode: 'map', scope: 'reports' }, chat: { open: false, tab: 'chats', thread: null }, draft: null });
const board = (r, u = ui(), more = {}) => courtBoard(r, u, { pick: () => {}, act: () => {}, ...more });
const rows = (el) => el.querySelectorAll('.rl-court-path');
const squares = (row) => row.querySelectorAll('.rl-court-sq');
const sqName = (sq) => words(sq.querySelector('.rl-court-name'));
const square = (el, name) => el.querySelectorAll('.rl-court-sq').find((s) => sqName(s) === name);
const person = (id, name) => ({ kind: 'person', person: id, name });

test('one row per path: its name, the forms that travel it, a square per decision step in order', () => {
  const view = board(wide());
  assert.equal(view.getAttribute('aria-labelledby'), 'rl-court-h');
  const all = rows(view);
  assert.deepEqual(all.map((r) => words(r.querySelector('.rl-court-path-name'))),
    ['A bill through Congress', 'A naval order', 'A cable to the Prime Minister', 'A Lend-Lease allocation', 'A public address',
      'The intelligence office']);
  assert.equal(words(all[1].querySelector('.rl-court-forms')), 'Forms: Give a naval order, Move a fleet, Detach part of a fleet');
  assert.deepEqual(squares(all[0]).map(sqName), ['Sam Rayburn', 'Alben W. Barkley', 'You']);
  assert.deepEqual(squares(all[3]).map(sqName), ['Harry L. Hopkins', 'Edward R. Stettinius Jr.', 'You']);
  const barkley = square(all[0], 'Alben W. Barkley');
  assert.equal(words(barkley.querySelector('.rl-court-office')), 'Senate Majority Leader');
  assert.equal(words(barkley.querySelector('.rl-court-days')), '20 days');
  assert.equal(words(square(all[0], 'You').querySelector('.rl-court-office')), 'President of the United States');
});

test('a clerical step is a small mark between the squares, not a square', () => {
  const view = board(wide());
  const [bill, , cable, , address] = rows(view);
  const steps = bill.querySelectorAll('.rl-court-line li').filter((li) => li.parentNode.classList.contains('rl-court-line'));
  assert.deepEqual(steps.map((li) => li.className), ['rl-court-step', 'rl-court-step clerk', 'rl-court-step', 'rl-court-step']);
  const clerk = bill.querySelector('.rl-court-clerk');
  assert.equal(words(clerk), 'House committee clerk, 1 day');
  assert.equal(clerk.tagName, 'SPAN', 'a mark, not a button');
  assert.deepEqual(squares(cable).map(sqName), ['Winston Churchill']);
  assert.equal(squares(address).length, 0, 'a path of clerks alone has no square');
  assert.equal(words(address.querySelector('.rl-court-clerk')), 'Stephen T. Early, 1 day');
});

test('each order in flight is a token on its holder\'s square, with the day it is on and the days stated', () => {
  const view = board(wide());
  const tokens = view.querySelectorAll('.rl-court-tok');
  assert.equal(tokens.length, 2, 'two orders in flight');
  const rayburn = square(view, 'Sam Rayburn');
  assert.equal(words(rayburn.querySelector('.rl-court-tok')), 'Send a bill to Congress: day 9 of about 8');
  assert.ok(rayburn.classList.contains('holds'));
  assert.equal(words(square(view, 'Harold R. Stark').querySelector('.rl-court-tok')), 'Give a naval order: day 2 of about 2');
  assert.equal(square(view, 'Alben W. Barkley').querySelector('.rl-court-tok'), null);
  assert.ok(!square(view, 'Alben W. Barkley').classList.contains('holds'));
});

test('a step with no stated time says so, on the square and on its token', () => {
  const view = board(thin());
  const sq = square(view, 'Hajime Sugiyama');
  assert.equal(words(sq.querySelector('.rl-court-days')), 'no time stated');
  assert.equal(words(sq.querySelector('.rl-court-tok')), 'Move an army: day 1; no time stated');
});

test('the ring: circle and chain on no path, grouped by bloc, each with the channel', () => {
  const view = board(wide());
  const ring = view.querySelector('.rl-court-ring');
  assert.equal(words(ring.querySelector('h3')), 'Your circle, on no path today');
  const groups = ring.querySelectorAll('.rl-court-bloc').map((g) => [
    words(g.querySelector('h4')),
    g.querySelectorAll('.rl-court-chip').map(words),
  ]);
  assert.deepEqual(groups, [
    ['Department of State', ['Cordell Hull · in person']],
    ['War Department', ['Henry L. Stimson · in person']],
    ['Navy Department', ['Frank Knox · in person']],
    ['Other', ['George C. Marshall · in person', 'Henry A. Wallace · in person', 'Henry Morgenthau Jr. · in person', 'White House executive clerk · in person']],
  ]);
  const r = wide();
  r.court.ring = [{ person: 'X', name: 'Winston Churchill', office: 'Prime Minister', channel: 'cable' }];
  assert.deepEqual(board(r).querySelectorAll('.rl-court-chip').map(words), ['Winston Churchill · by cable']);
  r.court.ring = [
    { person: 'X1', name: 'Felix Frankfurter', office: 'Associate Justice', channel: 'letter' },
    { person: HULL, name: 'Cordell Hull', office: 'Secretary of State', channel: 'in_person' },
  ];
  assert.deepEqual(board(r).querySelectorAll('.rl-court-bloc h4').map(words), ['Department of State', 'Other'], 'Other comes last');
  r.court.ring = [];
  assert.equal(board(r).querySelector('.rl-court-ring'), null, 'no ring, no section');
});

test('chambers: a bar of seats by party with the line that carries a vote, then the public votes', () => {
  const view = board(wide());
  const chambers = view.querySelectorAll('.rl-court-chamber');
  assert.deepEqual(chambers.map((c) => words(c.querySelector('h3'))), ['House of Representatives · 434 seats', 'Senate · 96 seats']);
  const [house, senate] = chambers;
  const bar = house.querySelector('svg.rl-court-seats');
  assert.equal(bar.getAttribute('viewBox'), '0 0 434 10');
  assert.equal(bar.getAttribute('role'), 'img');
  assert.equal(bar.getAttribute('aria-label'), '267 Democrats, 162 Republicans, 5 Other members; 218 seats carry a vote');
  const rects = bar.querySelectorAll('rect');
  assert.deepEqual(rects.map((r) => [r.getAttribute('x'), r.getAttribute('width')]), [['0', '267'], ['267', '162'], ['429', '5']]);
  const carry = bar.querySelector('line');
  assert.equal(carry.getAttribute('x1'), '218');
  assert.equal(carry.getAttribute('x2'), '218');
  assert.equal(words(house.querySelector('.rl-court-parties')), '267 Democrats · 162 Republicans · 5 Other members · 218 carry a vote');
  assert.deepEqual(house.querySelectorAll('.rl-court-vote').map(words), ['House vote on draft extension: 203 yeas, 202 nays, 12 August 1941']);
  assert.equal(senate.querySelector('line').getAttribute('x1'), '49');
  assert.equal(words(senate.querySelector('.rl-court-votes')), 'No public vote yet.');
});

test('a thin seat: two rows, its own step a square that is not a button, no chamber section', () => {
  const view = board(thin());
  assert.equal(rows(view).length, 2);
  assert.equal(view.querySelector('.rl-court-chambers'), null);
  const you = square(view, 'You');
  assert.equal(you.tagName, 'DIV', 'the seat does not pick itself');
  assert.ok(you.classList.contains('you'));
  assert.deepEqual(view.querySelectorAll('.rl-court-chip').map(words), ['Kōichi Kido · in person']);
});

test('a seat whose forms travel no path, and a view with no court, say so', () => {
  const r = thin();
  r.court = { paths: [], ring: [], chambers: [], load_limit: 2 };
  const none = board(r);
  assert.equal(rows(none).length, 0);
  assert.match(words(none), /None of your forms travels a path yet\./);
  delete r.court;
  const blank = board(r);
  assert.equal(words(blank.querySelector('h2')), 'Court');
  assert.match(words(blank), /No court has reached this view yet\./);
});

test('picking a square or a ring chip picks that person; picking them again clears it', () => {
  const picked = [];
  const view = board(wide(), ui(), { pick: (p) => picked.push(p) });
  square(view, 'Sam Rayburn').click();
  buttons(view, 'Cordell Hull · in person')[0].click();
  assert.deepEqual(picked, [{ piece: person(RAYBURN, 'Sam Rayburn') }, { piece: person(HULL, 'Cordell Hull') }]);
  const on = board(wide(), ui(person(RAYBURN, 'Sam Rayburn')), { pick: (p) => picked.push(p) });
  const sq = square(on, 'Sam Rayburn');
  assert.equal(sq.getAttribute('aria-pressed'), 'true');
  assert.equal(square(on, 'Alben W. Barkley').getAttribute('aria-pressed'), 'false');
  sq.click();
  assert.deepEqual(picked.at(-1), { piece: null });
});

test('a picked person with a roster line shows their figure card beside the board', () => {
  const view = board(wide(), ui(person(HOPKINS, 'Harry L. Hopkins')));
  const sel = view.querySelector('.rl-court-sel');
  assert.ok(sel, 'the selected person');
  assert.equal(words(sel.querySelector('.rl-dos-name')), 'Harry L. Hopkins');
  assert.match(words(sel), /White House · One of your people/);
  assert.match(words(sel), /Loyalty .*Devoted/, 'drawn as from Your people');
  assert.equal(sel.querySelector('dialog'), null, 'in the board, not a dialog');
  assert.equal(sel.querySelector('.rl-dos-foot'), null, 'no Close of the dialog');
  assert.equal(board(wide()).querySelector('.rl-court-sel'), null, 'nothing picked, no card');
  const force = { kind: 'force', person: HOPKINS, name: 'Harry L. Hopkins' };
  assert.equal(board(wide(), ui(force)).querySelector('.rl-court-sel'), null, 'a piece that is not a person is not looked up');
});

test('a picked person with no roster line shows their name and office and says the staff hold no card', () => {
  const view = board(wide(), ui(person(RAYBURN, 'Sam Rayburn')));
  const sel = view.querySelector('.rl-court-sel');
  assert.equal(words(sel.querySelector('h3')), 'Sam Rayburn');
  assert.match(words(sel), /Speaker of the House of Representatives/);
  assert.match(words(sel), /Your staff hold no card on them\./);
});

test('the two moves: ask a question where a channel reaches them, write an order where one carries an order', () => {
  const view = board(wide(), ui(person(RAYBURN, 'Sam Rayburn')));
  const moves = view.querySelector('.rl-court-moves');
  assert.deepEqual(moves.querySelectorAll('button').map(words), ['Ask them a question', 'Write them an order']);
  const r = wide();
  r.reach.inner_circle[1].channel_keys = [];
  assert.deepEqual(board(r, ui(person(RAYBURN, 'Sam Rayburn'))).querySelector('.rl-court-moves').querySelectorAll('button').map(words),
    ['Ask them a question']);
  const far = board(wide(), ui(person(STIMSON, 'Henry L. Stimson')));
  assert.equal(far.querySelectorAll('.rl-court-moves button').length, 0);
  assert.match(words(far.querySelector('.rl-court-moves')), /You cannot reach them from here\./);
});

test('Ask opens the messenger on their thread; Write addresses the order form to them', () => {
  const picked = [];
  const u = ui(person(RAYBURN, 'Sam Rayburn'));
  u.draft = { to: 'Harry Hopkins', channel: 'letter', text: 'Keep the words' };
  const view = board(wide(), u, { pick: (p) => picked.push(p) });
  buttons(view, 'Ask them a question')[0].click();
  assert.deepEqual(u.chat, { open: true, tab: 'chats', thread: 'Sam Rayburn' });
  assert.deepEqual(picked.at(-1), { tab: 'messages' });
  buttons(view, 'Write them an order')[0].click();
  assert.equal(u.orderTo.name, 'Sam Rayburn');
  assert.deepEqual(u.draft, { to: 'Sam Rayburn', channel: 'telephone', text: 'Keep the words' });
  assert.equal(u.proposal, null);
  assert.equal(u.chat.open, false, 'the messenger closes so the form is seen');
  assert.deepEqual(picked.at(-1), {});
});

/** The whole room on Roosevelt's view, in the page, with no model or server behind it. */
function room() {
  const doc = installDom();
  api.realism = async () => ({});
  const r = { ...wide(), documents: fixture.listing, wake_tick: 1 };
  const me = { account: { handle: 'josh' }, game: { id: `g-${Math.random()}`, name: 'Autumn 1941', view: { realism: r, seat: { name: 'Franklin D. Roosevelt' } } } };
  const root = realismRoom({ me, refresh: async () => {}, go: () => {} });
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  return root;
}

const toCourt = (root) => {
  buttons(root.querySelector('.rl-viewswitch'), 'Board')[0].click();
  buttons(root.querySelector('.rl-boardswitch'), 'Court')[0].click();
};

test('in the room: the Court board replaces the stub, and a pick keeps focus on the square and shows the card', () => {
  const root = room();
  const scrolled = [];
  Object.getPrototypeOf(root).scrollIntoView = function scrollIntoView() { scrolled.push(this.className); };
  toCourt(root);
  assert.doesNotMatch(words(root.querySelector('.rl-board-main')), /not built yet/);
  square(root, 'Sam Rayburn').click();
  const sq = square(root, 'Sam Rayburn');
  assert.equal(sq.getAttribute('aria-pressed'), 'true');
  assert.equal(document.activeElement, sq);
  assert.equal(words(root.querySelector('.rl-court-sel h3')), 'Sam Rayburn');
  assert.deepEqual(scrolled, ['rl-court-sel'], 'the card is scrolled into sight');
});

test('in the room: Write them an order puts them in the order form beside the board', () => {
  const root = room();
  toCourt(root);
  square(root, 'Sam Rayburn').click();
  buttons(root, 'Write them an order')[0].click();
  const checked = root.querySelectorAll('.rl-board-side input').find((i) => i.getAttribute('type') === 'radio' && i.checked);
  assert.equal(checked?.value, 'Sam Rayburn');
  assert.equal(document.activeElement, root.querySelector('.rl-board-side .rl-write textarea'));
});

test('in the room: Ask them a question opens their thread in the messenger', () => {
  const root = room();
  toCourt(root);
  square(root, 'Sam Rayburn').click();
  buttons(root, 'Ask them a question')[0].click();
  assert.equal(words(root.querySelector('.rl-th-name')), 'Sam Rayburn');
});

test('c-court.css is linked, uses tokens only, and the court is text nodes only', () => {
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  assert.match(html, /<link rel="stylesheet" href="\/css\/c-court\.css">/);
  const css = readFileSync(new URL('../css/c-court.css', import.meta.url), 'utf8');
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,6}\b|rgba?\(/, 'colours come from tokens');
  const src = readFileSync(new URL('../js/views/realism-court.js', import.meta.url), 'utf8');
  assert.doesNotMatch(src, /innerHTML|insertAdjacentHTML|outerHTML/);
});
