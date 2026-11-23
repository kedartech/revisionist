// Beginner shows less (BGN), one test or more per plan rule: 1. on Beginner the map-first room shows
// the board, the seat's three aims (the bar's marks) and one next step, the top line of "What needs you"; 2. the Court,
// Home and Diplomacy sheets carry a mark when something in them is a line in the list, and with
// nothing waiting stay reachable by the game menu's "All sheets", so every proactive composer opens
// in a quiet wake; 3. the economy's components and the odds table's rows sit behind "More"; 4. the
// first-wake card's words match the new room. Keeps: no style sees more or better odds, so what
// Beginner folds away still opens. Mutants: a sheet unreachable on Beginner; the court marked with
// nothing in it.
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
const { setRoomLayout } = await import('../js/views/realism-sheets.js');
const { addNeedKind, needLines } = await import('../js/views/realism-needs.js');
const { FIRST_WAKE, FIRST_WAKE_BEGINNER } = await import('../js/views/realism-firstwake.js');
const { ownSheet, foldEconomy } = await import('../js/views/realism-economy.js');
const { oddsPanel, foldOdds } = await import('../js/views/realism-odds.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHEET_KEYS = ['papers', 'orders', 'forms', 'messages', 'court', 'people', 'press'];

/** The seat's view on the toy board with nothing waiting but Done; `change` edits it. */
function seat(style, change = () => {}) {
  const rv = structuredClone(fixture);
  rv.map = structuredClone(fixture.territory_map);
  rv.style = style;
  rv.battles = [];
  rv.agenda = { ...rv.agenda, items: [] };
  rv.orders = { orders: rv.orders.orders.map((o) => ({ ...o, decision_needed: false })) };
  rv.documents = structuredClone(fixture.listing);
  rv.home = { ...rv.home, chambers: [] };
  rv.locks = null;
  rv.wake_tick = 1;
  rv.wake = { ...rv.wake, you_committed: false };
  change(rv);
  return rv;
}

/** The whole map-first room for view `rv`, as the page draws it. */
function room(rv, id = `g-${Math.random()}`) {
  const doc = installDom();
  setRoomLayout('map');
  api.realism = async () => ({});
  api.catchup = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  const game = { id, name: 'Autumn 1941', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'Franklin D. Roosevelt' } } };
  const ctx = { me: { account: { handle: 'josh' }, game }, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {} };
  const root = realismRoom(ctx);
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  return root;
}

const tabKeys = (root) => root.querySelector('.rl-sheettabs').querySelectorAll('button').map((b) => b.getAttribute('data-sheet'));
const tabOf = (root, key) => root.querySelector('.rl-sheettabs').querySelectorAll('button').find((b) => b.getAttribute('data-sheet') === key);
const menuKeys = (root) => root.querySelectorAll('.rl-allsheets button').map((b) => b.getAttribute('data-sheet'));
const openName = (root) => root.querySelectorAll('.rl-over').map((s) => s.getAttribute('data-sheet'));
const openMenu = (root) => root.querySelector('.rl-menu-btn').click();
const allSheets = (root, key) => root.querySelectorAll('.rl-allsheets button').find((b) => b.getAttribute('data-sheet') === key);
const waiting = (root) => root.querySelectorAll('.rl-needs .rl-need');

/** Two lines in the list, due on different days. */
const withLines = (rv) => {
  rv.agenda = { ...rv.agenda, items: [
    { id: 'A1', kind: 'Order', text: 'First matter.', issuer: 'The President', issued: '1941-10-01', deadline: '1941-10-20', options: [] },
    { id: 'A2', kind: 'Order', text: 'Second matter.', issuer: 'The President', issued: '1941-10-02', deadline: '1941-10-25', options: [] },
  ] };
};

// rule 1: the board, three aims, one next step

test('Beginner shows the seat\'s three aims and the top line of the list; the rest sits behind More', () => {
  const rv = seat('beginner', withLines);
  assert.equal(needLines(rv).length, 2);
  const root = room(rv);
  const aims = root.querySelector('.rl-roombar .rl-aimmarks');
  assert.ok(aims, 'the aims on the bar above the map');
  assert.equal(aims.querySelectorAll('.rl-aimmark').length, 3);
  assert.ok(root.querySelector('.rl-mapfirst .rl-theatre'), 'the board');
  const shown = root.querySelectorAll('.rl-needs-lines').find((u) => u.parentNode.getAttribute('id') === 'rl-needs').querySelectorAll('.rl-need');
  assert.equal(shown.length, 1, 'one next step');
  assert.equal(shown[0].getAttribute('data-need'), needLines(rv)[0].key, 'the top line');
  const more = root.querySelector('.rl-needs-more');
  assert.ok(more, 'More holds the rest');
  assert.equal(more.querySelectorAll('.rl-need').length, 1, 'and nothing is lost');
  assert.ok(root.querySelector('.rl-needs-commit'), 'Done is still at the foot');
});

test('Free shows every line, and the same aim marks', () => {
  const root = room(seat('free', withLines));
  assert.equal(waiting(root).length, 2);
  assert.equal(root.querySelector('.rl-needs-more'), null);
  assert.equal(root.querySelectorAll('.rl-roombar .rl-aimmark').length, 3);
});

// rule 2: marks, and the quiet route

test('with nothing waiting the Court, Home and Diplomacy leave the tab bar and carry no mark', () => {
  const rv = seat('beginner');
  assert.deepEqual(needLines(rv), []);
  const root = room(rv);
  assert.deepEqual(tabKeys(root), ['papers', 'orders', 'forms', 'messages', 'people', 'press']);
  assert.equal(root.querySelectorAll('.rl-sheettab .rl-tab-count').filter((c) => ['Court', 'Home', 'Diplomacy'].some((n) => words(c.parentNode).startsWith(n))).length, 0);
});

