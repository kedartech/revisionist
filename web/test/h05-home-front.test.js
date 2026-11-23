// The home front on screen, one test or more per rule: 1. the home sheet opens on what changed
// since the seat's last wake: each group that moved, by how much and why, one line each, heaviest
// first, and a line opens every move with how it reached the public; 2. each measure on its way
// shows its count now beside its count then, with the blocs that moved marked; 3. each place of
// political weight is a line with its holder, and a threatened one is a line in what needs you
// that shows it on the map; 4. a general's seat sees the same sheet as his nation's politician.
// Amended (the Capital board): each bloc and group that moved carries a mark, picking it gives
// each move's amount, cause and reach, those against the seat as well, and the vote's track has
// the count then beside the count now. Keeps: the sheet is the same in every style.
// Mutant: a move drawn that the server did not send.
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
const home = await import('../js/views/realism-home.js');
const needs = await import('../js/views/realism-needs.js');
const cap = await import('../js/views/realism-capital.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');

/**
 * Norra's home block after a wake with losses: the Greens up 5 on a battle won, the Public down
 * 2 then down 4 on territory lost and losses felt (net down 6, the heaviest), the Levy act's
 * assembly vote then 101 yea and 99 nay, now 91 and 109, with the Greens' count moved and the
 * Greys' not; the Norra Plain held and threatened, the hills held and quiet.
 */
function block(change = () => {}) {
  const h = structuredClone(fixture.home);
  const g = (key) => h.groups.find((x) => x.key === key);
  g('greens').since = [{ cause: 'battle_won', change: 5, on: '1900-04-02', why: 'a battle won', reach: 'reported' }];
  g('public').since = [
    { cause: 'territory_lost', change: -2, on: '1900-04-04', why: 'territory lost', reach: 'reported' },
    { cause: 'losses_felt', change: -4, on: '1900-04-05', why: 'earlier battle losses felt at home', reach: 'felt' },
  ];
  h.moved = [
    { group: 'public', name: 'The Norra Public', change: -6, line: 'The Norra Public -6: earlier battle losses felt at home and 1 more' },
    { group: 'greens', name: 'The Greens', change: 5, line: 'The Greens +5: a battle won' },
  ];
  const v = h.chambers[0].measures[0].votes[0];
  v.then = [101, 99];
  v.blocs = [
    { group: 'greens', yeas: 71, nays: 29, then: [81, 19], moved: true },
    { group: 'greys', yeas: 20, nays: 80, then: [20, 80], moved: false },
  ];
  const own = h.nation;
  h.places = [
    { key: 'norra_plain', name: 'The Norra Plain', holder: own, threatened: true },
    { key: 'norra_hills', name: 'The Norra Hills', holder: own, threatened: false },
  ];
  change(h);
  return h;
}

/** The seat's view with that block; `change` edits the view. */
function seat(change = () => {}) {
  const rv = structuredClone(fixture);
  rv.map = structuredClone(fixture.territory_map);
  rv.documents = structuredClone(fixture.listing);
  rv.battles = [];
  rv.agenda = { ...rv.agenda, items: [] };
  rv.wake_tick = 1;
  rv.style = 'free';
  rv.home = block();
  change(rv);
  return rv;
}

const sheet = (h, opts) => {
  installDom();
  const el = home.homeSheet(h, opts);
  document.body.append(el);
  return el;
};
const sinceRows = (el) => el.querySelectorAll('.rl-home-since li.rl-home-since-row');

// --- Rule 1: the sheet opens on what moved since the last wake --------------------------------

test('the sheet opens on what moved since the last wake: one line a group, as the server worded it, heaviest first', () => {
  const el = sheet(block());
  const since = el.querySelector('.rl-home-since');
  assert.ok(since, 'a section of what moved');
  const kids = [...el.children];
  assert.equal(kids.indexOf(since), 2, 'it stands at the top, under the title and the day');
  assert.match(words(since.querySelector('h4')), /Since your last wake/);
  assert.deepEqual(sinceRows(el).map((li) => li.getAttribute('data-group')), ['public', 'greens']);
  assert.match(words(sinceRows(el)[0]), /The Norra Public -6: earlier battle losses felt at home and 1 more/);
  assert.match(words(sinceRows(el)[1]), /The Greens \+5: a battle won/);
});

