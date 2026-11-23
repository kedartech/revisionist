// The nations as a bar chart, with a card each (NBR), one test or more per rule, on 21 nations
// built in the test and on two: 1. World's Nations part draws one horizontal bar per nation in the
// server's order, the flag, the bar and the figure at its end, a bar's length its figure against
// the largest shown; 2. the seat's own nation is marked and every bar carries its relation by a
// mark that is not colour alone; 3. the name is in each row's accessible name always, and drawn
// beside the flag (css/c-nations.css hides it under 1024 px, where the flag labels the row); 4.
// with more than ten nations ten are shown, the seat's own among them, and "All nations" opens the
// rest in place; 5. a row opens that nation's card (flag, name, relation, the figure and what it
// is, the band as a five-step meter only with a reading, the seat's own two ways on), one at a
// time, and Escape closes it with the focus back on its row; 6. with no economy the nations are
// listed with flags and bands and no bars, and with neither block there is no Nations part.
// Keeps: another nation's components are never drawn; the Classic layout keeps its chips.
// Mutants: a bar measured against the seat's own figure; another nation's components drawn on its
// card when the client is handed them; a band drawn with no reading.
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
/** Nation `i` of 21: real 1941 keys so the flags are found; the seat's own is `own`. */
const nation = (i, own) => ({ key: `ID${i}`, name: `Nation ${i}`, relation: i === own ? 'own' : RELATIONS[i % 3] });

/**
 * The seat's view with 21 nations, largest first, the seat's own the `own`th; every other nation
 * has a band but the 2nd, which has no reading. `change` edits it.
 */
function seat({ own = 0, change = () => {} } = {}) {
  const rv = structuredClone(fixture);
  rv.map = structuredClone(fixture.territory_map);
  rv.documents = structuredClone(fixture.listing);
  rv.wake_tick = 1;
  rv.style = 'free';
  rv.world_key = 'autumn-1941';
  rv.nation_keys = Object.fromEntries(Array.from({ length: NATIONS }, (_, i) => [`ID${i}`, KEYS[i]]));
  const own0 = { ...rv.economy.own, nation: nation(own, own) };
  rv.economy = { ...rv.economy, own: own0, figures: Array.from({ length: NATIONS }, (_, i) => ({ nation: nation(i, own), figure: 200 - 9 * i })) };
  rv.home = { ...rv.home, standings: Array.from({ length: NATIONS }, (_, i) => ({ nation: nation(i, own), band: i === 2 ? null : 'firm' })) };
  change(rv);
  return rv;
}

/** The fixture's two nations, Norra (the seat's) and Sudland, as the toy world sends them. */
const two = (change = () => {}) => {
  const rv = structuredClone(fixture);
  rv.map = structuredClone(fixture.territory_map);
  rv.documents = structuredClone(fixture.listing);
  rv.wake_tick = 1;
  rv.style = 'free';
  change(rv);
  return rv;
};

/** The whole room for `rv` in `layout`. */
async function room(rv, layout = 'map') {
  const doc = installDom();
  setRoomLayout(layout);
  forgetShapes();
  api.realism = async () => ({});
  api.catchup = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  const game = { id: `h12-${Math.random()}`, name: 'Autumn 1941', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'Franklin D. Roosevelt' } } };
  const ctx = { me: { account: { handle: 'josh' }, game }, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {}, signOut: () => {} };
  const root = realismRoom(ctx);
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  await settle();
  return { root, doc, now: () => doc.body.firstElementChild };
}

/** World opened at its Nations part; answers the open sheet. */
function nationsPart(r) {
  r.now().querySelectorAll('.rl-sheettabs button').find((b) => b.getAttribute('data-group') === 'world').click();
  const sheet = r.now().querySelector('.rl-over');
  assert.equal(sheet.getAttribute('data-sheet'), 'nations');
  return sheet;
}

/** A panel drawn alone, as the room draws it, with a fresh state. */
function panel(rv, opts = {}) {
  installDom();
  setFlagIndex(FLAGS);
  return nb.nationsPanel(rv, { state: {}, ...opts });
}

