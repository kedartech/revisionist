// Battles on the map, and the battle sheet (BTC). An area with a battle the seat's nation is in
// carries a battle mark; a battle the seat knows only from the press is marked as the press gave
// it and opens that paper. The battle sheet shows each day's round with the seat's losses and the
// enemy's as reported, the seat's strength as pips and the enemy's as a range, and the decision in
// force. The four decisions are buttons with one line each; press, hold and withdraw file through
// the `battle` action, withdraw and a fall-back to an area picked among the lit adjacent areas.
// A piece's sheet holds the contingency picker. A battle with no decision this wake is a line in
// "What needs you", due at the close; a decision on its way reads like any other order that waits.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';

Object.defineProperty(Object.getPrototypeOf(installDom().createElement('div')), 'hidden', {
  configurable: true,
  get() { return this.hasAttribute('hidden'); },
  set(on) { this.toggleAttribute('hidden', Boolean(on)); },
});
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { theatreBoard, forgetShapes } = await import('../js/views/realism-theatre.js');
const { forgetMarks } = await import('../js/views/realism-territory.js');
const { piecePanel } = await import('../js/views/realism-board.js');
const { needLines } = await import('../js/views/realism-needs.js');
const { realismRoom } = await import('../js/views/realism-room.js');
const { setRoomLayout } = await import('../js/views/realism-sheets.js');
const rules = await import('../js/realism-rules.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const TMAP = fixture.territory_map;
const LEVY = 'The Norra Levy';
const TODAY = '1900-04-16';

/** The toy world's movement form: its forces and the areas it sends to. */
const MOVE = {
  name: 'move_piece', label: 'Move a piece', summary: 'Send a piece to another area.', pipeline: 'field_order',
  params: [
    { name: 'force', label: 'Which piece', kind: 'enum', lo: null, hi: null, places: [], choices: [
      { value: 'norra_levy', label: LEVY }, { value: 'norra_kites', label: 'The Norra Kites' }] },
    { name: 'to', label: 'To', kind: 'enum', lo: null, hi: null, places: [], choices: [
      { value: 'norra_hills', label: 'The Norra Hills' }, { value: 'isle', label: 'The Isle' },
      { value: 'sudland_coast', label: 'The Sudland Coast' }, { value: 'the_gulf', label: 'The Gulf' }] },
  ],
};

/** A press paper the seat holds, as the listing gives it. */
const press = (id, title, issued) => ({
  id, kind: 'press', title, author: 'The Sudland Gazette', issued, arrives: issued, channel: 'press',
  classification: 'open', unread: true, flagged: false, group: null, ack: false,
});

/**
 * The seat in a battle at the Sudland Coast, day 3: its levy there, three rounds reported, the
 * enemy put at 1 to 4 by its papers, no decision given yet. `change(rv, battle)` adjusts it.
 */
function seat(change = () => {}) {
  const map = structuredClone(TMAP);
  const held = new Map(fixture.economy_areas.map((a) => [a.key, a.holder]));
  for (const a of map.areas) a.holder = held.get(a.key) ?? null;
  const levy = map.marks.find((m) => m.name === LEVY);
  levy.piece.area = { key: 'sudland_coast', name: 'The Sudland Coast', place: null };
  levy.piece.strength = 3;
  const battle = structuredClone(fixture.battles[0]);
  battle.rounds = [
    { on: '1900-04-14', own_lost: 1, enemy_lost: 1 },
    { on: '1900-04-15', own_lost: 0, enemy_lost: 2 },
    { on: '1900-04-16', own_lost: 1, enemy_lost: 0 },
  ];
  battle.enemy_strength = { low: 1, high: 4 };
  const rv = {
    ...structuredClone(fixture),
    map,
    battles: [battle],
    desk: { ...fixture.desk, levers: [structuredClone(MOVE)] },
    clock: { ...fixture.clock, world_date: TODAY },
    orders: { orders: [] },
    record: { orders: [] },
    documents: { ...fixture.listing, documents: [] },
  };
  change(rv, battle);
  return rv;
}

/** A small room: `pick` redraws the board as the room does; `act` is recorded and never answered. */
async function room(rv, ui = { piece: null, theatre: { mode: 'map', scope: 'reports' } }) {
  const acts = [];
  const opened = [];
  const was = globalThis.fetch;
  globalThis.fetch = async (url) => ({ ok: true, status: 200, json: async () => (url === '/api/realism/map' ? { reply: '', refused: false, file: TMAP.file, map: SHAPES } : {}) });
  const r = {
    ui, acts, opened, view: null,
    draw() {
      r.view?.remove();
      r.view = theatreBoard(rv, ui, {
        pick: (p) => { if (p.theatre) ui.theatre = p.theatre; if (p.piece !== undefined) ui.piece = p.piece; r.draw(); },
        act: (message, action, body, then) => { acts.push({ message, action, body, then }); },
        open: (p) => opened.push(p),
      });
      document.body.append(r.view);
      return r.view;
    },
  };
  try {
    forgetShapes();
    forgetMarks();
    r.draw();
    await new Promise((ok) => setTimeout(ok, 0));
    await new Promise((ok) => setTimeout(ok, 0));
  } finally { globalThis.fetch = was; }
  r.draw();
  return r;
}

const battleMarks = (view) => view.querySelectorAll('g.rl-bt-mark');
const markAt = (view, key) => battleMarks(view).find((g) => g.getAttribute('data-area') === key);
const sheetOf = (view) => view.querySelector('.rl-bt-sheet');
const button = (el, label) => el.querySelectorAll('button').find((b) => words(b).startsWith(label));
const decisionButtons = (el) => el.querySelectorAll('.rl-bt-decisions button');
const lit = (view) => view.querySelectorAll('g.rl-map-target').map((g) => g.getAttribute('data-area')).sort();
const litArea = (view, key) => view.querySelectorAll('g.rl-map-target').find((g) => g.getAttribute('data-area') === key);
const acted = (r, action) => r.acts.filter((a) => a.action === action).map((a) => a.body);

async function opened(change) {
  const r = await room(seat(change));
  markAt(r.view, 'sudland_coast').dispatchEvent({ type: 'click', target: null, preventDefault() {}, stopPropagation() {} });
  return r;
}

// --- rule 1: the battle mark; other battles as the news gave them ------------------------

test('an area with a battle the seat\'s nation is in carries a battle mark that says so in words', async () => {
  const r = await room(seat());
  const marks = battleMarks(r.view);
  assert.deepEqual(marks.map((g) => g.getAttribute('data-area')), ['sudland_coast']);
  const mark = marks[0];
  assert.equal(mark.getAttribute('data-battle'), 'own');
  assert.equal(mark.getAttribute('aria-label'), 'Battle at The Sudland Coast, day 3: you attack Sudland. Open the battle sheet');
  assert.ok(mark.querySelector('.rl-bt-glyph'), 'the crossed-swords glyph is drawn');
});

test('a battle the seat knows only from the press is marked as the press gave it and opens the paper, not a battle sheet', async () => {
  const r = await room(seat((rv) => {
    rv.documents.documents = [
      press('p-isle', 'The Sudland Gazette: Battle at The Isle: Sudland attacks Norra', '1900-04-15'),
      press('p-hills-1', 'The Sudland Gazette: Battle at The Norra Hills: Sudland att…', '1900-04-10'),
      press('p-hills-2', 'The Sudland Gazette: Battle at The Norra Hills ends: Norra holds', '1900-04-13'),
    ];
  }));
  assert.deepEqual(battleMarks(r.view).map((g) => g.getAttribute('data-area')).sort(), ['isle', 'sudland_coast'],
    'an ended battle carries no mark');
  const news = markAt(r.view, 'isle');
  assert.equal(news.getAttribute('data-battle'), 'news');
  assert.equal(news.getAttribute('aria-label'), 'In the press: The Sudland Gazette: Battle at The Isle: Sudland attacks Norra. Open the paper');
  news.dispatchEvent({ type: 'click', target: null, preventDefault() {}, stopPropagation() {} });
  assert.deepEqual(r.opened, [{ id: 'p-isle' }]);
  assert.equal(sheetOf(r.view), null, 'no battle sheet for a battle the seat is not in');
});

test('the press battles read from the papers: the latest word on an area decides, and the seat\'s own battles are left out', () => {
  const rv = seat((x) => {
    x.documents.documents = [
      press('a', 'The Gazette: Battle at The Isle: Sudland attacks Norra', '1900-04-15'),
      press('b', 'The Gazette: Battle at The Sudland Coast: Norra attacks Sudland', '1900-04-14'),
      press('c', 'The Gazette: Battle at The Norra Hills: Sudland attacks Norra', '1900-04-10'),
      press('d', 'The Gazette: Battle at The Norra Hills ends: Norra holds', '1900-04-12'),
    ];
  });
  assert.deepEqual(rules.newsBattles(rv).map((n) => [n.area, n.paper]), [['isle', 'a']]);
});

// --- rule 2: the sheet: rounds, strengths as pips, the enemy as a range, the decision in force

test('a tap on the mark opens the battle sheet: the day, both sides, each day\'s round and the decision in force', async () => {
  const r = await opened();
  const sheet = sheetOf(r.view);
  assert.ok(sheet, 'the sheet opens');
  assert.equal(words(sheet.querySelector('h3')), 'Battle at The Sudland Coast · day 3');
  const rows = sheet.querySelectorAll('table.rl-bt-days tbody tr').map((tr) => tr.querySelectorAll('td, th').map(words));
  assert.deepEqual(rows, [
    ['14 Apr', '1 step', '1 step'],
    ['15 Apr', 'none', '2 steps'],
    ['16 Apr', '1 step', 'none'],
  ]);
  assert.match(words(sheet.querySelector('.rl-bt-now')), /^At this wake's close: Press \(the attacker's default\) unless you change it$/);
});