test('each line is drawn: an arrow its way and a bar of its size, a loss marked as one', () => {
  const [pub, greens] = sinceRows(sheet(block()));
  assert.ok(pub.classList.contains('down'));
  assert.ok(greens.classList.contains('up'));
  const width = (li) => Number(li.querySelector('rect.rl-home-since-fill').getAttribute('width'));
  assert.equal(width(pub), 100, 'the heaviest fills its bar');
  assert.ok(Math.abs(width(greens) - (100 * 5) / 6) < 0.01, 'the others to scale');
});

test('a line opens every move behind it: amount, day, cause and how it reached the public', () => {
  const el = sheet(block());
  const row = sinceRows(el)[0];
  const btn = row.querySelector('button.rl-home-since-btn');
  const list = row.querySelector('.rl-home-since-moves');
  assert.equal(btn.getAttribute('aria-expanded'), 'false');
  assert.ok(list.hasAttribute('hidden'));
  fire(btn, 'click');
  assert.equal(btn.getAttribute('aria-expanded'), 'true');
  assert.ok(!list.hasAttribute('hidden'));
  assert.deepEqual(list.querySelectorAll('li').map(words), [
    'Down 2 on 4 April 1900: territory lost, by report',
    'Down 4 on 5 April 1900: earlier battle losses felt at home, felt at home',
  ]);
});

test('nothing moved since the last wake says so; a block without the list draws no section', () => {
  assert.match(words(sheet(block((h) => { h.moved = []; })).querySelector('.rl-home-since')), /Nothing at home has moved since your last wake/);
  assert.equal(sheet(block((h) => { delete h.moved; })).querySelector('.rl-home-since'), null);
});

test('mutant: a move the server did not send is not drawn', () => {
  // the groups still carry their moves and last moves, but the server sent no line for them
  const el = sheet(block((h) => { h.moved = [h.moved[1]]; }));
  assert.deepEqual(sinceRows(el).map((li) => li.getAttribute('data-group')), ['greens'], 'only the line sent');
  const none = sheet(block((h) => { h.moved = []; }));
  assert.equal(sinceRows(none).length, 0, 'no line worked out from the groups\' moves');
});

// --- Rule 2: the count now beside the count then ------------------------------------------------

test('a measure on its way shows its count then beside its count now, each drawn as a bar', () => {
  const el = sheet(block());
  const vote = el.querySelector('.rl-home-vote');
  const then = vote.querySelector('.rl-home-then');
  assert.ok(then, 'the count then');
  assert.match(words(then), /At your last wake: 101 yea, 99 nay/);
  assert.match(words(then), /Now: 91 yea, 109 nay/);
  const yeas = (sel) => Number(vote.querySelector(`${sel} rect.rl-home-vseg.yeas`).getAttribute('width'));
  assert.ok(yeas('.rl-home-thenbar') > yeas('.rl-home-votebar'), 'the bar then is longer in yeas than now');
});

test('the blocs that moved are marked, with what each stood at then', () => {
  const vote = sheet(block()).querySelector('.rl-home-vote');
  assert.match(words(vote.querySelector('.rl-home-then')), /Moved since: The Greens, 81 yea and 19 nay then/);
  const tokens = vote.querySelectorAll('.rl-home-token');
  assert.ok(tokens.find((t) => t.getAttribute('data-group') === 'greens').classList.contains('moved'));
  assert.ok(!tokens.find((t) => t.getAttribute('data-group') === 'greys').classList.contains('moved'));
});

test('no count then (no wake yet, or not then on its way): only the count now', () => {
  const vote = sheet(block((h) => { h.chambers[0].measures[0].votes[0].then = null; })).querySelector('.rl-home-vote');
  assert.equal(vote.querySelector('.rl-home-then'), null);
});

test('mutant: a bloc the server did not mark as moved is not marked', () => {
  const vote = sheet(block((h) => { h.chambers[0].measures[0].votes[0].blocs[0].moved = false; })).querySelector('.rl-home-vote');
  assert.doesNotMatch(words(vote.querySelector('.rl-home-then')), /Moved since/);
  assert.equal(vote.querySelectorAll('.rl-home-token.moved').length, 0);
});

// --- Rule 3: the places of weight -------------------------------------------------------------------

