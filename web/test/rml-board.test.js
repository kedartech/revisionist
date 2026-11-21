// Board and Desk views: one switch between the room as it is (Desk) and the Board (the first
// view), whose Theatre or Court sits beside the selected piece's panel and the order form.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { pickPanel, realismRoom, uiFor } = await import('../js/views/realism-room.js');
const { boardView, viewSwitch } = await import('../js/views/realism-board.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const rv = () => ({ ...fixture, documents: fixture.listing, wake_tick: 1 });

/** The whole room for a fresh game, in the page, with no model or server behind it. */
function room(id = `g-${Math.random()}`) {
  const doc = installDom();
  api.realism = async () => ({});
  const me = { account: { handle: 'josh' }, game: { id, name: 'Autumn 1941', view: { realism: rv(), seat: { name: 'Franklin D. Roosevelt' } } } };
  const root = realismRoom({ me, refresh: async () => {}, go: () => {} });
  // the fake DOM has no layout; the room scrolls a form into view
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  return { root, id };
}

const pressed = (group) => group.querySelectorAll('button').filter((b) => b.getAttribute('aria-pressed') === 'true').map(words);
const ui = (more = {}) => ({ view: 'board', board: 'theatre', piece: null, theatre: { mode: 'map', scope: 'reports' }, ...more });
const write = () => {
  const el = document.createElement('section');
  el.className = 'rl-write';
  return el;
};

test('the room has a switch to Desk, which draws the desk in place of the board', () => {
  const { root } = room();
  const sw = root.querySelector('.rl-viewswitch');
  assert.ok(sw, 'a view switch');
  assert.deepEqual(sw.querySelectorAll('button').map(words), ['Board', 'Desk']);
  buttons(sw, 'Desk')[0].click();
  assert.deepEqual(pressed(root.querySelector('.rl-viewswitch')), ['Desk']);
  assert.ok(root.querySelector('main.rl-room'), 'the desk columns');
  assert.equal(root.querySelector('.rl-board'), null, 'no board');
});

test('Board in the switch puts the board in place of the desk, and Desk brings the desk back', () => {
  const { root } = room();
  buttons(root.querySelector('.rl-viewswitch'), 'Board')[0].click();
  assert.ok(root.querySelector('.rl-board'), 'the board');
  assert.equal(root.querySelector('main.rl-room'), null, 'no desk columns');
  assert.deepEqual(pressed(root.querySelector('.rl-viewswitch')), ['Board']);
  buttons(root.querySelector('.rl-viewswitch'), 'Desk')[0].click();
  assert.ok(root.querySelector('main.rl-room'), 'the desk columns are back');
  assert.equal(root.querySelector('.rl-board'), null);
});

test('the order form beside the board keeps the words typed on the desk', () => {
  const { root, id } = room();
  uiFor(id).draft = { to: '', channel: '', text: 'Put the Atlantic Fleet on convoy duty.' };
  buttons(root.querySelector('.rl-viewswitch'), 'Board')[0].click();
  const field = root.querySelector('.rl-board-side .rl-write textarea');
  assert.ok(field, 'the order form is beside the board');
  assert.equal(words(field), 'Put the Atlantic Fleet on convoy duty.');
});

test('on a phone the tab bar starts with Board, and a tap on it opens the board', () => {
  const { root } = room();
  const tabs = () => root.querySelector('.rl-tabbar').querySelectorAll('button');
  assert.deepEqual(tabs().map((b) => words(b).split(' ')[0]), ['Board', 'Papers', 'Desk', 'Orders', 'Messages']);
  tabs()[0].click();
  assert.ok(root.querySelector('.rl-board'), 'the board');
  const current = tabs().filter((b) => b.getAttribute('aria-current') === 'page').map((b) => words(b).split(' ')[0]);
  assert.deepEqual(current, ['Board']);
  tabs().find((b) => words(b).startsWith('Orders')).click();
  assert.ok(root.querySelector('main.rl-room'), 'a desk panel tab brings the desk back');
});

test('a fresh room is on the Board view with the Theatre picked', () => {
  const state = uiFor(`g-${Math.random()}`);
  assert.equal(state.view, 'board');
  assert.equal(state.board, 'theatre');
});

test('panel picks: Board and Desk set the view; a desk tab means Desk; Messages leaves the view', () => {
  const state = { view: 'desk', tab: 'desk', side: 'papers', chat: { open: true } };
  pickPanel(state, { view: 'board' }, false);
  assert.equal(state.view, 'board');
  pickPanel(state, { tab: 'messages' }, false);
  assert.equal(state.view, 'board');
  pickPanel(state, { tab: 'papers' }, false);
  assert.equal(state.view, 'desk');
  pickPanel(state, { tab: 'board' }, true);
  assert.equal(state.view, 'board');
  assert.equal(state.chat.open, false, 'on a phone the board tab closes the messenger');
  pickPanel(state, { view: 'desk' }, false);
  assert.equal(state.view, 'desk');
});

test('the view switch marks the view and picks by view', () => {
  const picked = [];
  const sw = viewSwitch({ view: 'board' }, (p) => picked.push(p));
  assert.ok(sw.getAttribute('aria-label'), 'a named group');
  assert.deepEqual(pressed(sw), ['Board']);
  for (const b of sw.querySelectorAll('button')) b.click();
  assert.deepEqual(picked, [{ view: 'board' }, { view: 'desk' }]);
});

test('the Theatre draws the seat\'s map, one mark for each mark it holds', () => {
  const picked = [];
  const board = boardView(rv(), ui(), { pick: (p) => picked.push(p), act: () => {}, write: write() });
  const sw = board.querySelector('.rl-boardswitch');
  assert.deepEqual(sw.querySelectorAll('button').map(words), ['Theatre', 'Court']);
  assert.deepEqual(pressed(sw), ['Theatre']);
  assert.ok(board.querySelector('svg.rl-map-svg'), 'the map');
  assert.equal(board.querySelectorAll('.rl-map-svg .rl-mk').length, fixture.map.marks.length);
  buttons(sw, 'Court')[0].click();
  assert.deepEqual(picked, [{ board: 'court' }]);
});

test('the Court draws the court\'s paths and no map', () => {
  const board = boardView(rv(), ui({ board: 'court' }), { pick: () => {}, act: () => {}, write: write() });
  assert.deepEqual(pressed(board.querySelector('.rl-boardswitch')), ['Court']);
  assert.ok(board.querySelector('.rl-board-main .rl-court-paths'), 'the court board');
  assert.equal(board.querySelector('svg.rl-map-svg'), null);
});

test('to the right of the board: the selected piece\'s panel, then the order form', () => {
  const board = boardView(rv(), ui(), { pick: () => {}, act: () => {}, write: write() });
  const side = board.querySelector('.rl-board-side');
  assert.ok(side, 'a side panel');
  const parts = [...side.children].map((c) => c.className);
  const piece = parts.findIndex((c) => c.includes('rl-piece'));
  const form = parts.findIndex((c) => c.includes('rl-write'));
  assert.ok(piece >= 0 && form >= 0 && piece < form, `piece panel above the form: ${parts.join(' | ')}`);
  assert.match(words(side.querySelector('.rl-piece')), /Nothing is selected/);
});

test('a mark picked on the Theatre is the selected piece, and the panel names it and where it is', () => {
  const picked = [];
  const mark = fixture.map.marks[0];
  const board = boardView(rv(), ui(), { pick: (p) => picked.push(p), act: () => {}, write: write() });
  board.querySelector('.rl-map-svg .rl-mk').click();
  assert.equal(picked.length, 1);
  const name = picked[0].piece?.name;
  assert.deepEqual(picked[0].piece, { kind: 'force', name });
  const chosen = boardView(rv(), ui({ piece: { kind: 'force', name: mark.name } }), { pick: () => {}, act: () => {}, write: write() });
  const panel = words(chosen.querySelector('.rl-piece'));
  assert.match(panel, new RegExp(mark.name));
  assert.match(panel, new RegExp(mark.places.at(-1).name));
  const gone = boardView(rv(), ui({ piece: { kind: 'force', name: 'No such fleet' } }), { pick: () => {}, act: () => {}, write: write() });
  assert.match(words(gone.querySelector('.rl-piece')), /Nothing is selected/);
});

test('the selected piece\'s panel opens the page that placed it', () => {
  const opened = [];
  const mark = fixture.map.marks[0];
  const board = boardView(rv(), ui({ piece: { kind: 'force', name: mark.name } }), { pick: () => {}, act: () => {}, write: write(), open: (d) => opened.push(d) });
  buttons(board.querySelector('.rl-piece'), 'Open the page')[0].click();
  assert.deepEqual(opened, [{ id: mark.document }]);
});

test('c-board.css is linked and lays out the board: two columns, one on a phone with five tabs', () => {
  const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');
  assert.ok(read('index.html').includes('href="/css/c-board.css"'), 'linked from the page');
  const css = read('css/c-board.css').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.match(css, /\.rl-board \{[^}]*grid-template-columns: minmax\(0, 1fr\) minmax\(300px, 380px\)/);
  const phone = css.slice(css.indexOf('@media (max-width: 767px)'));
  assert.match(phone, /\.rl-tabbar\.rl-tabbar-board \{ grid-template-columns: repeat\(5, minmax\(0, 1fr\)\)/);
  assert.match(phone, /\.rl-board \{ grid-template-columns: minmax\(0, 1fr\);/);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b/, 'tokens only');
});

test('a form the aide offers in the messenger, picked on the Board, opens on the Desk', () => {
  const { root, id } = room();
  buttons(root.querySelector('.rl-viewswitch'), 'Board')[0].click();
  uiFor(id).chat = { open: true, tab: 'chats', thread: 'aide' };
  buttons(root.querySelector('.rl-viewswitch'), 'Board')[0].click();
  const offer = root.querySelectorAll('button.rl-th-offer').find((b) => words(b).includes('Send a bill to Congress'));
  assert.ok(offer, 'the aide\'s offer in its thread');
  offer.click();
  assert.ok(root.querySelector('main.rl-room'), 'the Desk view, where the standard forms are');
  const form = root.querySelector('.rl-instrument[data-lever="send_bill"]');
  assert.ok(form, 'the bill form on the desk');
  const fold = form.closest('details');
  assert.ok(!fold || fold.open === true, 'its fold is open');
  assert.ok(root.querySelector('main.rl-room').querySelector('.rl-instrument[data-lever="send_bill"]'), 'on the desk');
});

test('Open the page on the Board reads the paper and shows it on the Desk, in the in-tray', async () => {
  const { root, id } = room();
  const asked = [];
  api.realism = async (action, body) => { asked.push([action, body]); return action === 'read' ? fixture.page : {}; };
  const mark = fixture.map.marks[0];
  buttons(root.querySelector('.rl-viewswitch'), 'Board')[0].click();
  root.querySelector('.rl-board .rl-map-svg .rl-mk').click();
  buttons(root.querySelector('.rl-piece'), 'Open the page')[0].click();
  for (let i = 0; i < 20 && !asked.some(([a]) => a === 'read'); i++) await new Promise((r) => setTimeout(r, 5));
  await new Promise((r) => setTimeout(r, 5));
  assert.deepEqual(asked.filter(([a]) => a === 'read'), [['read', { doc_id: mark.document }]]);
  assert.equal(uiFor(id).view, 'desk');
  assert.equal(uiFor(id).tab, 'papers');
  // the app re-reads the game and builds the room again from the same picks
  const again = room(id).root;
  assert.ok(again.querySelector('main.rl-room'), 'the Desk view');
  assert.match(words(again.querySelector('.rl-papers')), /House count on the Neutrality Act revision/);
});

const pinFor = (patch = {}, more = {}) => {
  const view = { ...rv(), ...patch };
  return boardView(view, ui(more), { pick: () => {}, act: () => {}, write: write() }).querySelector('.rl-pin');
};
const withAims = (aims) => ({ desk: { ...fixture.desk, aims }, stakes: undefined });
const withDates = (dates, world_date = '1941-10-20') => ({
  setting: { ...fixture.setting, dates },
  clock: { ...fixture.clock, world_date },
});

test('the Board pins the seat\'s aims: .rl-pin-aims, one child element for each aim', () => {
  const aims = ['Keep Britain supplied.', 'Protect the Atlantic convoys.', 'Stay out of a declared war.'];
  const list = pinFor(withAims(aims)).querySelector('.rl-pin-aims');
  assert.ok(list, 'the aims container');
  assert.deepEqual(list.children.map(words), aims);
  assert.equal(list.childNodes.length, aims.length, 'nothing but the aims in it');
});

test('with no aims the pin has no aims container', () => {
  assert.equal(pinFor(withAims([])).querySelector('.rl-pin-aims'), null);
  const older = { ...rv(), desk: { ...fixture.desk }, stakes: undefined };
  delete older.desk.aims;
  assert.equal(boardView(older, ui(), { pick: () => {}, act: () => {}, write: write() }).querySelector('.rl-pin-aims'), null);
});

test('the Board pins the first history date after today, with its words, and not a past one', () => {
  const pin = pinFor();
  const next = pin.querySelector('.rl-pin-next');
  assert.ok(next, 'the next-date line');
  assert.match(words(next), /31 October 1941/);
  assert.match(words(next), /USS Reuben James is sunk\./);
  assert.doesNotMatch(words(pin), /17 October/);
  assert.doesNotMatch(words(pin), /Kearny/);
});

test('the pinned date is the earliest one after today whatever order the dates come in, and a date on today is not after it', () => {
  const dates = [
    { on: '9 November 1941', what: 'Later.' },
    { on: '20 October 1941', what: 'Today itself.' },
    { on: '2 November 1941', what: 'Soonest ahead.' },
    { on: '1 October 1941', what: 'Past.' },
  ];
  const next = pinFor(withDates(dates)).querySelector('.rl-pin-next');
  assert.match(words(next), /2 November 1941/);
  assert.match(words(next), /Soonest ahead\./);
  assert.doesNotMatch(words(next), /Later|Today itself|Past/);
});

test('past the last date on history\'s clock no date is pinned, and the aims stay', () => {
  const pin = pinFor(withDates(fixture.setting.dates, '1941-12-07'));
  assert.equal(pin.querySelector('.rl-pin-next'), null);
  assert.ok(pin.querySelector('.rl-pin-aims'));
  assert.equal(pinFor({ setting: null }).querySelector('.rl-pin-next'), null);
});

test('the pin reads in words: no ISO date, no underscore', () => {
  assert.doesNotMatch(words(pinFor()), /\d{4}-\d{2}-\d{2}|_/);
});

test('the pin is the first thing on the Board, on the Theatre and on the Court', () => {
  for (const board of ['theatre', 'court']) {
    const view = boardView(rv(), ui({ board }), { pick: () => {}, act: () => {}, write: write() });
    const main = view.querySelector('.rl-board-main');
    assert.ok(main.children[0].classList.contains('rl-pin'), board);
    assert.ok(main.children[1].classList.contains('rl-boardswitch'), board);
  }
});

test('keyboard path: the pin takes focus by Tab, is named, and nothing in it has a positive tab index', () => {
  const pin = pinFor();
  assert.equal(pin.tagName, 'SECTION');
  assert.equal(pin.getAttribute('tabindex'), '0');
  assert.match(pin.getAttribute('aria-label') ?? '', /aims.*next/i);
  for (const el of [pin, ...pin.querySelectorAll('[tabindex]')]) {
    const t = el.getAttribute('tabindex');
    assert.ok(t === null || Number(t) <= 0, `${el.tagName} tabindex ${t}`);
  }
  pin.focus();
  assert.equal(document.activeElement, pin);
});

test('p5-board.css is linked, holds the pin and scopes every selector to it', () => {
  const css = readFileSync(new URL('../css/p5-board.css', import.meta.url), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.ok(css.trim().length > 0, 'the stylesheet has rules');
  assert.match(readFileSync(new URL('../index.html', import.meta.url), 'utf8'), /href="\/css\/p5-board\.css"/);
  const outer = css.replace(/@(media|container|supports)[^{]+\{/g, '');
  const sels = [...outer.matchAll(/([^{}]+)\{/g)].flatMap((m) => m[1].split(',')).map((s) => s.trim()).filter(Boolean);
  assert.ok(sels.length > 0);
  for (const sel of sels) assert.match(sel, /\.rl-pin/, sel);
  assert.doesNotMatch(css, /#[0-9a-f]{3,8}\b|\brgba?\(/i, 'tokens only');
});
