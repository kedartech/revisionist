// Where each nation stands: the flag grid (STG), one test or more per rule, on 21 nations built in
// the test and on the two of the toy world: 1. World's Standing part draws a tile for each nation:
// its flag, its name and its relation to the seat by a mark and a word; 2. a tile lists the
// nations it is at war with as small flags (the public list, both ways) and its public pacts by
// name; 3. a tile opens that nation's card in the Nations part; 4. a nation with no flag file takes
// the plain block.
// Keeps: only what is public or the seat's own: a pact the view does not mark public is not drawn,
// even when the seat is a party to it; the relation is the one the view sends.
// Mutants: a war drawn on one of its two nations only; a pact drawn with no public mark.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';

const FLAGS = JSON.parse(readFileSync(new URL('../assets/flags/index.json', import.meta.url), 'utf8'));
globalThis.fetch = async () => ({ ok: true, json: async () => FLAGS });
Object.defineProperty(Object.getPrototypeOf(installDom().createElement('div')), 'hidden', {
  configurable: true,
  get() { return this.hasAttribute('hidden'); },
  set(on) { this.toggleAttribute('hidden', Boolean(on)); },
});
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { realismRoom } = await import('../js/views/realism-room.js');
const { forgetShapes } = await import('../js/views/realism-theatre.js');
const { setRoomLayout } = await import('../js/views/realism-sheets.js');
const { setFlagIndex } = await import('../js/flags.js');
const nb = await import('../js/views/realism-nations.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');
const settle = () => new Promise((r) => setTimeout(r, 0));

const NATIONS = 21;
const KEYS = Object.keys(FLAGS['autumn-1941']);
const RELATIONS = ['enemy', 'ally', 'neutral'];
const nation = (i, own) => ({ key: `ID${i}`, name: `Nation ${i}`, relation: i === own ? 'own' : RELATIONS[i % 3] });
const side = (i) => ({ key: `ID${i}`, name: `Nation ${i}` });
const pact = (id, parties, published, wording = '') => ({ id, parties: parties.map((i) => `Nation ${i}`), wording, made: '1941-03-01', published, party: false, clauses: [] });

/** The seat's view with 21 nations, the 0th its own; wars and pacts as given. */
function seat({ wars = [], pacts = [], change = () => {} } = {}) {
  const rv = structuredClone(fixture);
  rv.map = structuredClone(fixture.territory_map);
  rv.documents = structuredClone(fixture.listing);
  rv.wake_tick = 1;
  rv.style = 'free';
  rv.world_key = 'autumn-1941';
  rv.nation_keys = Object.fromEntries(Array.from({ length: NATIONS }, (_, i) => [`ID${i}`, KEYS[i]]));
  rv.economy = { ...rv.economy, own: { ...rv.economy.own, nation: nation(0, 0) }, figures: Array.from({ length: NATIONS }, (_, i) => ({ nation: nation(i, 0), figure: 200 - 9 * i })) };
  rv.home = { ...rv.home, standings: Array.from({ length: NATIONS }, (_, i) => ({ nation: nation(i, 0), band: 'firm' })) };
  rv.wars = wars.map(([a, b]) => ({ a: side(a), b: side(b), since: '1939-09-01' }));
  rv.agreements = { agreements: pacts, offers: [] };
  change(rv);
  return rv;
}

async function room(rv) {
  const doc = installDom();
  setRoomLayout('map');
  forgetShapes();
  api.realism = async () => ({});
  api.catchup = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  const game = { id: `h19-${Math.random()}`, name: 'Autumn 1941', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'Franklin D. Roosevelt' } } };
  const ctx = { me: { account: { handle: 'josh' }, game }, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {}, signOut: () => {} };
  const root = realismRoom(ctx);
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  await settle();
  return { root, doc, now: () => doc.body.firstElementChild };
}

/** The room's World sheet opened at its Standing part. */
function standingPart(r) {
  r.now().querySelectorAll('.rl-sheettabs button').find((b) => b.getAttribute('data-group') === 'world').click();
  r.now().querySelectorAll('.rl-over .rl-parts button').find((b) => b.getAttribute('data-sheet') === 'standing').click();
  const sheet = r.now().querySelector('.rl-over');
  assert.equal(sheet.getAttribute('data-sheet'), 'standing');
  return sheet;
}

function grid(rv, opts = {}) {
  installDom();
  setFlagIndex(FLAGS);
  return nb.standingGrid(rv, opts);
}