test('each place of political weight is a line with its holder; a threatened one is marked', () => {
  const el = sheet(block());
  const rows = el.querySelectorAll('.rl-home-places li');
  assert.deepEqual(rows.map((li) => li.getAttribute('data-area')), ['norra_plain', 'norra_hills']);
  assert.match(words(rows[0]), /The Norra Plain.*Held by Norra.*Threatened/);
  assert.ok(rows[0].classList.contains('threatened'));
  assert.doesNotMatch(words(rows[1]), /Threatened/);
  const lost = sheet(block((h) => { h.places[1].holder = { key: 'X', name: 'Sudland', relation: 'enemy' }; }));
  assert.match(words(lost.querySelectorAll('.rl-home-places li')[1]), /Held by Sudland/);
  const empty = sheet(block((h) => { h.places[1].holder = null; }));
  assert.match(words(empty.querySelectorAll('.rl-home-places li')[1]), /Held by no one/);
  assert.equal(sheet(block((h) => { h.places = []; })).querySelector('.rl-home-places'), null);
});

test('a threatened place is a line in what needs you that shows it on the map', () => {
  const lines = needs.needLines(seat()).filter((l) => l.kind === 'place');
  assert.deepEqual(lines.map((l) => [l.key, l.action]), [['norra_plain', { word: 'Show on map', to: 'map', area: 'norra_plain' }]]);
  assert.match(lines[0].what, /The Norra Plain/);
  assert.deepEqual(needs.needLines(seat((rv) => { rv.home.places[0].threatened = false; })).filter((l) => l.kind === 'place'), []);
  assert.deepEqual(needs.needLines(seat((rv) => { rv.home = null; })).filter((l) => l.kind === 'place'), []);
});

test('the place\'s line in the room centres the map on it and opens its area', async () => {
  const rv = seat();
  const { root } = room(rv);
  const row = root().querySelectorAll('li.rl-need').find((li) => li.getAttribute('data-kind') === 'place');
  assert.ok(row, 'the line is in the list');
  fire(row.querySelector('button.rl-need-row'), 'click');
  fire(root().querySelectorAll('li.rl-need').find((li) => li.getAttribute('data-kind') === 'place').querySelector('button.rl-need-act'), 'click');
  assert.ok(root().querySelector('.rl-area-sheet'), 'the area\'s sheet is open on the map');
  assert.match(words(root().querySelector('.rl-area-sheet')), /Norra Plain/);
});

// --- Rule 4: a general's seat sees the same sheet ---------------------------------------------------

/** The whole room for view `rv` in the map-first layout. */
function room(rv) {
  const doc = installDom();
  setRoomLayout('map');
  api.realism = async () => ({ reply: '', refused: false });
  api.catchup = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  const game = { id: `h05-${Math.random()}`, name: 'Autumn 1941', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'A seat' } } };
  const ctx = { me: { account: { handle: 'josh' }, game }, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {}, signOut: () => {} };
  const el = realismRoom(ctx);
  Object.getPrototypeOf(el).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(el);
  return { root: () => doc.body.firstElementChild ?? el };
}

/** The home sheet as the map-first room opens it: World, the seat's own nation, At home. */
function openHome(root) {
  fire(root().querySelectorAll('.rl-sheettabs button').find((b) => b.getAttribute('data-group') === 'world'), 'click');
  fire(root().querySelector('button.rl-nb-row.rl-nb-own'), 'click');
  fire(root().querySelector('.rl-nb-card button.rl-nb-home'), 'click');
  return root().querySelector('.rl-home-sheet');
}

test('a general\'s seat sees the same home sheet as his nation\'s politician', () => {
  const politician = seat((rv) => { rv.desk = { ...rv.desk, path: 'political' }; });
  const general = seat((rv) => { rv.desk = { ...rv.desk, path: 'military' }; });
  const a = openHome(room(politician).root);
  const aw = words(a);
  const b = openHome(room(general).root);
  assert.ok(a && b);
  assert.equal(words(b), aw);
  assert.ok(b.querySelector('.rl-home-since'), 'what moved is on the general\'s sheet');
});

test('keeps: the sheet reads the same in every style, and Beginner opens it', () => {
  const free = openHome(room(seat()).root);
  const fw = words(free);
  const beginner = openHome(room(seat((rv) => { rv.style = 'beginner'; })).root);
  assert.ok(beginner, 'Beginner opens the sheet');
  assert.equal(words(beginner), fw);
});

// --- Amended: the Capital board ---------------------------------------------------------------------