const rows = (el) => el.querySelectorAll('button.rl-nb-row');
const row = (el, key) => rows(el).find((b) => b.getAttribute('data-nation') === key);
const share = (r) => Number(r.querySelector('rect.rl-nb-fill').getAttribute('width'));
const card = (el) => el.querySelector('.rl-nb-card');
const key = (el, k) => {
  const ev = { type: 'keydown', key: k, target: el, defaultPrevented: false, stopped: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; } };
  el.dispatchEvent(ev);
  return ev;
};

// rule 1: one bar per nation, in the server's order, against the largest

test('rule 1: World\'s Nations part draws the chart in place of the chips', async () => {
  const r = await room(seat());
  const sheet = nationsPart(r);
  assert.ok(sheet.querySelector('.rl-nb'), 'the chart');
  assert.equal(sheet.querySelectorAll('.rl-eco-chip').length, 0, 'no chip in the map-first room');
  assert.equal(sheet.querySelectorAll('.rl-home-chip').length, 0, 'no band chip in the map-first room');
});

test('rule 1: one row per nation shown, in the server\'s order, each a flag, a bar and the figure at its end', () => {
  const rv = seat();
  rv.economy.figures.reverse(); // whatever order the server sent is the order drawn
  const el = panel(rv, { state: { all: true } });
  const got = rows(el);
  assert.equal(got.length, NATIONS);
  assert.deepEqual(got.map((b) => b.getAttribute('data-nation')), rv.economy.figures.map((f) => f.nation.key));
  for (const b of got) {
    const kids = [...b.children];
    assert.ok(b.querySelector('.flag'), 'a flag');
    assert.ok(b.querySelector('svg.rl-nb-bar'), 'a bar');
    assert.ok(kids.indexOf(b.querySelector('.rl-nb-num')) > kids.indexOf(b.querySelector('svg.rl-nb-bar')), 'the figure after the bar');
  }
  assert.equal(words(row(el, 'ID3').querySelector('.rl-nb-num')), '173');
});

test('rule 1: a bar\'s length is its figure against the largest figure shown, not the seat\'s own', () => {
  const el = panel(seat({ own: 4 }), { state: { all: true } });
  assert.equal(share(row(el, 'ID0')), 100, 'the largest fills its track');
  assert.equal(share(row(el, 'ID4')), 82, 'the seat\'s own (164) against the largest (200)');
  assert.equal(share(row(el, 'ID10')), 55);
  assert.ok(share(row(el, 'ID0')) <= 100);
});

test('rule 1: the flag is found by the world\'s key and the nation\'s key in that world', () => {
  const el = panel(seat());
  const img = row(el, 'ID1').querySelector('.flag img');
  assert.equal(img.getAttribute('src'), `/assets/flags/${FLAGS['autumn-1941'][KEYS[1]]}`);
  const none = panel(seat({ change: (rv) => { rv.world_key = 'invented'; } }));
  assert.ok(row(none, 'ID1').querySelector('.flag-plain'), 'no file: the plain block');
});

test('rule 1: a figure of nought or below draws an empty bar, and no bar runs past its track', () => {
  const el = panel(seat({ change: (rv) => { rv.economy.figures.at(-1).figure = -5; } }), { state: { all: true } });
  assert.equal(share(row(el, 'ID20')), 0);
  for (const b of rows(el)) assert.ok(share(b) >= 0 && share(b) <= 100);
});

// rule 2: the seat's own marked, and each relation by a mark

test('rule 2: the seat\'s own row is marked, in words and not by colour', () => {
  const el = panel(seat({ own: 4 }));
  const own = rows(el).filter((b) => b.classList.contains('rl-nb-own'));
  assert.deepEqual(own.map((b) => b.getAttribute('data-nation')), ['ID4']);
  assert.ok(words(own[0]).includes('yours'));
});