const tiles = (el) => el.querySelectorAll('button.rl-sg-tile');
const tile = (el, k) => tiles(el).find((b) => b.getAttribute('data-nation') === k);
const warFlags = (t) => t.querySelectorAll('.rl-sg-wars .flag');
const pactNames = (t) => t.querySelectorAll('.rl-sg-pact').map((li) => words(li));

// rule 1: a tile for each nation, with its flag, name, and relation by a mark and a word

test('rule 1: World\'s Standing part draws the grid, a tile for each nation, in the server\'s order', async () => {
  const r = await room(seat());
  const sheet = standingPart(r);
  const got = tiles(sheet);
  assert.equal(got.length, NATIONS);
  assert.deepEqual(got.map((b) => b.getAttribute('data-nation')), Array.from({ length: NATIONS }, (_, i) => `ID${i}`));
});

test('rule 1: a tile is the flag, the name, and the relation as a mark and a word', () => {
  const el = grid(seat());
  const t = tile(el, 'ID1');
  assert.ok(t.querySelector('.flag'), 'a flag');
  assert.equal(words(t.querySelector('.rl-sg-name')), 'Nation 1');
  assert.equal(t.querySelector('svg.rl-nb-rel').getAttribute('data-relation'), 'ally');
  assert.equal(words(t.querySelector('.rl-sg-relation')), 'Ally');
  assert.equal(words(tile(el, 'ID0').querySelector('.rl-sg-relation')), 'Yours');
  assert.equal(words(tile(el, 'ID2').querySelector('.rl-sg-relation')), 'Neutral');
  assert.equal(words(tile(el, 'ID3').querySelector('.rl-sg-relation')), 'Enemy');
});

test('rule 1: a relation the view does not send is neutral, and the name is in the tile\'s accessible name', () => {
  const el = grid(seat({ change: (rv) => { rv.economy.figures[5].nation.relation = 'bogus'; } }));
  assert.equal(words(tile(el, 'ID5').querySelector('.rl-sg-relation')), 'Neutral');
  assert.match(tile(el, 'ID5').getAttribute('aria-label'), /^Nation 5, neutral/);
  assert.match(tile(el, 'ID0').getAttribute('aria-label'), /^Nation 0 \(yours\)/);
});

test('rule 1: with no economy the tiles come from the home block; with neither there is no Standing part', async () => {
  const noEconomy = seat({ change: (rv) => { delete rv.economy; } });
  assert.equal(tiles(grid(noEconomy)).length, NATIONS);
  const neither = seat({ change: (rv) => { delete rv.economy; delete rv.home; } });
  assert.equal(nb.standingGrid(neither), null);
  const r = await room(neither);
  r.now().querySelectorAll('.rl-sheettabs button').find((b) => b.getAttribute('data-group') === 'world')?.click();
  const parts = r.now().querySelectorAll('.rl-over .rl-parts button').map((b) => b.getAttribute('data-sheet'));
  assert.ok(!parts.includes('standing'));
});

// rule 2: wars as small flags, public pacts by name

test('rule 2: a war is drawn on both of its nations, as the other\'s flag', () => {
  const el = grid(seat({ wars: [[3, 7]] }));
  assert.equal(warFlags(tile(el, 'ID3')).length, 1);
  assert.equal(warFlags(tile(el, 'ID7')).length, 1, 'the second nation shows it too');
  assert.equal(warFlags(tile(el, 'ID3'))[0].getAttribute('data-nation'), KEYS[7]);
  assert.equal(warFlags(tile(el, 'ID7'))[0].getAttribute('data-nation'), KEYS[3]);
  assert.equal(warFlags(tile(el, 'ID4')).length, 0, 'a nation at war with no one has none');
});

test('rule 2: a war flag is named for the nation it is against', () => {
  const el = grid(seat({ wars: [[3, 7], [3, 9]] }));
  const flagsOf = warFlags(tile(el, 'ID3'));
  assert.equal(flagsOf.length, 2);
  assert.deepEqual(flagsOf.map((f) => f.getAttribute('aria-label')), ['Nation 7', 'Nation 9']);
  assert.match(tile(el, 'ID3').getAttribute('aria-label'), /at war with Nation 7, Nation 9/);
});

test('rule 2: a nation with no war has no war line and says nothing of one', () => {
  const el = grid(seat());
  assert.equal(el.querySelectorAll('.rl-sg-wars').length, 0);
  assert.doesNotMatch(tile(el, 'ID1').getAttribute('aria-label'), /war/);
});

