// The home sheet and the floor (GRC), one test or more per plan rule: 1. the seat's groups as
// tokens with a five-step bar (the number on tap) and an arrow for the last move with its cause,
// opened from the nation's band in the top strip; 2. each chamber's blocs as tokens with their
// seats, an open measure counted by bloc with the line that carries it (and a line in what needs
// you); 3. after the reading and before signing, the groups the named theme speaks to, as the
// staff's read and not a promise ("Speak to the nation" opens the composer under the themes and
// the cap); 4. after the close, what moved; 5. a held territory's sheet shows its holder's band.
// The fixture's groups are a guild, two parties and a public: not Congress. Mutants: another
// nation's groups drawn (only bands reach the strip and an area's sheet); the read shown as a result.
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
const { setRoomLayout } = await import('../js/views/realism-sheets.js');
const { forgetShapes } = await import('../js/views/realism-theatre.js');
const { statusStrip } = await import('../js/views/realism-status.js');
const { territoryView } = await import('../js/views/realism-territory.js');
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
async function room(rv = seat(), layout = 'map', prep = null) {
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
  prep?.(uiFor(id));
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
/** The World group's tab on the map-first room's bar. */
const worldTab = (root) => root.querySelectorAll('.rl-sheettabs button').find((b) => b.getAttribute('data-group') === 'world');
/** The way to the home sheet in the map-first room: At home on the seat's own card, in World's Nations part. */
const nationsChip = (root) => {
  fire(worldTab(root), 'click');
  const own = document.body.firstElementChild.querySelector('button.rl-nb-row.rl-nb-own');
  fire(own, 'click');
  return document.body.firstElementChild.querySelector('.rl-nb-card button.rl-nb-home');
};

// --- Rule 1: the band in the top strip opens the home sheet ---------------------------------

test('the top strip shows each nation\'s band, the seat\'s own as the button that opens its home sheet', () => {
  let opened = 0;
  const rv = seat();
  rv.home.standings[1].band = 'shaken';
  const el = strip(rv, { home: { open: false, onOpen: () => { opened += 1; } } });
  const chips = el.querySelectorAll('.rl-home-chip');
  assert.deepEqual(chips.map(words), ['Norra (yours): steady at home', 'Sudland: shaken at home']);
  const own = ownChip(el);
  assert.ok(own, 'the seat\'s own band is a button');
  assert.equal(own.getAttribute('aria-expanded'), 'false');
  fire(own, 'click');
  assert.equal(opened, 1);
  assert.equal(el.querySelectorAll('.rl-home-chip').filter((c) => c.tagName === 'BUTTON').length, 1, 'another nation\'s band opens nothing');
});

/** `rv` with standings: the own nation's band `own`, then [name, band] for each other nation. */
function standing(own, others) {
  const rv = seat();
  const [mine] = rv.home.standings;
  rv.home.standings = [
    { nation: mine.nation, band: own },
    ...others.map(([name, band], i) => ({ nation: { key: `N${i}`, name, relation: 'neutral' }, band })),
  ];
  return rv;
}
const chipWords = (rv) => strip(rv, { home: { open: false, onOpen: () => {} } }).querySelectorAll('.rl-home-chip').map(words);

test('the strip leaves out every other nation with no reading', () => {
  const rv = standing('steady', [['Vell', 'firm'], ['Aster', null], ['Kora', 'shaken'], ['Lund', null], ['Mire', null]]);
  assert.deepEqual(chipWords(rv), ['Norra (yours): steady at home', 'Vell: firm at home', 'Kora: shaken at home']);
});

test('the seat\'s own nation keeps its band button with no reading', () => {
  const rv = standing(null, [['Vell', 'firm'], ['Aster', null]]);
  const el = strip(rv, { home: { open: false, onOpen: () => {} } });
  assert.deepEqual(el.querySelectorAll('.rl-home-chip').map(words), ['Norra (yours): no reading', 'Vell: firm at home']);
  assert.ok(ownChip(el), 'the own band is still the button');
});

test('when every other nation has no reading the strip shows the own band only', () => {
  assert.deepEqual(chipWords(standing('steady', [['Vell', null], ['Aster', null]])), ['Norra (yours): steady at home']);
});

test('standings with no chip left add nothing to the strip', () => {
  const rv = standing(null, [['Vell', null], ['Aster', null]]);
  rv.home.standings.shift();
  assert.equal(home.homeStrip(rv, { open: false, onOpen: () => {} }), null);
  assert.equal(strip(rv).querySelectorAll('.rl-home').length, 0);
});

test('a game with no groups at home shows no band in the strip', () => {
  const rv = seat();
  delete rv.home;
  assert.equal(strip(rv, { home: { open: false, onOpen: () => {} } }).querySelectorAll('.rl-home-chip').length, 0);
});

test('the home sheet shows each group as a token: its name, a five-step bar with the number on tap, and an arrow for its last move with the cause', () => {
  const sheet = home.homeSheet(seat().home);
  const items = sheet.querySelectorAll('.rl-home-group');
  assert.deepEqual(items.map((li) => li.getAttribute('data-group')), ['smiths', 'greens', 'greys', 'public'], 'in the world\'s order');
  const greens = groupItem(sheet, 'greens');
  assert.equal(words(greens.querySelector('.rl-home-grouphead')), 'The Greens party');
  const bar = greens.querySelector('button.rl-home-bar');
  assert.equal(bar.querySelectorAll('.rl-home-step').length, 5, 'five steps');
  assert.equal(bar.querySelectorAll('.rl-home-step.on').length, 4, 'support 60 is the fourth step');
  const num = greens.querySelector('.rl-home-num');
  assert.ok(num.hasAttribute('hidden'), 'the number waits for a tap');
  assert.equal(bar.getAttribute('aria-expanded'), 'false');
  fire(bar, 'click');
  assert.ok(!num.hasAttribute('hidden'));
  assert.equal(words(num), '60 of 100');
  assert.equal(bar.getAttribute('aria-expanded'), 'true');
  fire(bar, 'click');
  assert.ok(num.hasAttribute('hidden'), 'a second tap hides it');
  assert.equal(words(greens.querySelector('.rl-home-arrow')), '↑');
  assert.equal(words(greens.querySelector('.rl-home-moved')), '↑ Up 5 on 2 April 1900: a battle won');
  assert.equal(words(greens.querySelector('.rl-home-themes')), 'Moved by: The Levy Act (up 1)');
  assert.equal(words(greens.querySelector('.rl-home-seats')), '100 seats in the assembly');
  const pub = groupItem(sheet, 'public');
  assert.equal(pub.querySelectorAll('.rl-home-step.on').length, 2, 'support 38 is the second step');
  assert.equal(words(pub.querySelector('.rl-home-moved')), '↓ Down 2 on 4 April 1900: a territory lost');
  assert.equal(pub.querySelector('.rl-home-seats'), null, 'not a bloc: no seats');
  const smiths = groupItem(sheet, 'smiths');
  assert.equal(smiths.querySelectorAll('.rl-home-step.on').length, 3);
  assert.equal(words(smiths.querySelector('.rl-home-moved')), 'Not moved yet');
  assert.equal(smiths.querySelector('.rl-home-arrow'), null);
  assert.equal(words(smiths.querySelector('.rl-home-themes')), 'Moved by: Bread for All (down 1)');
  assert.equal(words(groupItem(sheet, 'greys').querySelector('.rl-home-themes')), 'No theme moves it');
  assert.match(words(sheet.querySelector('.rl-home-standing')), /Standing at home 43\.5: steady/);
});

test('the five steps follow the bands\' lower bounds', () => {
  assert.deepEqual([0, 19, 20, 39, 40, 59, 60, 79, 80, 100].map(home.supportStep), [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]);
});

test('the groups are not Congress: the fixture\'s are a guild, two parties and a public, by the world\'s own names', () => {
  const names = home.homeSheet(seat().home).querySelectorAll('.rl-home-group .rl-home-grouphead strong').map(words);
  assert.deepEqual(names, ['The Smiths\' Guild', 'The Greens', 'The Greys', 'The Norra Public']);
});

test('another nation\'s groups are never drawn: its band only', () => {
  const h = seat().home;
  const sheet = home.homeSheet(h);
  assert.doesNotMatch(words(sheet), /Sudland/, 'the home sheet is the seat\'s own nation only');
  const band = { ...seat(), home: { ...h, standings: h.standings.map((s) => (s.nation.name === 'Sudland' ? { ...s, band: 'shaken' } : s)) } };
  const el = strip(band, { home: { open: true, onOpen: () => {}, sheet } });
  const sud = el.querySelectorAll('.rl-home-chip').find((c) => words(c).startsWith('Sudland'));
  assert.equal(sud.tagName, 'SPAN');
  assert.equal(words(sud), 'Sudland: shaken at home');
});

test('in the map-first room At home on the seat\'s own card opens the Home part over the map, the minute poll keeps it, and Escape returns focus to the World tab', async () => {
  const { root, ctx, doc } = await room();
  fire(nationsChip(root()), 'click');
  const sheet = sheetOf(root());
  assert.ok(sheet, 'a sheet is open');
  assert.equal(sheet.getAttribute('data-sheet'), 'home');
  assert.equal(words(sheet.querySelector('.rl-over-title')), 'World');
  assert.equal(doc.activeElement, sheet.querySelector('.rl-over-title'));
  await ctx.refresh();
  await settle();
  assert.equal(sheetOf(root())?.getAttribute('data-sheet'), 'home', 'the poll keeps it open');
  sheetOf(root()).dispatchEvent({ type: 'keydown', key: 'Escape', target: null, defaultPrevented: false, preventDefault() {}, stopPropagation() {} });
  assert.equal(sheetOf(root()), null);
  assert.equal(doc.activeElement, worldTab(root()), 'focus goes back to the World tab');
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

test('each chamber shows its blocs as tokens with their seats, and an open measure its count by bloc with the line that carries it', () => {
  const floor = home.homeSheet(seat().home).querySelector('.rl-home-floor');
  assert.ok(floor);
  const chamber = floor.querySelector('[data-chamber="assembly"]');
  assert.equal(words(chamber.querySelector('h4')), 'The assembly');
  assert.deepEqual(chamber.querySelectorAll('.rl-home-seg').map((r) => r.getAttribute('aria-label')), ['The Greens, 100 seats. Open its card', 'The Greys, 100 seats. Open its card']);
  const measure = chamber.querySelector('.rl-home-measure');
  assert.equal(words(measure.querySelector('h5')), 'Levy act');
  assert.deepEqual(measure.querySelectorAll('.rl-home-vote .rl-home-token').map(words), ['The Greens 71 yea, 29 nay', 'The Greys 20 yea, 80 nay']);
  assert.equal(words(measure.querySelector('.rl-home-line')), '101 yeas carry it. Counted today: 91 yea, 109 nay: short by 10');
});

test('a measure counted to carry says so on its line', () => {
  const h = seat().home;
  const vote = h.chambers[0].measures[0].votes[0];
  Object.assign(vote, { yeas: 120, nays: 80, blocs: [{ group: 'greens', yeas: 90, nays: 10 }, { group: 'greys', yeas: 30, nays: 70 }] });
  assert.equal(words(home.homeSheet(h).querySelector('.rl-home-line')), '101 yeas carry it. Counted today: 120 yea, 80 nay: it carries');
});

test('a chamber with no measure of the seat\'s says so, with each bloc\'s seats', () => {
  const h = seat().home;
  h.chambers[0].measures = [];
  const chamber = home.homeSheet(h).querySelector('[data-chamber="assembly"]');
  assert.equal(words(chamber.querySelector('.rl-home-seatnote')), 'The Greens 100 · The Greys 100');
  assert.equal(chamber.querySelector('.rl-home-measure'), null);
  assert.equal(words(chamber.querySelector('.rl-home-nomeasure')), 'No measure of yours is before the assembly.');
});

test('a nation with no chamber has no floor', () => {
  const h = seat().home;
  h.chambers = [];
  assert.equal(home.homeSheet(h).querySelector('.rl-home-floor'), null);
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
  fire(nationsChip(root()), 'click');
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

// --- Rule 3 (plan): the composer's read of the groups a theme speaks to --------------------

const BREAD = { person: 'Ilse Varg', channel: 'Proclamation', text: 'Speak to the people of bread for all.', parts: ['Make a statement on bread for all'], reason: null };

test('after the reading, the theme the order names shows the groups it speaks to, as the staff\'s read and not a promise', () => {
  const read = home.themeRead(seat().home, BREAD);
  assert.ok(read);
  assert.equal(read.getAttribute('data-key'), 'bread');
  assert.equal(words(read.querySelector('.rl-home-read-head')), 'Your staff\'s read: this speaks to Bread for All, which reaches The Norra Public up 2, The Smiths\' Guild down 1.');
  assert.match(words(read), /A read, not a promise/);
  assert.doesNotMatch(words(read), /\b(moved|has moved|will move)\b/i, 'not worded as a result');
});

test('a theme is named by its key or its name as whole words, the first in the world\'s order', () => {
  const h = seat().home;
  assert.equal(home.namedTheme(h, { text: 'On the levy', parts: [] })?.key, 'levy');
  assert.equal(home.namedTheme(h, { text: 'The Levy Act and bread for all', parts: [] })?.key, 'bread');
  assert.equal(home.namedTheme(h, { text: 'Breadfor all levyact', parts: [] }), null, 'not as whole words');
  assert.equal(home.namedTheme(h, { text: 'Move the escorts', parts: ['Escort the convoys'] }), null);
  assert.equal(home.themeRead(h, { text: 'Move the escorts', parts: [] }), null, 'no theme, no read');
});

test('in the room the read stands under the order card before signing, and is gone once it is signed', async () => {
  const { root, calls } = await room(seat(), 'map', (ui) => { ui.proposal = structuredClone(BREAD); ui.sheet = 'forms'; ui.sheetFrom = { tab: 'forms' }; });
  const write = sheetOf(root()).querySelector('.rl-write');
  const kids = [...write.children];
  const card = kids.findIndex((el) => el.classList.contains('rl-proposal'));
  assert.ok(card >= 0, 'the card to sign');
  assert.ok(kids[card + 1]?.classList.contains('rl-home-read'), 'the read under the card');
  fire(buttons(write, 'Sign and send')[0], 'click');
  await settle();
  await settle();
  assert.ok(calls.some(([a]) => a === 'file'), 'signed');
  assert.equal(root().querySelector('.rl-home-read'), null, 'not shown as a result once signed');
});

test('an order card that names no theme carries no read', async () => {
  const { root } = await room(seat(), 'map', (ui) => { ui.proposal = structuredClone(fixture.proposal); ui.sheet = 'forms'; ui.sheetFrom = { tab: 'forms' }; });
  assert.ok(sheetOf(root()).querySelector('.rl-proposal'));
  assert.equal(root().querySelector('.rl-home-read'), null);
});

// --- Rule 4 (plan): after the close the sheet shows what moved ----------------------------

test('after the close the sheet shows the groups the close moved, by the days it walked', () => {
  const h = seat().home;
  h.day = '1900-04-04';
  const moved = (days) => home.homeSheet(h, { days }).querySelectorAll('.rl-home-close li').map((li) => li.getAttribute('data-group'));
  assert.deepEqual(moved(2), ['public'], 'the close walked the 3rd and the 4th');
  assert.deepEqual(moved(3), ['greens', 'public']);
  assert.equal(words(home.homeSheet(h, { days: 2 }).querySelector('.rl-home-close li')), 'The Norra Public ↓ Down 2 on 4 April 1900: a territory lost');
  h.day = '1900-04-20';
  assert.equal(words(home.homeSheet(h, { days: 6 }).querySelector('.rl-home-close p')), 'Nothing moved at the last close.');
  assert.equal(home.homeSheet(h).querySelector('.rl-home-close'), null, 'no close walked: no section');
});

test('the room gives the home sheet the days the last close walked', async () => {
  const rv = seat();
  rv.home.day = '1900-04-04';
  rv.record.wake.days_passed = 2;
  const { root } = await room(rv);
  fire(nationsChip(root()), 'click');
  assert.deepEqual(sheetOf(root()).querySelectorAll('.rl-home-close li').map((li) => li.getAttribute('data-group')), ['public']);
});

// --- Rule 5 (plan): a capital's sheet shows that nation's public standing band -------------

test('a held territory\'s sheet shows its holder\'s band at home, and nothing of its groups', () => {
  const rv = seat();
  const held = new Map(rv.economy_areas.map((a) => [a.key, a.holder]));
  const map = { ...rv.map, areas: rv.map.areas.map((a) => ({ ...a, holder: held.get(a.key) ?? null })) };
  const standings = structuredClone(rv.home.standings);
  const sheetFor = (area) => territoryView(map, SHAPES, { area, standings }).querySelector('section.rl-area-sheet');
  const own = sheetFor('norra_plain');
  const rows = (s) => s.querySelectorAll('dt').map((dt, i) => [words(dt), words(s.querySelectorAll('dd')[i])]);
  assert.deepEqual(rows(own).at(-1), ['Norra at home', 'Steady']);
  assert.deepEqual(rows(sheetFor('sudland_coast')).at(-1), ['Sudland at home', 'No reading']);
  standings[1].band = 'shaken';
  const theirs = sheetFor('sudland_coast');
  assert.deepEqual(rows(theirs).at(-1), ['Sudland at home', 'Shaken']);
  assert.doesNotMatch(words(theirs), /Greens|Greys|Guild|Public/, 'a band only');
  assert.ok(!rows(territoryView(map, SHAPES, { area: 'norra_plain' }).querySelector('section.rl-area-sheet')).some(([k]) => k.endsWith('at home')), 'no standings, no line');
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
  assert.match(css, /\.rl-home-tokens\s*{[^}]*flex-wrap:\s*wrap/);
});