test('the seat\'s strength is pips; the enemy\'s is a range, solid to the low end and hollow to the high end', async () => {
  const r = await opened();
  const sheet = sheetOf(r.view);
  const own = sheet.querySelector('.rl-bt-own g.rl-tm-pips');
  assert.equal(own.getAttribute('data-filled'), '3');
  const theirs = sheet.querySelector('.rl-bt-enemy g.rl-tm-pips');
  assert.equal(theirs.getAttribute('data-filled'), '1');
  assert.equal(theirs.getAttribute('data-slots'), '4');
  assert.equal(theirs.querySelectorAll('rect.rl-pip-empty').length, 3);
  assert.match(words(sheet.querySelector('.rl-bt-enemy')), /1 to 4, as your papers put Sudland there/);
});

test('the enemy\'s strength reads as a range in words, and as not yet reported before any paper places it', () => {
  assert.equal(rules.battleRangeWords({ enemy_strength: { low: 1, high: 4 } }), '1 to 4');
  assert.equal(rules.battleRangeWords({ enemy_strength: { low: 2, high: 2 } }), '2 to 2');
  assert.equal(rules.battleRangeWords({ enemy_strength: null }), 'not yet reported');
  assert.deepEqual(rules.battleRangePips({ enemy_strength: { low: 1, high: 4 } }), { filled: 1, slots: 4 });
  assert.equal(rules.battleRangePips({ enemy_strength: null }), null);
});