test('rule 2: each bar carries its relation by a mark of its own shape', () => {
  const el = panel(seat(), { state: { all: true } });
  const shapes = new Map();
  for (const b of rows(el)) {
    const rel = b.getAttribute('data-relation');
    const mark = b.querySelector('svg.rl-nb-rel');
    assert.ok(mark, `a mark on ${b.getAttribute('data-nation')}`);
    assert.equal(mark.getAttribute('data-relation'), rel);
    const shape = mark.children.map((c) => `${c.tagName}:${c.getAttribute('d') ?? ''}${c.getAttribute('r') ?? ''}`).join('|');
    if (shapes.has(rel)) assert.equal(shapes.get(rel), shape);
    shapes.set(rel, shape);
  }
  assert.deepEqual([...shapes.keys()].sort(), ['ally', 'enemy', 'neutral', 'own']);
  assert.equal(new Set(shapes.values()).size, 4, 'four relations, four shapes');
  const label = row(el, 'ID1').getAttribute('aria-label');
  assert.ok(label.includes('ally'), label);
});

test('rule 2: the marks and bars are coloured from the theme\'s tokens only', () => {
  const css = read('css/c-nations.css');
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(/);
  assert.match(css, /\.rl-nb-row\[data-relation="enemy"\][^{]*\{[^}]*var\(--danger\)/);
});

// rule 3: the name always in the accessible name; beside the flag at 1440, the flag alone under 1024

test('rule 3: each row\'s accessible name holds the nation\'s name, its relation and its figure', () => {
  const el = panel(seat(), { state: { all: true } });
  for (const [i, b] of rows(el).entries()) {
    const label = b.getAttribute('aria-label');
    assert.ok(label.startsWith(`Nation ${i}`), label);
    assert.ok(label.includes(String(200 - 9 * i)), label);
    assert.equal(b.querySelector('.flag').getAttribute('aria-hidden'), 'true', 'the flag beside the name is decoration');
    assert.equal(words(b.querySelector('.rl-nb-name')).replace(' · yours', ''), `Nation ${i}`);
  }
});

test('rule 3: the name beside the flag is drawn from 1024 px and hidden under it', () => {
  const css = read('css/c-nations.css');
  assert.match(css, /@media \(max-width: 1023px\)\s*\{[^}]*\.rl-nb-name\s*\{[^}]*display: none/);
});

// rule 4: ten shown, the seat's own among them, "All nations" opens the rest

test('rule 4: with 21 nations ten are shown and "All 21 nations" opens the rest in place', () => {
  const el = panel(seat());
  assert.equal(rows(el).length, 10);
  const all = el.querySelector('button.rl-nb-all');
  assert.equal(words(all), 'All 21 nations');
  assert.equal(all.getAttribute('aria-expanded'), 'false');
  all.click();
  assert.equal(rows(el).length, NATIONS);
  assert.equal(el.querySelector('button.rl-nb-all').getAttribute('aria-expanded'), 'true');
  el.querySelector('button.rl-nb-all').click();
  assert.equal(rows(el).length, 10);
});

test('rule 4: the seat\'s own is among the ten when it is not in the first ten', () => {
  const el = panel(seat({ own: 15 }));
  const keys = rows(el).map((b) => b.getAttribute('data-nation'));
  assert.equal(keys.length, 10);
  assert.ok(keys.includes('ID15'));
  assert.deepEqual(keys, [...Array.from({ length: 9 }, (_, i) => `ID${i}`), 'ID15'], 'the first nine, then the seat\'s own in its place');
  assert.equal(share(row(el, 'ID15')), 33, 'still against the largest');
});

test('rule 4: two nations show both and no "All nations"', async () => {
  const r = await room(two());
  const sheet = nationsPart(r);
  assert.equal(rows(sheet).length, 2);
  assert.equal(sheet.querySelector('button.rl-nb-all'), null);
});

test('rule 4: "All nations" stays open across a redraw of the room', async () => {
  const r = await room(seat());
  nationsPart(r).querySelector('button.rl-nb-all').click();
  assert.equal(rows(r.now().querySelector('.rl-over')).length, NATIONS);
  await r.now().querySelector('.rl-over').querySelector('.rl-parts button[data-sheet="nations"]').click();
  assert.equal(rows(r.now().querySelector('.rl-over')).length, NATIONS);
});

// rule 5: a row opens the nation's card

test('rule 5: another nation\'s card: flag, name, relation, its figure read from the map, its band as a meter', () => {
  const el = panel(seat(), { state: {} });
  row(el, 'ID3').click();
  const c = card(el);
  assert.ok(c, 'the card');
  assert.equal(c.getAttribute('data-nation'), 'ID3');
  assert.equal(c.querySelector('.flag img').getAttribute('src'), `/assets/flags/${FLAGS['autumn-1941'][KEYS[3]]}`);
  assert.equal(words(c.querySelector('h3')), 'Nation 3');
  assert.ok(words(c.querySelector('.rl-nb-relation')).includes('Enemy'));
  assert.ok(c.querySelector('.rl-nb-relation svg.rl-nb-rel'), 'the relation\'s mark');
  assert.ok(words(c).includes('173'), 'its figure');
  assert.ok(words(c).includes('Read from the map'), 'what the figure is');
  const meter = c.querySelector('.rl-nb-meter');
  assert.ok(meter, 'the band as a meter');
  assert.equal(meter.querySelectorAll('.rl-nb-step').length, 5);
  assert.equal(meter.querySelectorAll('.rl-nb-step.on').length, 4, 'firm is the fourth of five');
  assert.ok(words(c).includes('firm at home'));
  assert.equal(rows(el).length, 0, 'the card takes the chart\'s place: one at a time');
});

test('rule 5: a nation with no reading at home has no meter on its card or its row', () => {
  const el = panel(seat(), { state: {} });
  assert.ok(!row(el, 'ID2').getAttribute('aria-label').includes('at home'));
  assert.ok(row(el, 'ID1').getAttribute('aria-label').includes('firm at home'));
  row(el, 'ID2').click();
  assert.equal(card(el).querySelector('.rl-nb-meter'), null);
  assert.ok(!words(card(el)).includes(' at home'), 'no band words');
});

test('rule 5: another nation\'s components are never drawn on its card, even when the client is handed them', () => {
  const rv = seat();
  const other = rv.economy.figures[1];
  Object.assign(other, { income: rv.economy.own.income, pools: rv.economy.own.pools, territories: rv.economy.own.territories });
  rv.economy.own = { ...rv.economy.own, nation: other.nation }; // even a block that names another nation
  const el = panel(rv, { state: {} });
  row(el, 'ID1').click();
  const c = card(el);
  assert.equal(c.querySelector('.rl-eco-income'), null);
  assert.equal(c.querySelectorAll('.rl-eco-sheet').filter((x) => !x.classList.contains('rl-eco-other')).length, 0);
  assert.equal(c.querySelectorAll('button').filter((b) => words(b).includes('war economy')).length, 0);
  for (const r of rv.economy.own.income) assert.ok(!words(c).includes(r.name), r.name);
});

test('rule 5: the seat\'s own card has its two ways on, to its war economy and its home sheet', () => {
  let home = 0;
  const el = panel(seat(), { state: {}, onHome: () => { home += 1; } });
  row(el, 'ID0').click();
  const c = card(el);
  assert.ok(words(c.querySelector('.rl-nb-relation')).includes('Yours'));
  assert.ok(!words(c).includes('Read from the map'));
  assert.ok(words(c).includes('counted for 2 April 1900'), 'the day in words');
  const eco = c.querySelectorAll('button').find((b) => words(b) === 'Your war economy');
  const atHome = c.querySelectorAll('button').find((b) => words(b) === 'At home');
  assert.ok(eco && atHome);
  assert.equal(eco.getAttribute('aria-expanded'), 'false');
  eco.click();
  const sheet = card(el).querySelector('.rl-eco-sheet');
  assert.ok(sheet && sheet.querySelector('.rl-eco-income'), 'the seat\'s own components');
  atHome.click();
  assert.equal(home, 1);
});

test('rule 5: in the room the own card\'s At home opens World at Home', async () => {
  const r = await room(seat());
  row(nationsPart(r), 'ID0').click();
  r.now().querySelector('.rl-nb-card').querySelectorAll('button').find((b) => words(b) === 'At home').click();
  assert.equal(r.now().querySelector('.rl-over').getAttribute('data-sheet'), 'home');
});

test('rule 5: Escape closes the card, keeps the sheet open and puts the focus back on its row', async () => {
  const r = await room(seat());
  row(nationsPart(r), 'ID5').click();
  const c = r.now().querySelector('.rl-nb-card');
  assert.equal(r.doc.activeElement, c.querySelector('.rl-nb-card-title'), 'the focus goes to the card');
  const ev = key(c, 'Escape');
  assert.ok(ev.stopped && ev.defaultPrevented, 'the sheet does not close on the same key');
  const sheet = r.now().querySelector('.rl-over');
  assert.equal(sheet.getAttribute('data-sheet'), 'nations');
  assert.equal(sheet.querySelector('.rl-nb-card'), null);
  assert.equal(r.doc.activeElement, row(sheet, 'ID5'));
});

test('rule 5: the card\'s Nations button goes back to the chart with the focus on its row', () => {
  const el = panel(seat(), { state: { all: true } });
  row(el, 'ID17').click();
  card(el).querySelectorAll('button').find((b) => words(b).includes('Nations')).click();
  assert.equal(card(el), null);
  assert.equal(globalThis.document.activeElement, row(el, 'ID17'));
});

test('rule 5: a card on the two-nation game, and Make an offer on another nation\'s', () => {
  let offered = null;
  const el = panel(two((rv) => { rv.agreements = rv.agreements ?? {}; }), { state: {}, onOffer: (n) => { offered = n.key; } });
  row(el, 'TZHP5CPZR27M6255484EX48TQ6').click();
  assert.ok(words(card(el)).includes('Sudland'));
  card(el).querySelectorAll('button').find((b) => words(b) === 'Make an offer').click();
  assert.equal(offered, 'TZHP5CPZR27M6255484EX48TQ6');
});

// rule 6: no economy, the list; neither block, no control

test('rule 6: with no economy the nations are listed with flags and bands and no bars', async () => {
  const r = await room(seat({ change: (rv) => { rv.economy = null; } }));
  const sheet = nationsPart(r);
  const got = rows(sheet);
  assert.equal(got.length, 10);
  assert.equal(sheet.querySelectorAll('svg.rl-nb-bar').length, 0, 'no bars');
  assert.equal(sheet.querySelectorAll('.rl-nb-num').length, 0, 'no figures');
  assert.ok(got.every((b) => b.querySelector('.flag')));
  assert.ok(words(row(sheet, 'ID1')).includes('firm'));
  row(sheet, 'ID1').click();
  const c = r.now().querySelector('.rl-nb-card');
  assert.ok(c.querySelector('.rl-nb-meter'));
  assert.ok(!words(c).includes('War economy'));
});

test('rule 6: with neither block World has no Nations part', async () => {
  const r = await room(seat({ change: (rv) => { rv.economy = null; rv.home = null; } }));
  r.now().querySelectorAll('.rl-sheettabs button').find((b) => b.getAttribute('data-group') === 'world').click();
  const parts = r.now().querySelectorAll('.rl-over .rl-parts button').map((b) => b.getAttribute('data-sheet'));
  assert.ok(!parts.includes('nations'), parts.join());
  assert.equal(nb.nationsPanel(seat({ change: (rv) => { rv.economy = null; rv.home = null; } }), { state: {} }), null);
});

// keeps

test('keeps: the Classic layout keeps its chips', async () => {
  const r = await room(seat(), 'room');
  assert.equal(r.now().querySelectorAll('.rl-eco-chip').length, NATIONS);
  assert.equal(r.now().querySelectorAll('.rl-nb').length, 0);
});

test('keeps: the stylesheet is linked from the page and its rows are 44 px targets', () => {
  assert.match(read('index.html'), /<link rel="stylesheet" href="\/css\/c-nations\.css">/);
  assert.match(read('css/c-nations.css'), /\.rl-nb-row\s*\{[^}]*min-height: 44px/);
});

test('keeps: nothing in the module touches the page on import', () => {
  const src = read('js/views/realism-nations.js');
  assert.doesNotMatch(src, /^(?!\s*\/\/)\s*document\./m);
  assert.doesNotMatch(src, /\.style\./);
});
