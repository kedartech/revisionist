// The home sheet and the floor (GRC): the nation's band in the top strip opens the home sheet;
// each group with its support as a bar, what last moved it and when, the themes that move it
// and its seats when it is a bloc; the floor: each bloc's seats and its expected vote on the
// seat's open measures, with the count; "Speak to the nation" opens the free-writing form with
// the themes listed and the cap stated; what needs you lists a measure on the seat's floor
// with its count against what is needed. Another nation shows its band only.
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
const { realismRoom } = await import('../js/views/realism-room.js');
const { setRoomLayout } = await import('../js/views/realism-sheets.js');
const { forgetShapes } = await import('../js/views/realism-theatre.js');
const { statusStrip } = await import('../js/views/realism-status.js');
const home = await import('../js/views/realism-home.js');
const needs = await import('../js/views/realism-needs.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');

/** The seat's view on the toy board, with its home block; nothing else waits on it. */
function seat() {
  const rv = structuredClone(fixture);
  rv.map = structuredClone(fixture.territory_map);
  rv.battles = [];
  rv.agenda = { ...rv.agenda, items: [] };
  rv.orders = { orders: rv.orders.orders.map((o) => ({ ...o, decision_needed: false })) };
  rv.documents = structuredClone(rv.listing);
  rv.wake_tick = 1;
  return rv;
}

const gameOf = (id, rv) => ({ id, name: 'Autumn 1941', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'Franklin D. Roosevelt' } } });
const settle = () => new Promise((r) => setTimeout(r, 0));

/** The whole room for a fresh game in `layout`, over `rv`, with the toy map's shapes served and every call recorded. */
async function room(rv = seat(), layout = 'map') {
  const doc = installDom();
  setRoomLayout(layout);
  forgetShapes();
  const calls = [];
  api.realism = async (action, body) => {
    calls.push([action, body]);
    if (action === 'map') return { reply: '', refused: false, file: rv.map.file, map: SHAPES };
    return { reply: '', refused: false };
  };
  api.catchup = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  const id = `g-${Math.random()}`;
  const me = { account: { handle: 'josh' }, game: gameOf(id, rv) };
  const ctx = { me, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {} };
  const root = realismRoom(ctx);
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  await settle();
  await settle();
  return { doc, ctx, root: () => doc.body.firstElementChild ?? root, calls };
}

const strip = (rv, { home: opts } = {}) => home.withHome(statusStrip(rv, {}, { act: () => {} }), rv, opts);
const ownChip = (el) => el.querySelector('button.rl-home-own');
const groupItem = (sheet, key) => sheet.querySelectorAll('.rl-home-group').find((li) => li.getAttribute('data-group') === key);
const sheetOf = (root) => root.querySelector('.rl-over');

// --- Rule 1: the band in the top strip opens the home sheet ---------------------------------

test('the top strip shows each nation\'s band, the seat\'s own as the button that opens its home sheet', () => {
  let opened = 0;
  const el = strip(seat(), { home: { open: false, onOpen: () => { opened += 1; } } });
  const chips = el.querySelectorAll('.rl-home-chip');
  assert.deepEqual(chips.map(words), ['Norra (yours): steady at home', 'Sudland: no reading']);
  const own = ownChip(el);
  assert.ok(own, 'the seat\'s own band is a button');
  assert.equal(own.getAttribute('aria-expanded'), 'false');
  fire(own, 'click');
  assert.equal(opened, 1);
  assert.equal(el.querySelectorAll('.rl-home-chip').filter((c) => c.tagName === 'BUTTON').length, 1, 'another nation\'s band opens nothing');
});

test('a game with no groups at home shows no band in the strip', () => {
  const rv = seat();
  delete rv.home;
  assert.equal(strip(rv, { home: { open: false, onOpen: () => {} } }).querySelectorAll('.rl-home-chip').length, 0);
});

test('the home sheet gives each group its support as a bar, what last moved it and when, the themes that move it, and a bloc\'s seats', () => {
  const sheet = home.homeSheet(seat().home);
  const items = sheet.querySelectorAll('.rl-home-group');
  assert.deepEqual(items.map((li) => li.getAttribute('data-group')), ['smiths', 'greens', 'greys', 'public'], 'in the world\'s order');
  const greens = groupItem(sheet, 'greens');
  const bar = greens.querySelector('meter');
  assert.equal(bar.value, 60);
  assert.equal(bar.getAttribute('min'), '0');
  assert.equal(bar.getAttribute('max'), '100');
  assert.equal(words(greens.querySelector('.rl-home-grouphead')), 'The Greens party');
  assert.equal(words(greens.querySelector('.rl-home-support')), 'Support 60 of 100');
  assert.match(words(greens.querySelector('.rl-home-moved')), /^Last moved up 5 on 2 April 1900, by a battle won$/);
  assert.equal(words(greens.querySelector('.rl-home-themes')), 'Moved by: The Levy Act (up 1)');
  assert.equal(words(greens.querySelector('.rl-home-seats')), '100 seats in the assembly');
  const pub = groupItem(sheet, 'public');
  assert.equal(words(pub.querySelector('.rl-home-moved')), 'Last moved down 2 on 4 April 1900, by a territory lost');
  assert.equal(words(pub.querySelector('.rl-home-themes')), 'Moved by: Bread for All (up 2)');
  assert.equal(pub.querySelector('.rl-home-seats'), null, 'not a bloc: no seats');
  const smiths = groupItem(sheet, 'smiths');
  assert.equal(words(smiths.querySelector('.rl-home-moved')), 'Not moved yet');
  assert.equal(words(smiths.querySelector('.rl-home-themes')), 'Moved by: Bread for All (down 1)');
  assert.equal(words(groupItem(sheet, 'greys').querySelector('.rl-home-themes')), 'No theme moves it');
  assert.match(words(sheet.querySelector('.rl-home-standing')), /Standing at home 43\.5: steady/);
});