test('rule 2: a public pact is named on the tile of each of its parties', () => {
  const el = grid(seat({ pacts: [pact('a1', [2, 4], '1941-03-02', 'Pact of Steel')] }));
  assert.deepEqual(pactNames(tile(el, 'ID2')), ['Pact of Steel']);
  assert.deepEqual(pactNames(tile(el, 'ID4')), ['Pact of Steel']);
  assert.equal(el.querySelectorAll('.rl-sg-pacts').length, 2, 'no other tile has a pact line');
  assert.match(tile(el, 'ID2').getAttribute('aria-label'), /Pact of Steel/);
});

test('rule 2: a public pact with no wording is named by its parties', () => {
  const el = grid(seat({ pacts: [pact('a1', [2, 4, 6], '1941-03-02')] }));
  assert.deepEqual(pactNames(tile(el, 'ID6')), ['Nation 2, Nation 4 and Nation 6']);
});

test('rule 2: a pact not marked public is not drawn, even when the seat is a party to it', () => {
  const secret = { ...pact('a1', [0, 4], null, 'Secret Protocol'), party: true };
  const el = grid(seat({ pacts: [secret, pact('a2', [2, 4], '1941-03-02', 'Open Pact')] }));
  assert.deepEqual(pactNames(tile(el, 'ID4')), ['Open Pact']);
  assert.equal(el.querySelectorAll('.rl-sg-pacts').length, 2);
  assert.ok(!words(el).includes('Secret Protocol'), 'its name is nowhere in the grid');
  assert.ok(!tile(el, 'ID0').getAttribute('aria-label').includes('Secret'));
});

test('rule 2: no agreements block draws no pact and no error', () => {
  const el = grid(seat({ change: (rv) => { delete rv.agreements; } }));
  assert.equal(el.querySelectorAll('.rl-sg-pacts').length, 0);
});

test('rule 2: a war between nations the grid does not list adds no tile', () => {
  const el = grid(seat({ wars: [[3, 90]] }));
  assert.equal(tiles(el).length, NATIONS);
  assert.equal(warFlags(tile(el, 'ID3')).length, 1);
});

// rule 3: a tile opens that nation's card

test('rule 3: a tile opens that nation\'s card in the Nations part', async () => {
  const r = await room(seat({ wars: [[3, 7]] }));
  const sheet = standingPart(r);
  tile(sheet, 'ID7').click();
  const open = r.now().querySelector('.rl-over');
  assert.equal(open.getAttribute('data-sheet'), 'nations');
  const card = open.querySelector('.rl-nb-card');
  assert.ok(card, 'the card');
  assert.equal(card.getAttribute('data-nation'), 'ID7');
  assert.equal(words(card.querySelector('.rl-nb-card-title')), 'Nation 7');
});

test('rule 3: a tile is a button of 44 px at least', () => {
  const css = read('css/c-nations.css');
  assert.match(css, /\.rl-sg-tile\s*\{[^}]*min-height:\s*44px/);
  assert.equal(grid(seat()).querySelector('button.rl-sg-tile').getAttribute('type'), 'button');
});

// rule 4: a nation with no flag file takes the plain block

test('rule 4: a nation with no flag file takes the plain block, in its relation\'s tone', () => {
  const el = grid(seat({ change: (rv) => { delete rv.nation_keys.ID3; } }));
  const f = tile(el, 'ID3').querySelector('.flag');
  assert.ok(f.classList.contains('flag-plain'));
  assert.ok(f.classList.contains('flag-enemy'));
  assert.ok(tile(el, 'ID1').querySelector('.flag').classList.contains('flag-file'));
});

test('rule 4: a war flag of a nation with no file is a plain block too', () => {
  const el = grid(seat({ wars: [[3, 7]], change: (rv) => { delete rv.nation_keys.ID7; } }));
  assert.ok(warFlags(tile(el, 'ID3'))[0].classList.contains('flag-plain'));
});

// the toy world

test('the two-nation toy game: both tiles, the war on both and no pact line', async () => {
  const rv = structuredClone(fixture);
  rv.map = structuredClone(fixture.territory_map);
  rv.documents = structuredClone(fixture.listing);
  rv.wake_tick = 1;
  rv.style = 'free';
  const el = grid(rv);
  assert.equal(tiles(el).length, 2);
  for (const t of tiles(el)) assert.equal(warFlags(t).length, 1);
});

// keeps

test('keeps: the stylesheet has the grid, from tokens only', () => {
  const css = read('css/c-nations.css');
  assert.match(css, /\.rl-sg-grid/);
  const sg = css.split('\n').filter((l) => l.includes('.rl-sg-')).join('\n');
  assert.doesNotMatch(sg, /#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(/);
});