test('the decision in force: the side\'s own, else the attacker presses and the defender holds', () => {
  assert.deepEqual(rules.decisionInForce({ decision: 'withdraw', side: 'attacker' }), { decision: 'withdraw', given: true });
  assert.deepEqual(rules.decisionInForce({ decision: null, side: 'attacker' }), { decision: 'press', given: false });
  assert.deepEqual(rules.decisionInForce({ decision: null, side: 'defender' }), { decision: 'hold', given: false });
  assert.equal(rules.battleDay({ opened: '1900-04-14' }, TODAY), 3);
});

// --- rule 3: four decisions as buttons with one line each; choosing one files `battle` -------

test('the four decisions are buttons, each with one line on what it does; the one in force is pressed', async () => {
  const r = await opened((rv, b) => { b.decision = 'hold'; });
  const btns = decisionButtons(sheetOf(r.view));
  assert.deepEqual(btns.map((b) => b.querySelector('b').textContent), ['Press', 'Hold', 'Reinforce', 'Withdraw']);
  for (const b of btns) assert.ok(words(b.querySelector('span')).length > 20, `${words(b)} has its line`);
  assert.deepEqual(btns.filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.querySelector('b').textContent), ['Hold']);
});

test('Press and Hold file through the battle action, named by the battle\'s area', async () => {
  const r = await opened();
  button(sheetOf(r.view), 'Hold').click();
  assert.deepEqual(acted(r, 'battle'), [{ area: 'sudland_coast', decision: 'hold' }]);
  r.draw();
  button(sheetOf(r.view), 'Press').click();
  assert.deepEqual(acted(r, 'battle').at(-1), { area: 'sudland_coast', decision: 'press' });
});