test('a line that opens the Home sheet or the Diplomacy sheet puts that sheet on the tab bar with a mark', () => {
  const rv = seat('beginner', (r) => {
    r.agenda = { ...r.agenda, items: [{ id: 'V1', kind: 'Vote', text: 'Vote on the text.', issuer: 'The chair', issued: '1941-10-01', deadline: '1941-10-20', options: [] }] };
  });
  const root = room(rv);
  assert.ok(tabOf(root, 'diplomacy'));
  assert.equal(tabOf(root, 'diplomacy').querySelectorAll('.rl-tab-count').length, 1);
  assert.equal(tabOf(root, 'court'), undefined, 'the court holds nothing and stays off');
  assert.equal(tabOf(root, 'home'), undefined);
});

test('a line in the Court marks the Court; with none, the Court carries no mark on Free either', () => {
  const off = addNeedKind('test-court', () => [{ key: 'c1', label: 'Court', what: 'A person waits.', from: 'the Court', due: null, arrived: null, action: { word: 'Open', to: 'sheet', sheet: 'court' } }]);
  try {
    const root = room(seat('beginner'));
    assert.equal(tabOf(root, 'court').querySelectorAll('.rl-tab-count').length, 1);
  } finally { off(); }
  assert.equal(tabOf(room(seat('beginner')), 'court'), undefined);
  assert.equal(tabOf(room(seat('free')), 'court').querySelectorAll('.rl-tab-count').length, 0);
});

test('every sheet Free draws is reachable on Beginner: a tab, or All sheets in the game menu', () => {
  const free = room(seat('free'));
  const drawn = [...new Set([...tabKeys(free), 'home'])];
  const root = room(seat('beginner'));
  openMenu(root);
  const reach = new Set([...tabKeys(root), ...menuKeys(root)]);
  for (const key of drawn) assert.ok(reach.has(key), `${key} is reachable on Beginner`);
  for (const key of SHEET_KEYS) assert.ok(reach.has(key), key);
});

test('every proactive composer opens from All sheets in a quiet wake with only Done waiting', () => {
  const root = room(seat('beginner'));
  assert.deepEqual(needLines(seat('beginner')), []);
  assert.equal(waiting(root).length, 0);
  assert.ok(root.querySelector('.rl-needs-commit'), 'only Done waits');
  // a statement: the Home sheet's Speak opens the writing form
  openMenu(root);
  allSheets(root, 'home').click();
  assert.deepEqual(openName(root), ['home']);
  assert.ok(buttons(root.querySelector('.rl-over'), 'Speak to the nation').length, 'a statement can be started');
  // an offer and a conference: the Diplomacy sheet
  openMenu(root);
  allSheets(root, 'diplomacy').click();
  assert.deepEqual(openName(root), ['diplomacy']);
  const sheet = root.querySelector('.rl-over');
  assert.ok(words(sheet).includes('Call a conference'), 'a conference can be called');
  assert.ok(words(sheet).includes('Offer'), 'an offer can be made');
  // the Court
  openMenu(root);
  allSheets(root, 'court').click();
  assert.deepEqual(openName(root), ['court']);
});

test('Free keeps the menu as it was: no All sheets', () => {
  const root = room(seat('free'));
  assert.equal(root.querySelector('.rl-allsheets'), null);
});

// rule 3: the economy's components and the odds table's rows sit behind More

test('the economy\'s components sit behind More on Beginner and in view on Free', () => {
  const economy = fixture.economy;
  foldEconomy(true);
  const folded = ownSheet(economy, fixture.map);
  foldEconomy(false);
  const open = ownSheet(economy, fixture.map);
  assert.ok(folded.querySelector('details.rl-eco-more .rl-eco-income'), 'income inside More');
  assert.ok(folded.querySelector('details.rl-eco-more .rl-eco-pools'), 'pools inside More');
  assert.equal(open.querySelector('details'), null);
  assert.ok(open.querySelector('.rl-eco-income'));
});

test('the odds table\'s rows sit behind More on Beginner and in view on Free', () => {
  const odds = structuredClone(fixture.spread);
  assert.ok(odds.by_strength.length >= 2);
  const draw = () => oddsPanel(fixture, { odds }, { what: 'the Isle' });
  foldOdds(true);
  const folded = draw();
  foldOdds(false);
  const open = draw();
  const inside = folded.querySelector('details.rl-odds-more');
  assert.ok(inside, 'the table is behind More');
  assert.equal(inside.querySelectorAll('.rl-odds-table tbody tr').length, odds.by_strength.length, 'every row is still there');
  assert.equal(open.querySelector('details'), null);
  assert.equal(open.querySelectorAll('.rl-odds-table tbody tr').length, odds.by_strength.length);
});

// rule 4: the first-wake card

test('the first-wake card on Beginner\'s map-first room names the aim marks and the list', () => {
  const wake0 = { wake: 0, deadline: '1941-09-01T21:00:00+00:00', committed: 0, humans: 1, you_committed: false, is_host: true, can_close: true };
  const firstRow = (root) => root.querySelectorAll('.rl-needs .rl-need').find((r) => r.getAttribute('data-kind') === 'first');
  const card = firstRow(room(seat('beginner', (r) => { r.wake = wake0; })));
  assert.ok(card, 'the first row of What needs you');
  assert.deepEqual(card.querySelectorAll('li').map(words), [...FIRST_WAKE_BEGINNER.steps]);
  assert.ok(!words(card).includes('pinned on the Board'));
  assert.ok(words(card).includes('the marks at the top'));
  const free = firstRow(room(seat('free', (r) => { r.wake = wake0; })));
  assert.deepEqual(free.querySelectorAll('li').map(words), [...FIRST_WAKE.steps]);
});