test('another nation\'s groups are never drawn: its band only', () => {
  const h = seat().home;
  const sheet = home.homeSheet(h);
  assert.doesNotMatch(words(sheet), /Sudland/, 'the home sheet is the seat\'s own nation only');
  const el = strip(seat(), { home: { open: true, onOpen: () => {}, sheet } });
  const sud = el.querySelectorAll('.rl-home-chip').find((c) => words(c).startsWith('Sudland'));
  assert.equal(sud.tagName, 'SPAN');
  const band = { ...seat(), home: { ...h, standings: h.standings.map((s) => (s.nation.name === 'Sudland' ? { ...s, band: 'shaken' } : s)) } };
  assert.equal(words(strip(band, { home: { open: false, onOpen: () => {} } }).querySelectorAll('.rl-home-chip')[1]), 'Sudland: shaken at home');
});

test('in the map-first room the band opens the home sheet over the map, the minute poll keeps it, and Escape returns focus to the band', async () => {
  const { root, ctx, doc } = await room();
  fire(ownChip(root()), 'click');
  const sheet = sheetOf(root());
  assert.ok(sheet, 'a sheet is open');
  assert.equal(sheet.getAttribute('data-sheet'), 'home');
  assert.equal(words(sheet.querySelector('.rl-over-title')), 'At home');
  assert.equal(doc.activeElement, sheet.querySelector('.rl-over-title'));
  assert.equal(ownChip(root()).getAttribute('aria-expanded'), 'true');
  await ctx.refresh();
  await settle();
  assert.equal(sheetOf(root())?.getAttribute('data-sheet'), 'home', 'the poll keeps it open');
  sheetOf(root()).dispatchEvent({ type: 'keydown', key: 'Escape', target: null, defaultPrevented: false, preventDefault() {}, stopPropagation() {} });
  assert.equal(sheetOf(root()), null);
  assert.equal(doc.activeElement, ownChip(root()));
});

test('in today\'s room the band opens the home sheet under the strip, and a second tap closes it', async () => {
  const { root, ctx } = await room(seat(), 'room');
  assert.equal(root().querySelector('.rl-home-sheet'), null);
  fire(ownChip(root()), 'click');
  assert.ok(root().querySelector('.rl-strip .rl-home-sheet'), 'the sheet under the strip');
  await ctx.refresh();
  await settle();
  assert.ok(root().querySelector('.rl-strip .rl-home-sheet'), 'a redraw keeps it');
  fire(ownChip(root()), 'click');
  assert.equal(root().querySelector('.rl-home-sheet'), null);
});

// --- Rule 2: the floor ----------------------------------------------------------------------

test('the floor gives each bloc\'s seats and its expected vote on each open measure, with the count', () => {
  const floor = home.homeSheet(seat().home).querySelector('.rl-home-floor');
  assert.ok(floor);
  const chamber = floor.querySelector('[data-chamber="assembly"]');
  assert.equal(words(chamber.querySelector('h4')), 'The assembly');
  const rows = chamber.querySelectorAll('tbody tr').map((tr) => tr.querySelectorAll('th, td').map(words));
  assert.deepEqual(rows, [
    ['The Greens', '100', '71 yea, 29 nay'],
    ['The Greys', '100', '20 yea, 80 nay'],
  ]);
  assert.deepEqual(chamber.querySelectorAll('thead th').map(words), ['Bloc', 'Seats', 'Levy act']);
  assert.deepEqual(chamber.querySelectorAll('.rl-home-count').map(words), ['Levy act: 91 yea, 109 nay. 101 needed to pass.']);
});

test('a chamber with no measure of the seat\'s says so, with each bloc\'s seats', () => {
  const h = seat().home;
  h.chambers[0].measures = [];
  const chamber = home.homeSheet(h).querySelector('[data-chamber="assembly"]');
  assert.deepEqual(chamber.querySelectorAll('tbody tr').map((tr) => tr.querySelectorAll('th, td').map(words)), [['The Greens', '100'], ['The Greys', '100']]);
  assert.equal(words(chamber.querySelector('.rl-home-nomeasure')), 'No measure of yours is before the assembly.');
});