test('a battle the seat may not decide now has no decision button: decided, between wakes, or none of its pieces', async () => {
  const r = await opened((rv, b) => { b.decisions = []; });
  const sheet = sheetOf(r.view);
  assert.equal(decisionButtons(sheet).length, 0, 'no button to file with');
  assert.match(words(sheet), /You cannot give this battle a decision now/);
});

test('no battle sheet, and so no decision button, for an area where the seat\'s nation is in no battle', async () => {
  const rv = seat((x) => {
    x.documents.documents = [press('p-isle', 'The Sudland Gazette: Battle at The Isle: Sudland attacks Norra', '1900-04-15')];
  });
  const r = await room(rv, { piece: null, theatre: { mode: 'map', scope: 'reports', battle: 'isle' } });
  assert.equal(sheetOf(r.view), null);
  assert.equal(r.view.querySelectorAll('.rl-bt-decisions button').length, 0);
});

test('Reinforce files nothing: it says to send a force from next door on the map', async () => {
  const r = await opened();
  button(sheetOf(r.view), 'Reinforce').click();
  assert.deepEqual(r.acts, []);
  assert.match(words(sheetOf(r.view).querySelector('.rl-bt-hint')), /Pick one of your forces next to The Sudland Coast on the map and put it down there/);
});

// --- withdraw and the fall-back: an area picked among the lit adjacent areas ----------------

test('the areas a side may fall back to: adjacent, of the same kind, held by its side or an ally', () => {
  const rv = seat();
  assert.deepEqual(rules.fallBackAreas(rv.map, 'sudland_coast'), ['norra_hills']);
  assert.deepEqual(rules.fallBackAreas(rv.map, 'norra_plain').sort(), ['isle', 'norra_hills']);
  assert.deepEqual(rules.fallBackAreas(rv.map, 'the_gulf').sort(), ['open_sea']);
  rv.map.areas.find((a) => a.key === 'norra_hills').holder = { key: 'S', name: 'Sudland', relation: 'enemy' };
  rv.map.areas.find((a) => a.key === 'isle').holder = { key: 'A', name: 'Ostra', relation: 'ally' };
  assert.deepEqual(rules.fallBackAreas(rv.map, 'norra_plain'), ['isle'], 'never into an enemy\'s area; an ally\'s is fine');
});