/** The board alone over `rv`. */
function board(rv, state = {}) {
  installDom();
  const el = cap.capitalBoard(rv, { q: `vote:${rv.home.chambers[0].measures[0].order_id}`, ...state }, {});
  document.body.append(el);
  return el;
}
const pieceOf = (el, key) => el.querySelectorAll('.rl-cap-piece').find((p) => p.getAttribute('data-group') === key);

test('the board marks each bloc and group that moved since the last wake, as the server sent it', () => {
  const el = board(seat());
  const greens = pieceOf(el, 'greens');
  assert.ok(greens.classList.contains('since') && greens.classList.contains('since-up'));
  assert.match(words(greens.querySelector('.rl-cap-since')), /\+5/);
  assert.match(greens.getAttribute('aria-label'), /moved up 5 since your last wake/);
  const greys = pieceOf(el, 'greys');
  assert.ok(!greys.classList.contains('since'));
  assert.equal(greys.querySelector('.rl-cap-since'), null);
});

test('a group outside the chamber that moved against the seat is marked as a loss', () => {
  const el = board(seat());
  const pub = pieceOf(el, 'public');
  assert.ok(pub, 'the public is outside the chamber');
  assert.ok(pub.classList.contains('since') && pub.classList.contains('since-down'));
  assert.match(words(pub.querySelector('.rl-cap-since')), /−6/);
});

test('picking a marked piece gives each move: amount, cause and how it reached the public, losses too', () => {
  const el = board(seat(), { pick: 'public' });
  const card = el.querySelector('.rl-cap-card');
  const moves = card.querySelectorAll('.rl-cap-sincelist li');
  assert.deepEqual(moves.map(words), [
    'Down 2 on 4 April 1900: territory lost, by report',
    'Down 4 on 5 April 1900: earlier battle losses felt at home, felt at home',
  ]);
  assert.ok(moves.every((li) => li.classList.contains('down')));
  const quiet = board(seat(), { pick: 'greys' }).querySelector('.rl-cap-card');
  assert.equal(quiet.querySelector('.rl-cap-sincelist'), null);
  assert.match(words(quiet), /Not moved since your last wake/);
});

test('mutant: the board marks no piece the server sent no line for', () => {
  const el = board(seat((x) => { x.home.moved = []; }));
  assert.equal(el.querySelectorAll('.rl-cap-piece.since').length, 0);
});

test('the vote\'s track has the count then beside the count now', () => {
  const el = board(seat());
  const boxes = el.querySelectorAll('.rl-cap-trackbox');
  const then = boxes.find((b) => b.classList.contains('then'));
  assert.ok(then, 'a track of the count then');
  assert.match(words(then), /At your last wake/);
  assert.match(words(then), /101 yea · 99 nay/);
  const now = boxes.find((b) => !b.classList.contains('then'));
  assert.match(words(now), /91 yea · 109 nay/);
  const greensYea = (box) => Number(box.querySelectorAll('rect.rl-cap-yea').find((r) => r.getAttribute('data-group') === 'greens').getAttribute('width'));
  assert.ok(greensYea(then) > greensYea(now), 'the Greens\' yeas then are drawn wider than now');
  assert.ok(now.querySelectorAll('rect.rl-cap-yea').find((r) => r.getAttribute('data-group') === 'greens').classList.contains('moved'));
  const none = board(seat((x) => { x.home.chambers[0].measures[0].votes[0].then = null; }));
  assert.equal(none.querySelectorAll('.rl-cap-trackbox.then').length, 0);
});

// --- Colour and width --------------------------------------------------------------------------------

test('the new marks take their colours from the tokens and wrap at phone width', () => {
  for (const f of ['css/c-home.css', 'css/c-capital.css']) {
    const css = read(f);
    assert.doesNotMatch(css, /#[0-9a-f]{3,8}\b|rgb\(|hsl\(/i, `${f}: tokens only`);
  }
  const css = read('css/c-home.css');
  assert.match(css, /\.rl-home-since-row\.down[^{]*\{[^}]*var\(--danger\)/);
  assert.match(css, /\.rl-home-place\.threatened[^{]*\{[^}]*var\(--danger\)/);
  assert.match(css, /\.rl-home-since[^{]*\{[^}]*(flex-wrap|min-width: 0)/);
  assert.match(read('css/c-capital.css'), /\.rl-cap-piece\.since-down[^{]*\{[^}]*var\(--danger\)/);
});
