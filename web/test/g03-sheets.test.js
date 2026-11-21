// The map-first room: a second layout, chosen from the game menu, where the map fills the
// screen and Papers, Orders, Forms, Messages, the Court, People and Press each open as a sheet
// over it, one at a time; the minute poll and a layer change keep the open sheet and its form.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, fire, installDom, words } from './dom-fake.js';

// the fake DOM has no `hidden` property; the forms' Draft toggle reads and writes it
Object.defineProperty(Object.getPrototypeOf(installDom().createElement('div')), 'hidden', {
  configurable: true,
  get() { return this.hasAttribute('hidden'); },
  set(on) { this.toggleAttribute('hidden', Boolean(on)); },
});
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { realismRoom, uiFor } = await import('../js/views/realism-room.js');
const { roomLayout, setRoomLayout } = await import('../js/views/realism-sheets.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');
const SHEET_NAMES = ['Papers', 'Orders', 'Forms', 'Messages', 'Court', 'People', 'Press'];

/** The seat's view, each form pointing at the court path that lists its label, so it has a cost strip. */
function view() {
  const court = structuredClone(fixture.court);
  const levers = structuredClone(fixture.desk.levers).map((l) => {
    const path = court.paths.find((p) => p.forms.includes(l.label));
    return path ? { ...l, pipeline: path.id } : l;
  });
  return { ...structuredClone(fixture), court, desk: { ...fixture.desk, levers }, documents: fixture.listing, wake_tick: 1 };
}

const gameOf = (id) => ({ id, name: 'Autumn 1941', ruleset: 'realism', phase: 'play', host: true, view: { realism: view(), seat: { name: 'Franklin D. Roosevelt' } } });

/** The whole room for a fresh game in the page, in `layout`, with no model or server behind it. */
function room(layout = 'map', id = `g-${Math.random()}`) {
  const doc = installDom();
  setRoomLayout(layout);
  api.realism = async () => ({});
  api.catchup = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  const me = { account: { handle: 'josh' }, game: gameOf(id) };
  // the room is re-read after a call, as app.js does: the page's room is drawn again in place
  const ctx = { me, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {} };
  const root = realismRoom(ctx);
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  return { root, id, now: () => doc.body.firstElementChild };
}

const key = (el, k) => el.dispatchEvent({
  type: 'keydown', key: k, target: null, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() {},
});
const tabs = (root) => root.querySelector('.rl-sheettabs');
const tab = (root, name) => tabs(root).querySelectorAll('button').find((b) => words(b).startsWith(name));
const sheets = (root) => root.querySelectorAll('.rl-over');
const openSheet = (root) => sheets(root).map((s) => s.getAttribute('data-sheet'));
const settle = () => new Promise((r) => setTimeout(r, 0));
const Element = Object.getPrototypeOf(installDom().createElement('div')).constructor;
const mark = (root, name) => root.querySelectorAll('.rl-mapfirst .rl-mk').find((m) => (m.getAttribute('aria-label') ?? '').startsWith(`${name}:`));

// rule 1: a second layout beside today's, chosen from the game menu; today's stays the default

test('today\'s room is the default layout, with its Board and Desk switch and no map-first screen', () => {
  setRoomLayout(null);
  assert.equal(roomLayout(), 'room');
  const { root } = room('room');
  assert.ok(root.querySelector('.rl-viewswitch'), 'the Board and Desk switch');
  assert.equal(root.querySelector('.rl-mapfirst'), null);
});