test('Withdraw lights the areas the side may fall back to; a lit one files the withdrawal to it', async () => {
  const r = await opened();
  button(sheetOf(r.view), 'Withdraw').click();
  assert.deepEqual(lit(r.view), ['norra_hills']);
  assert.deepEqual(r.acts, [], 'nothing is filed until an area is picked');
  litArea(r.view, 'norra_hills').dispatchEvent({ type: 'click', target: null, preventDefault() {}, stopPropagation() {} });
  assert.deepEqual(acted(r, 'battle'), [{ area: 'sudland_coast', decision: 'withdraw', to: 'norra_hills' }]);
});

test('an unlit area files nothing while an area is being picked', async () => {
  const r = await opened();
  button(sheetOf(r.view), 'Withdraw').click();
  r.view.querySelectorAll('path.rl-area').find((p) => p.getAttribute('data-area') === 'isle')
    .dispatchEvent({ type: 'click', target: null, preventDefault() {}, stopPropagation() {} });
  assert.deepEqual(r.acts, []);
});

// --- rule 4: the contingency picker on a piece's sheet ------------------------------------

function panel(rv, theatre = {}) {
  const picks = [];
  const acts = [];
  const el = piecePanel(rv, { kind: 'force', name: LEVY }, () => {}, {
    pick: (p) => picks.push(p), act: (m, a, b, t) => acts.push({ action: a, body: b, then: t }), theatre,
  });
  return { el, picks, acts };
}

test('a piece\'s sheet has the contingency picker: the four standing orders with a line each, the one in force pressed', () => {
  const { el } = panel(seat((rv, b) => { b.pieces[0].contingency = 'hold_fast'; }));
  const picker = el.querySelector('.rl-bt-contingency');
  assert.ok(picker, 'the picker is on the sheet');
  assert.equal(words(picker.querySelector('h3')), 'If you are not here');
  const btns = picker.querySelectorAll('.rl-bt-kinds button');
  assert.deepEqual(btns.map((b) => b.querySelector('b').textContent), ['Hold', 'Hold at all costs', 'Fall back', 'Withdraw when weak']);
  assert.deepEqual(btns.filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.querySelector('b').textContent), ['Hold at all costs']);
  assert.equal(picker.tagName, 'DETAILS');
  assert.equal(picker.hasAttribute('open'), false, 'folded, so a phone\'s piece sheet stays short and the lit places stay free');
  const picking = panel(seat(), { battlePick: { kind: 'fall_back', force: 'norra_levy', from: 'sudland_coast', name: LEVY } });
  assert.equal(picking.el.querySelector('.rl-bt-contingency').hasAttribute('open'), true, 'open while its area is picked');
});

test('Hold and Hold at all costs file the contingency for the piece\'s force', () => {
  const { el, acts } = panel(seat());
  button(el.querySelector('.rl-bt-contingency'), 'Hold at all costs').click();
  assert.deepEqual(acts.map((a) => [a.action, a.body]), [['contingency', { force: 'norra_levy', kind: 'hold_fast' }]]);
});

test('Fall back asks for its area on the map: it lights the lit adjacent areas of the piece', async () => {
  const { el, picks, acts } = panel(seat());
  button(el.querySelector('.rl-bt-contingency'), 'Fall back').click();
  assert.deepEqual(acts, []);
  assert.deepEqual(picks.map((p) => p.theatre.battlePick), [{ kind: 'fall_back', force: 'norra_levy', from: 'sudland_coast', name: LEVY }]);
  const ui = { piece: { kind: 'force', name: LEVY }, theatre: { mode: 'map', scope: 'reports', ...picks[0].theatre } };
  const r = await room(seat(), ui);
  assert.deepEqual(lit(r.view), ['norra_hills']);
  litArea(r.view, 'norra_hills').dispatchEvent({ type: 'click', target: null, preventDefault() {}, stopPropagation() {} });
  assert.deepEqual(acted(r, 'contingency'), [{ force: 'norra_levy', kind: 'fall_back', to: 'norra_hills' }]);
});