test('a nation with no chamber has no floor', () => {
  const h = seat().home;
  h.chambers = [];
  assert.equal(home.homeSheet(h).querySelector('.rl-home-floor'), null);
});

test('the votes needed are a majority of those voting', () => {
  assert.equal(home.needed({ yeas: 91, nays: 109 }), 101);
  assert.equal(home.needed({ yeas: 50, nays: 49 }), 50);
  assert.equal(home.needed({ yeas: 0, nays: 0 }), 1);
});

// --- Rule 3: Speak to the nation ------------------------------------------------------------

test('the home sheet\'s "Speak to the nation" calls its handler', () => {
  let spoke = 0;
  const sheet = home.homeSheet(seat().home, { onSpeak: () => { spoke += 1; } });
  const [btn] = buttons(sheet, 'Speak to the nation');
  assert.ok(btn);
  fire(btn, 'click');
  assert.equal(spoke, 1);
});

test('the speech note lists each theme with the groups it moves, and states the cap', () => {
  const note = home.speakNote(seat().home);
  assert.deepEqual(note.querySelectorAll('.rl-home-theme').map(words), [
    'Bread for All: The Norra Public up 2, The Smiths\' Guild down 1',
    'The Levy Act: The Greens up 1',
  ]);
  assert.match(words(note), /at most 3 points a day/);
  assert.match(words(note), /at most 6 in any seven days/);
});

test('in the map-first room "Speak to the nation" opens the Forms sheet\'s free-writing form under the themes and the cap, with focus in its words', async () => {
  const { root, doc } = await room();
  fire(ownChip(root()), 'click');
  fire(buttons(sheetOf(root()), 'Speak to the nation')[0], 'click');
  const sheet = sheetOf(root());
  assert.equal(sheet.getAttribute('data-sheet'), 'forms');
  const note = sheet.querySelector('.rl-write .rl-home-speak');
  assert.ok(note, 'the themes and the cap above the form');
  assert.ok(sheet.querySelector('.rl-write form.rl-directive'));
  assert.equal(doc.activeElement, sheet.querySelector('.rl-directive textarea'));
});

test('in today\'s room "Speak to the nation" opens the desk\'s free-writing form under the themes and the cap', async () => {
  const { root, doc } = await room(seat(), 'room');
  fire(ownChip(root()), 'click');
  fire(buttons(root().querySelector('.rl-home-sheet'), 'Speak to the nation')[0], 'click');
  const writes = root().querySelectorAll('.rl-write');
  assert.equal(writes.length, 1, 'one order form, on the Board');
  assert.ok(writes[0].querySelector('.rl-home-speak'));
  assert.equal(doc.activeElement, writes[0].querySelector('.rl-directive textarea'));
});

test('the speech note is not on the form unless the player chose to speak', async () => {
  const { root } = await room(seat(), 'room');
  assert.equal(root().querySelector('.rl-home-speak'), null);
});

// --- Rule 4: what needs you ----------------------------------------------------------------

test('what needs you lists a measure on the seat\'s floor with its count against what is needed', () => {
  const line = needs.needLines(seat()).find((l) => l.kind === 'floor');
  assert.ok(line, 'a floor line');
  assert.equal(line.what, 'Levy act: 91 yea of the 101 needed in the assembly');
  assert.deepEqual(line.action, { word: 'Show the floor', to: 'sheet', sheet: 'home' });
});

test('no floor line without a measure or without groups at home', () => {
  const rv = seat();
  rv.home.chambers[0].measures = [];
  assert.equal(needs.needLines(rv).filter((l) => l.kind === 'floor').length, 0);
  const off = seat();
  delete off.home;
  assert.equal(needs.needLines(off).filter((l) => l.kind === 'floor').length, 0);
});

test('the floor line\'s action opens the home sheet, and closing it goes back to the line', async () => {
  const { root, doc } = await room();
  const line = root().querySelectorAll('.rl-need').find((l) => l.getAttribute('data-kind') === 'floor');
  assert.ok(line);
  fire(line.querySelector('.rl-need-act'), 'click');
  assert.equal(sheetOf(root()).getAttribute('data-sheet'), 'home');
  sheetOf(root()).dispatchEvent({ type: 'keydown', key: 'Escape', target: null, defaultPrevented: false, preventDefault() {}, stopPropagation() {} });
  const back = root().querySelectorAll('.rl-need').find((l) => l.getAttribute('data-kind') === 'floor');
  assert.equal(doc.activeElement, back.querySelector('.rl-need-act'));
});

// --- Styles ---------------------------------------------------------------------------------

test('the home sheet\'s styles are linked and keep a 44px tap target and nothing wider than a phone', () => {
  assert.match(read('index.html'), /<link rel="stylesheet" href="\/css\/c-home\.css">/);
  const css = read('css/c-home.css').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.match(css, /\.rl-home-chip\s*{[^}]*min-height:\s*44px/);
  assert.match(css, /\.rl-home-sheet\s*{[^}]*max-width:\s*100%/);
  assert.match(css, /\.rl-home-table-wrap\s*{[^}]*overflow-x:\s*auto/);
});