test('the game menu offers the two layouts, and Map first redraws the room with the map as the screen', () => {
  const { root } = room('room');
  root.querySelector('.rl-menu-btn').click();
  const menu = root.querySelector('dialog.rl-menu');
  const group = menu.querySelector('.rl-layout');
  assert.ok(group, 'a layout choice in the menu');
  assert.deepEqual(group.querySelectorAll('button').map(words), ['Today\'s room', 'Map first']);
  assert.deepEqual(group.querySelectorAll('button[aria-pressed="true"]').map(words), ['Today\'s room']);
  buttons(group, 'Map first')[0].click();
  assert.equal(roomLayout(), 'map');
  assert.ok(root.querySelector('.rl-mapfirst'), 'the map-first screen');
  assert.ok(root.querySelector('.rl-mapfirst .rl-theatre'), 'the map fills it');
  assert.equal(root.querySelector('main.rl-room'), null, 'no desk columns');
  assert.equal(root.querySelector('.rl-viewswitch'), null, 'no Board and Desk switch');
  root.querySelector('.rl-menu-btn').click();
  buttons(root.querySelector('dialog.rl-menu .rl-layout'), 'Today\'s room')[0].click();
  assert.equal(root.querySelector('.rl-mapfirst'), null);
  assert.ok(root.querySelector('.rl-viewswitch'), 'today\'s room is back');
});

test('the layout chosen holds for the page: another game\'s room opens in it', () => {
  room('map');
  setRoomLayout('map');
  const { root } = room('map');
  assert.ok(root.querySelector('.rl-mapfirst'));
  setRoomLayout('room');
});

// rule 2: the map fills the screen; each of the seven opens as a sheet over it

test('the sheet tabs name the seven sheets, and each opens over the map', () => {
  const { root } = room();
  // DPL: a game with agreements or conferences adds the Diplomacy sheet after the seven
  assert.deepEqual(tabs(root).querySelectorAll('button').map((b) => words(b).split(' ')[0]), [...SHEET_NAMES, 'Diplomacy']);
  assert.deepEqual(openSheet(root), [], 'the bare map');
  for (const name of [...SHEET_NAMES, 'Diplomacy']) {
    tab(root, name).click();
    const [sheet] = sheets(root);
    assert.ok(sheet, name);
    assert.equal(words(sheet.querySelector('.rl-over-title')), name);
    assert.equal(sheet.getAttribute('role'), 'dialog');
    assert.ok(root.querySelector('.rl-mapfirst .rl-theatre'), `the map stays under ${name}`);
    assert.equal(tab(root, name).getAttribute('aria-expanded'), 'true');
  }
});

test('each sheet holds its panel: the papers, the orders, the forms, the messenger, the court, the roster, the newspapers', () => {
  const { root } = room();
  const inside = { Papers: '.rl-tray', Orders: '.rl-oc', Forms: '.rl-instrument', Messages: '.rl-msgr-panel', Court: '.rl-court', People: '.rl-people', Press: '.rl-pd-body' };
  for (const [name, sel] of Object.entries(inside)) {
    tab(root, name).click();
    assert.ok(sheets(root)[0].querySelector(sel), `${name} holds ${sel}`);
  }
});