test('Withdraw when weak takes the strength to withdraw below, then its area on the map', async () => {
  const { el, picks } = panel(seat());
  const picker = el.querySelector('.rl-bt-contingency');
  const below = picker.querySelector('select[name="below"]');
  assert.deepEqual(below.querySelectorAll('option').map((o) => o.value), ['1', '2', '3']);
  below.value = '2';
  button(picker, 'Withdraw when weak').click();
  assert.deepEqual(picks.at(-1).theatre.battlePick, { kind: 'withdraw_below', force: 'norra_levy', from: 'sudland_coast', name: LEVY, below: 2 });
  const ui = { piece: { kind: 'force', name: LEVY }, theatre: { mode: 'map', scope: 'reports', ...picks.at(-1).theatre } };
  const r = await room(seat(), ui);
  litArea(r.view, 'norra_hills').dispatchEvent({ type: 'click', target: null, preventDefault() {}, stopPropagation() {} });
  assert.deepEqual(acted(r, 'contingency'), [{ force: 'norra_levy', kind: 'withdraw_below', to: 'norra_hills', below: 2 }]);
});

test('the battle sheet names each of the seat\'s pieces there with its standing order', async () => {
  const r = await opened((rv, b) => { b.pieces[0].contingency = 'fall_back'; });
  assert.match(words(sheetOf(r.view).querySelector('.rl-bt-standing')), /The Norra Levy: Fall back/);
});

// --- rule 5: a battle with no decision this wake is a line in "What needs you" --------------

test('a battle that waits on a decision is a line in "What needs you", due at the close, with one action', () => {
  const lines = needLines(seat()).filter((l) => l.kind === 'battle');
  assert.equal(lines.length, 1);
  const [line] = lines;
  assert.equal(line.what, 'The battle at The Sudland Coast: your decision for this wake');
  assert.equal(line.at, 'close');
  assert.equal(line.due, TODAY);
  assert.deepEqual(line.action, { word: 'Decide', to: 'battle', area: 'sudland_coast' });
});

test('a battle decided this wake, or one the seat cannot decide, is not a line', () => {
  assert.equal(needLines(seat((rv, b) => { b.decided = true; b.decisions = []; })).filter((l) => l.kind === 'battle').length, 0);
  assert.equal(needLines(seat((rv, b) => { b.decisions = []; })).filter((l) => l.kind === 'battle').length, 0);
  assert.equal(needLines(seat((rv, b) => { b.decided = true; })).filter((l) => l.kind === 'battle').length, 0,
    'decided is enough, whatever the decisions list says');
});

// --- rule 6: a decision waiting on a holder reads like any other order that waits ------------

test('a decision on its way reads like any other order that waits: the chip, its holder and the day', async () => {
  const r = await opened((rv, b) => {
    b.decided = true;
    b.decisions = [];
    rv.record.orders = [{
      id: 'o-bt', wake: 3, filed: '16 April 1900', settled: null, asked: 'The battle at The Sudland Coast: hold', to: null,
      holder: 'Ilse Varg', status: 'on its way', moving: true, track: null, due: '17 April 1900', said: null, receipt: null,
    }];
  });
  const waits = sheetOf(r.view).querySelector('.rl-bt-order');
  assert.ok(waits, 'the order is on the sheet');
  assert.deepEqual(waits.children.map(words), ['The battle at The Sudland Coast: hold', 'Under way', 'With Ilse Varg', 'Answer expected 17 April 1900']);
  assert.equal(decisionButtons(sheetOf(r.view)).length, 0);
});

test('a decision held for the next wake says so', async () => {
  const r = await opened((rv, b) => { b.decided = true; b.held = true; b.decisions = []; });
  assert.match(words(sheetOf(r.view)), /Your decision is held for the next wake and is filed when it opens/);
});

// --- the map-first room: the line opens the battle sheet over the map ----------------------

