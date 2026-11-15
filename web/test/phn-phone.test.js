// The board on a phone, and Board as the first view: the room opens on the Board at every
// width; a picked piece's panel is a sheet from the bottom on a narrow screen, with a close;
// on the Court the picked person's card sits in that panel; the court's paths scroll sideways.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { realismRoom, uiFor } = await import('../js/views/realism-room.js');
const { boardView } = await import('../js/views/realism-board.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const rv = (more = {}) => ({ ...fixture, documents: fixture.listing, wake_tick: 1, ...more });
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');

/** The whole room for a fresh game, in the page, with no model or server behind it. */
function room() {
  const doc = installDom();
  api.realism = async () => ({});
  const me = { account: { handle: 'josh' }, game: { id: `g-${Math.random()}`, name: 'Autumn 1941', view: { realism: rv(), seat: { name: 'Franklin D. Roosevelt' } } } };
  const root = realismRoom({ me, refresh: async () => {}, go: () => {} });
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  return root;
}

const pressed = (group) => group.querySelectorAll('button').filter((b) => b.getAttribute('aria-pressed') === 'true').map(words);
const current = (root) => root.querySelector('.rl-tabbar').querySelectorAll('button')
  .filter((b) => b.getAttribute('aria-current') === 'page').map((b) => words(b).split(' ')[0]);
const ui = (more = {}) => ({ view: 'board', board: 'theatre', piece: null, theatre: { mode: 'map', scope: 'reports' }, ...more });
const write = () => {
  const el = document.createElement('section');
  el.className = 'rl-write';
  return el;
};
const board = (r, u, pick = () => {}) => boardView(r, u, { pick, act: () => {}, write: write() });
const rayburn = fixture.court.paths[0].steps[0];
const person = { kind: 'person', person: rayburn.person, name: rayburn.name };
const square = (root, name) => root.querySelectorAll('button.rl-court-sq').find((b) => words(b).startsWith(name));

test('a fresh room opens on the Board, with the Theatre picked', () => {
  const state = uiFor(`g-${Math.random()}`);
  assert.equal(state.view, 'board');
  assert.equal(state.board, 'theatre');
});

test('the room opens on the Board: the switch marks Board, and no desk columns are drawn', () => {
  const root = room();
  assert.ok(root.querySelector('.rl-board'), 'the board');
  assert.equal(root.querySelector('main.rl-room'), null, 'no desk columns');
  assert.deepEqual(pressed(root.querySelector('.rl-viewswitch')), ['Board']);
});

test('on a phone the room opens on the Board too, and the tab bar marks the Board tab', () => {
  const before = globalThis.matchMedia;
  globalThis.matchMedia = (q) => ({ matches: q.includes('max-width'), media: q, addEventListener() {}, removeEventListener() {} });
  try {
    const root = room();
    assert.ok(root.querySelector('.rl-board'), 'the board');
    assert.equal(root.querySelector('main.rl-room'), null);
    assert.deepEqual(current(root), ['Board']);
  } finally {
    globalThis.matchMedia = before;
  }
});

test('a picked force\'s panel is a sheet with a Close that drops the pick; with nothing picked it is not', () => {
  const picked = [];
  const mark = fixture.map.marks[0];
  const chosen = board(rv(), ui({ piece: { kind: 'force', name: mark.name } }), (p) => picked.push(p));
  const panel = chosen.querySelector('.rl-board-side .rl-piece');
  assert.ok(panel.classList.contains('rl-sheet'), 'a sheet');
  buttons(panel, 'Close')[0].click();
  assert.deepEqual(picked, [{ piece: null }]);
  const empty = board(rv(), ui()).querySelector('.rl-piece');
  assert.equal(empty.classList.contains('rl-sheet'), false, 'nothing picked, no sheet');
  assert.equal(buttons(empty, 'Close').length, 0);
});

test('on the Court a picked person\'s card is in the side panel\'s sheet, and the court holds no second copy', () => {
  const picked = [];
  const chosen = board(rv(), ui({ board: 'court', piece: person }), (p) => picked.push(p));
  const panel = chosen.querySelector('.rl-board-side .rl-piece');
  assert.ok(panel.classList.contains('rl-sheet'), 'a sheet');
  const card = panel.querySelector('.rl-court-sel');
  assert.ok(card, 'the card in the panel');
  assert.match(words(card), new RegExp(rayburn.name));
  assert.ok(buttons(card, 'Ask them a question').length + buttons(card, 'Write them an order').length > 0, 'its moves');
  assert.equal(chosen.querySelectorAll('.rl-court-sel').length, 1, 'one card');
  assert.equal(chosen.querySelector('.rl-board-main .rl-court-sel'), null);
  assert.doesNotMatch(words(panel), /Nothing is selected/);
  buttons(panel, 'Close')[0].click();
  assert.deepEqual(picked, [{ piece: null }]);
});

test('a court with no chambers, its card moved to the panel, keeps no empty column', () => {
  const thin = rv({ court: { ...fixture.court, chambers: [] } });
  const chosen = board(thin, ui({ board: 'court', piece: person }));
  assert.equal(chosen.querySelector('.rl-court-aside'), null, 'no empty column');
  assert.ok(chosen.querySelector('.rl-court-body').classList.contains('single'), 'the paths take the width');
  assert.ok(chosen.querySelector('.rl-board-side .rl-court-sel'), 'the card is in the panel');
});

test('on the Court with nothing picked the panel asks for a person, not a force', () => {
  const text = words(board(rv(), ui({ board: 'court' })).querySelector('.rl-piece'));
  assert.match(text, /Pick a person on the court/);
  assert.doesNotMatch(text, /force on the map/);
});

test('in the room: a square tapped on the Court opens the sheet, and its Close shuts it', () => {
  const root = room();
  buttons(root.querySelector('.rl-boardswitch'), 'Court')[0].click();
  square(root, rayburn.name).click();
  const sheet = root.querySelector('.rl-board-side .rl-piece.rl-sheet');
  assert.ok(sheet, 'the sheet');
  assert.ok(sheet.querySelector('.rl-court-sel'), 'with the card');
  buttons(sheet, 'Close')[0].click();
  assert.equal(root.querySelector('.rl-piece.rl-sheet'), null, 'the sheet is shut');
  assert.equal(square(root, rayburn.name).getAttribute('aria-pressed'), 'false', 'the square is no longer picked');
});

/** A tap: the button takes focus, as in a browser, then the click. */
const tap = (b) => {
  b.focus();
  b.click();
};

test('in the room: Close puts focus back on the square or mark that was picked', () => {
  const root = room();
  buttons(root.querySelector('.rl-boardswitch'), 'Court')[0].click();
  square(root, rayburn.name).click();
  tap(buttons(root.querySelector('.rl-piece.rl-sheet'), 'Close')[0]);
  assert.equal(document.activeElement, square(root, rayburn.name), 'the square');
  buttons(root.querySelector('.rl-boardswitch'), 'Theatre')[0].click();
  const mark = () => root.querySelectorAll('.rl-board .rl-map-svg .rl-mk')[1];
  mark().click();
  tap(buttons(root.querySelector('.rl-piece.rl-sheet'), 'Close')[0]);
  assert.equal(root.querySelector('.rl-piece.rl-sheet'), null);
  assert.equal(document.activeElement, mark(), 'the mark');
});

test('c-board.css at 600 px and narrower: the panel is a bottom sheet above the tab bar and the court\'s paths scroll sideways', () => {
  const css = read('css/c-board.css').replace(/\/\*[\s\S]*?\*\//g, '');
  const at = css.indexOf('@media (max-width: 600px)');
  assert.ok(at >= 0, 'a 600 px rule');
  const narrow = css.slice(at);
  const rule = (sel) => narrow.match(new RegExp(`${sel.replace(/[.[\]()]/g, '\\$&')} \\{([^}]*)\\}`))?.[1] ?? '';
  const sheet = rule('.rl-board-side .rl-piece.rl-sheet');
  assert.match(sheet, /position: fixed/);
  assert.match(sheet, /left: 0/);
  assert.match(sheet, /right: 0/);
  assert.match(sheet, /bottom: 45px/, 'above the tab bar (44px and a 1px rule)');
  assert.match(sheet, /max-height: /);
  assert.match(sheet, /overflow-y: auto/);
  assert.match(rule('.rl-sheet-close'), /display: flex/, 'the close shows on a phone');
  assert.match(css.slice(0, at), /\.rl-sheet-close \{[^}]*display: none/, 'and not on a wider screen');
  const line = rule('.rl-board .rl-court-line');
  assert.match(line, /flex-wrap: nowrap/);
  assert.match(line, /overflow-x: auto/);
  assert.match(rule('.rl-board .rl-court-step'), /flex: none/);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(/, 'tokens only');
});