test('c-sheets.css: at the side from 1024 px, a half sheet from the bottom below it; tokens only', () => {
  const css = read('css/c-sheets.css').replace(/\/\*[\s\S]*?\*\//g, '');
  const wide = css.indexOf('@media (min-width: 1024px)');
  assert.ok(wide >= 0, 'a 1024 px rule');
  const rule = (src, sel) => src.match(new RegExp(`${sel.replace(/[.[\]()]/g, '\\$&')} \\{([^}]*)\\}`))?.[1] ?? '';
  const base = rule(css.slice(0, wide), '.rl-over');
  assert.match(base, /position: fixed/);
  assert.match(base, /bottom: /);
  assert.match(base, /max-height: 50/, 'a half sheet');
  const side = rule(css.slice(wide), '.rl-over');
  assert.match(side, /right: /);
  assert.match(side, /top: /);
  assert.match(side, /width: /);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(/, 'tokens only');
  assert.match(read('index.html'), /href="\/css\/c-sheets\.css"/, 'the page loads it');
});

// rule 3: one sheet at a time; Escape closes it and focus goes back to what opened it

test('one sheet at a time: opening another replaces the first', () => {
  const { root } = room();
  tab(root, 'Papers').click();
  tab(root, 'Orders').click();
  assert.deepEqual(openSheet(root), ['orders']);
  for (const [name, key] of [['Press', 'press'], ['Messages', 'messages'], ['Papers', 'papers'], ['Press', 'press'], ['Forms', 'forms']]) {
    tab(root, name).click();
    assert.deepEqual(openSheet(root), [key], `after ${name}`);
    assert.deepEqual(tabs(root).querySelectorAll('button[aria-expanded="true"]').map((b) => b.getAttribute('data-sheet')), [key]);
  }
  tab(root, 'Forms').click();
  assert.deepEqual(openSheet(root), [], 'its own tab closes it');
});

test('Escape closes the sheet and focus goes back to the tab that opened it', () => {
  const { root } = room();
  const opener = tab(root, 'People');
  opener.focus();
  opener.click();
  assert.ok(sheets(root)[0].contains?.(document.activeElement) ?? document.activeElement.closest('.rl-over'), 'focus is in the sheet');
  key(sheets(root)[0], 'Escape');
  assert.deepEqual(openSheet(root), []);
  assert.equal(document.activeElement, tab(root, 'People'));
});

test('the sheet\'s Close does the same as Escape', () => {
  const { root } = room();
  tab(root, 'Court').focus();
  tab(root, 'Court').click();
  buttons(sheets(root)[0].querySelector('.rl-over-head'), 'Close')[0].click();
  assert.deepEqual(openSheet(root), []);
  assert.equal(document.activeElement, tab(root, 'Court'));
});

// rule 4: every standard form opens in a sheet with its cost strip

test('in the Forms sheet every standard form that has a court path shows its cost strip when opened', () => {
  const { root } = room();
  tab(root, 'Forms').click();
  const items = sheets(root)[0].querySelectorAll('.rl-instrument');
  assert.equal(items.length, view().desk.levers.length);
  const linked = view().desk.levers.filter((l) => fixture.court.paths.some((p) => p.id === l.pipeline));
  assert.ok(linked.length > 0, 'the fixture links a form to a path');
  for (const l of linked) {
    const item = items.find((i) => i.getAttribute('data-lever') === l.name);
    item.querySelector('[aria-expanded]').click();
    assert.ok(item.querySelector('.rl-cost'), `${l.name} has its strip`);
  }
});

test('a picked force\'s sheet holds the form that moves it, with its cost strip', () => {
  const { root } = room();
  mark(root, 'US Atlantic Fleet').click();
  const [sheet] = sheets(root);
  assert.equal(sheet.getAttribute('data-sheet'), 'piece');
  const item = sheet.querySelector('.rl-instrument[data-lever="move_fleet"]');
  assert.ok(item, 'the moving form is in the sheet');
  assert.ok(item.querySelector('.rl-cost'), 'with its strip');
});

// rule 5: the minute poll and a layer change keep the open sheet, its form values and a picked destination

/** Fill the moving form in the force's sheet: a destination the map holds, picked from its list. */
function fillMove(root) {
  const item = sheets(root)[0].querySelector('.rl-instrument[data-lever="move_fleet"]');
  const onMap = new Set(fixture.map.places.map((p) => p.name));
  const radio = item.querySelectorAll('input[type="radio"]')
    .find((r) => !r.disabled && onMap.has(words(r.closest('label').querySelector('.rl-place-name'))));
  radio.checked = true;
  fire(radio, 'change');
  return radio.value;
}

const picked = (root) => sheets(root)[0]?.querySelector('.rl-instrument[data-lever="move_fleet"] input[type="hidden"]')?.value;

test('a layer change keeps the force\'s sheet and the destination picked', () => {
  const { root } = room();
  mark(root, 'US Atlantic Fleet').click();
  const to = fillMove(root);
  buttons(root.querySelector('.rl-mapfirst'), 'Diplomatic')[0].click();
  assert.deepEqual(openSheet(root), ['piece']);
  buttons(root.querySelector('.rl-mapfirst'), 'Military')[0].click();
  assert.deepEqual(openSheet(root), ['piece']);
  assert.equal(picked(root), to);
  assert.ok(root.querySelector('.rl-mapfirst .rl-map-target.chosen'), 'the destination is lit as chosen');
});

test('the Forms sheet keeps a form open and its values over a redraw', () => {
  const { root } = room();
  tab(root, 'Forms').click();
  const item = () => sheets(root)[0].querySelector('.rl-instrument[data-lever="lend_lease_finding"]');
  item().querySelector('[aria-expanded]').click();
  item().querySelector('select[name="recipient"]').value = item().querySelectorAll('select[name="recipient"] option')[1].getAttribute('value');
  item().querySelector('input[name="share_pct"]').value = '30';
  const recipient = item().querySelector('select[name="recipient"]').value;
  buttons(root.querySelector('.rl-mapfirst'), 'Diplomatic')[0].click();
  assert.deepEqual(openSheet(root), ['forms']);
  assert.equal(item().querySelector('[aria-expanded]').getAttribute('aria-expanded'), 'true');
  assert.equal(item().querySelector('select[name="recipient"]').value, recipient);
  assert.equal(item().querySelector('input[name="share_pct"]').value, '30');
});

test('the minute poll (a faked interval) keeps the open sheet, its form values and the picked destination', async () => {
  const doc = installDom();
  setRoomLayout('map');
  const app = doc.createElement('div');
  doc.body.append(app);
  doc.getElementById = () => app;
  // app.js asks for selectors the fake cannot read (`button[disabled].primary`): none of them is in this room
  doc.querySelector = (s) => { try { return doc.body.querySelector(s); } catch { return null; } };
  globalThis.location = { hash: '#home' };
  globalThis.history = { replaceState() {} };
  const id = `g-${Math.random()}`;
  api.me = async () => ({ account: { handle: 'josh' }, finished: [], game: gameOf(id) });
  api.realism = async () => ({});
  api.catchup = async () => ({});
  const realInterval = globalThis.setInterval;
  let tick = null;
  globalThis.setInterval = (fn) => { tick = fn; return 0; };
  try {
    await import('../js/app.js');
  } finally {
    globalThis.setInterval = realInterval;
  }
  await settle();
  assert.ok(tick, 'the app set its minute poll');
  const now = () => app.querySelector('.realism-screen');
  Object.getPrototypeOf(now()).scrollIntoView ??= function scrollIntoView() {};
  mark(now(), 'US Atlantic Fleet').click();
  const to = fillMove(now());
  const first = now();
  doc.activeElement = doc.body;
  tick();
  await settle();
  await settle();
  assert.notEqual(now(), first, 'the poll drew the room again');
  assert.deepEqual(openSheet(now()), ['piece']);
  assert.equal(picked(now()), to);
  tab(now(), 'Forms').click();
  const item = () => sheets(now())[0].querySelector('.rl-instrument[data-lever="lend_lease_finding"]');
  item().querySelector('[aria-expanded]').click();
  item().querySelector('input[name="share_pct"]').value = '45';
  tick();
  await settle();
  await settle();
  assert.deepEqual(openSheet(now()), ['forms']);
  assert.equal(item().querySelector('input[name="share_pct"]').value, '45');
  setRoomLayout('room');
});

test('a form filed from a sheet is sent once and comes back empty, not refilled from what was kept', async () => {
  const { root, now } = room();
  const sent = [];
  api.realism = async (action, body) => { sent.push([action, body]); return { reply: 'Filed.' }; };
  tab(root, 'Forms').click();
  const item = () => sheets(root)[0].querySelector('.rl-instrument[data-lever="lend_lease_finding"]');
  item().querySelector('[aria-expanded]').click();
  const pick = item().querySelectorAll('select[name="recipient"] option')[1].getAttribute('value');
  item().querySelector('select[name="recipient"]').value = pick;
  item().querySelector('input[name="share_pct"]').value = '30';
  const form = item().querySelector('form');
  form.querySelector = (sel) => (sel.startsWith('#') ? form.querySelectorAll('[id]').find((e) => e.id === sel.slice(1)) ?? null : Element.prototype.querySelector.call(form, sel));
  fire(form, 'submit');
  await settle();
  await settle();
  assert.notEqual(now(), root, 'the room was read again after the call');
  buttons(now().querySelector('.rl-mapfirst'), 'Diplomatic')[0].click();
  assert.deepEqual(sent.filter(([a]) => a === 'lever'), [['lever', { lever: 'lend_lease_finding', params: { recipient: pick, share_pct: 30 } }]]);
  assert.deepEqual(openSheet(now()), ['forms']);
  const fresh = sheets(now())[0].querySelector('.rl-instrument[data-lever="lend_lease_finding"]');
  assert.equal(fresh.querySelector('input[name="share_pct"]').value, '');
  assert.equal(fresh.querySelector('select[name="recipient"]').value, '');
});

// rule 6: choosing a piece opens its sheet; opening the Court clears the pick

test('choosing a force on the map opens its sheet, named for it', () => {
  const { root } = room();
  mark(root, 'Home Fleet').click();
  assert.deepEqual(openSheet(root), ['piece']);
  assert.equal(words(sheets(root)[0].querySelector('.rl-over-title')), 'Home Fleet');
});

test('opening the Court clears the pick', () => {
  const { root, id } = room();
  mark(root, 'Home Fleet').click();
  tab(root, 'Court').click();
  assert.equal(uiFor(id).piece, null);
  assert.equal(root.querySelector('.rl-mapfirst .rl-mk[aria-pressed="true"]'), null, 'no mark is marked picked');
});

test('closing a force\'s sheet drops the pick and puts focus back on its mark', () => {
  const { root, id } = room();
  mark(root, 'Home Fleet').click();
  key(sheets(root)[0], 'Escape');
  assert.equal(uiFor(id).piece, null);
  assert.equal(document.activeElement, mark(root, 'Home Fleet'));
});

// rule 7: on a phone, "Write them an order" closes the card before the form opens

/** The Court in today's room with a person picked, on a phone or not. */
function courtCard(phone) {
  const before = globalThis.matchMedia;
  globalThis.matchMedia = (q) => ({ matches: phone && q.includes('max-width'), media: q });
  const { root, id } = room('room');
  buttons(root.querySelector('.rl-boardswitch'), 'Court')[0].click();
  const sq = root.querySelectorAll('.rl-board-main .rl-court-sq, .rl-board-main .rl-court-chip')
    .find((el) => { el.click(); return root.querySelector('.rl-piece.rl-sheet') && buttons(root, 'Write them an order').length; });
  assert.ok(sq, 'a person who can be written to');
  return { root, id, restore: () => { globalThis.matchMedia = before; } };
}

test('on a phone, Write them an order closes the card and the order form has focus', () => {
  const { root, id, restore } = courtCard(true);
  try {
    buttons(root, 'Write them an order')[0].click();
    assert.equal(uiFor(id).piece, null, 'the pick is dropped');
    assert.equal(root.querySelector('.rl-piece.rl-sheet'), null, 'no card sheet over the form');
    assert.equal(document.activeElement, root.querySelector('.rl-board-side .rl-write textarea'));
  } finally {
    restore();
  }
});

test('on a wide screen Write them an order keeps the card beside the form', () => {
  const { root, restore } = courtCard(false);
  try {
    buttons(root, 'Write them an order')[0].click();
    assert.ok(root.querySelector('.rl-piece.rl-sheet'), 'the card stays');
  } finally {
    restore();
  }
});

test('in the map-first room, Write them an order on the Court sheet opens the Forms sheet at the order', () => {
  const { root } = room();
  tab(root, 'Court').click();
  const sq = sheets(root)[0].querySelectorAll('.rl-court-sq, .rl-court-chip')
    .find((el) => { el.click(); return buttons(sheets(root)[0], 'Write them an order').length; });
  assert.ok(sq);
  buttons(sheets(root)[0], 'Write them an order')[0].click();
  assert.deepEqual(openSheet(root), ['forms']);
  assert.equal(document.activeElement, sheets(root)[0].querySelector('.rl-write textarea'));
});

test('realism-sheets.js reads every node list through a spread: a real browser\'s NodeList has no find or filter', () => {
  const src = read('js/views/realism-sheets.js');
  assert.doesNotMatch(src, /querySelectorAll\([^)]*\)\s*\.(find|filter|map|some)\(/);
});