test('in the map-first room the list\'s Decide opens the battle sheet over the map, and Close puts focus back on the line', async () => {
  const doc = installDom();
  setRoomLayout('map');
  api.realism = async (action) => (action === 'map' ? { reply: '', refused: false, file: TMAP.file, map: SHAPES } : {});
  api.catchup = async () => ({});
  const rv = seat();
  rv.wake_tick = 1;
  const me = { account: { handle: 'josh' }, game: { id: `g-${Math.random()}`, name: 'Toy', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'Ilse' } } } };
  const ctx = { me, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {} };
  forgetShapes();
  const root = realismRoom(ctx);
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  await new Promise((ok) => setTimeout(ok, 0));
  await new Promise((ok) => setTimeout(ok, 0));
  const act = root.querySelectorAll('.rl-need-act').find((b) => b.getAttribute('data-need') === 'sudland_coast');
  assert.ok(act, 'the line is listed');
  act.click();
  const over = root.querySelector('.rl-over');
  assert.equal(over?.getAttribute('data-sheet'), 'battle');
  assert.equal(words(over.querySelector('.rl-over-title')), 'Battle at The Sudland Coast · day 3');
  assert.ok(over.querySelector('.rl-bt-decisions'), 'the decisions are on the sheet');
  assert.equal(root.querySelectorAll('.rl-bt-sheet').length, 1, 'one battle sheet, over the map');
  over.querySelector('.rl-over-close').click();
  assert.equal(root.querySelector('.rl-over'), null);
  const mark = root.querySelectorAll('.rl-mapfirst g.rl-bt-mark').find((g) => g.getAttribute('data-area') === 'sudland_coast');
  mark.dispatchEvent({ type: 'click', target: null, preventDefault() {}, stopPropagation() {} });
  assert.equal(root.querySelector('.rl-over')?.getAttribute('data-sheet'), 'battle', 'the map\'s mark opens the same sheet over the map');
  assert.equal(root.querySelectorAll('.rl-bt-sheet').length, 1);
});

test('in today\'s room the battle mark opens the battle sheet under the map', async () => {
  const doc = installDom();
  setRoomLayout('room');
  api.realism = async (action) => (action === 'map' ? { reply: '', refused: false, file: TMAP.file, map: SHAPES } : {});
  api.catchup = async () => ({});
  const rv = seat();
  rv.wake_tick = 1;
  const me = { account: { handle: 'josh' }, game: { id: `g-${Math.random()}`, name: 'Toy', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'Ilse' } } } };
  const ctx = { me, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {} };
  forgetShapes();
  let root = realismRoom(ctx);
  doc.body.append(root);
  await new Promise((ok) => setTimeout(ok, 0));
  await new Promise((ok) => setTimeout(ok, 0));
  root = doc.body.firstElementChild;
  const mark = root.querySelectorAll('g.rl-bt-mark').find((g) => g.getAttribute('data-area') === 'sudland_coast');
  assert.ok(mark, 'the mark is on the board');
  mark.dispatchEvent({ type: 'click', target: null, preventDefault() {}, stopPropagation() {} });
  root = doc.body.firstElementChild;
  assert.equal(root.querySelectorAll('.rl-bt-sheet').length, 1, 'the sheet is drawn');
  setRoomLayout('map');
});

// --- the styles ---------------------------------------------------------------------------

test('the battle styles are linked from the page and use the theme\'s tokens only, with 44 px buttons', () => {
  const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');
  assert.match(read('index.html'), /<link rel="stylesheet" href="\/css\/c-battle\.css">/);
  const css = read('css/c-battle.css');
  assert.equal(css.match(/#[0-9a-fA-F]{3,8}\b|rgba?\(/g), null, 'no raw colour');
  assert.match(css, /\.rl-bt-choice \{[^}]*min-height: 44px/);
  assert.match(css, /\.rl-bt-choice\[aria-pressed="true"\] b::after \{[^}]*in force/);
});
