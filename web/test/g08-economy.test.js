// The war economy on screen (ECO): the strip's figure per nation; the seat's own sheet under
// the world's resource names; another nation's figure read from the map; the economy layer's
// pips, with the numbers on a tap. Fixture resources are grain, iron, levies, pitch, rails,
// glory: none is called industry or oil.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { fire, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { statusStrip } = await import('../js/views/realism-status.js');
const eco = await import('../js/views/realism-economy.js');
const { territoryDrawing, territoryView } = await import('../js/views/realism-territory.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');
const DESK = { width: 960, height: 740 };

const rv = () => {
  const v = structuredClone(fixture);
  v.map = structuredClone(fixture.territory_map);
  return v;
};
const strip = (v) => statusStrip(v, {}, { act: () => {} });
const chip = (el, name) => el.querySelectorAll('button.rl-eco-chip').find((b) => b.getAttribute('data-nation') === name);
const NORRA = fixture.economy.figures[0].nation.key;
const SUDLAND = fixture.economy.figures[1].nation.key;

// --- Rule 1: one figure per nation in the top strip ---------------------------------------

test('the top strip shows one war-economy figure per nation, the seat\'s own marked', () => {
  const el = strip(rv());
  const chips = el.querySelectorAll('button.rl-eco-chip');
  assert.equal(chips.length, 2);
  assert.equal(words(chips[0]), 'Norra (yours) 100');
  assert.equal(words(chips[1]), 'Sudland 1.2');
});

test('a game with no economy block has no figures in the strip', () => {
  const v = rv();
  delete v.economy;
  assert.equal(strip(v).querySelectorAll('button.rl-eco-chip').length, 0);
});

// --- Rule 2: the seat's own sheet, under the world's own names -----------------------------

test('a tap on the seat\'s own figure opens its components under the world\'s own resource names', () => {
  const el = strip(rv());
  assert.equal(el.querySelectorAll('.rl-eco-sheet').length, 0, 'closed until tapped');
  fire(chip(el, NORRA), 'click');
  const sheet = el.querySelector('.rl-eco-sheet');
  assert.ok(sheet);
  assert.equal(chip(el, NORRA).getAttribute('aria-expanded'), 'true');
  const income = sheet.querySelectorAll('.rl-eco-income li').map(words);
  assert.deepEqual(income, ['Grain 10 tons', 'Iron 0 tons', 'Levies 2000 men', 'Pitch 0 barrels', 'Rails 0 miles', 'Glory 1 laurels']);
  const pools = sheet.querySelectorAll('.rl-eco-pools li').map(words);
  assert.deepEqual(pools, ['Grain, Iron: 10 in the pool', 'Levies: 2000 in the pool']);
  assert.match(words(sheet.querySelector('.rl-eco-fuel')), /^Pitch: no stock is kept/);
  fire(chip(el, NORRA), 'click');
  assert.equal(el.querySelectorAll('.rl-eco-sheet').length, 0, 'a second tap closes it');
});

test('months of fuel are said under the fuel resource\'s own name when a stock is kept', () => {
  const v = rv();
  v.economy.own.fuel_months = 3.5;
  const el = strip(v);
  fire(chip(el, NORRA), 'click');
  assert.equal(words(el.querySelector('.rl-eco-fuel')), 'Pitch lasts 3.5 months at this income');
});

test('the months of fuel are drawn as a bar against twelve months, beside the stock and the months it lasts', () => {
  const v = rv();
  v.economy.own.pools.fuel = 420;
  v.economy.own.fuel_months = 3.5;
  const el = strip(v);
  fire(chip(el, NORRA), 'click');
  const row = el.querySelector('.rl-eco-fuelrow');
  assert.ok(row, 'the stock and the months sit in one row');
  assert.equal(words(row.querySelector('.rl-eco-stock')), 'Pitch stock 420');
  const bar = row.querySelector('.rl-mark-bar');
  assert.equal(bar.getAttribute('aria-label'), 'Pitch lasts: 3.5 of 12 months');
  assert.equal(bar.querySelector('.rl-mark-fill').getAttribute('data-share'), '29.17');
  assert.equal(words(row.querySelector('.rl-eco-fuel')), 'Pitch lasts 3.5 months at this income');
});

test('a stock with no months sent draws no bar, and no stock sent draws none', () => {
  const v = rv();
  v.economy.own.pools.fuel = 90;
  const el = strip(v);
  fire(chip(el, NORRA), 'click');
  assert.equal(words(el.querySelector('.rl-eco-stock')), 'Pitch stock 90');
  assert.equal(el.querySelector('.rl-eco-fuelrow .rl-mark-bar'), null);
  const none = strip(rv());
  fire(chip(none, NORRA), 'click');
  assert.equal(none.querySelectorAll('.rl-eco-stock').length, 0);
});

test('the sheet is drawn from tokens only and its fuel row wraps', () => {
  const css = read('css/c-economy.css');
  assert.equal(css.match(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl/g), null);
  assert.match(css, /\.rl-eco-fuelrow \{[^}]*flex-wrap: wrap/);
});

test('the sheet lists the territories that pay less than they print, and why', () => {
  const v = rv();
  const hills = v.map.areas.find((a) => a.key === 'norra_hills');
  hills.yields = { grain: 4 };
  hills.held_since = '1900-03-20';
  hills.taken_from = { key: SUDLAND, name: 'Sudland', relation: 'enemy' };
  v.economy.own.territories.find((t) => t.area === 'norra_hills').factors.output = 0;
  v.map.areas.find((a) => a.key === 'norra_plain').yields = { grain: 6, levies: 2000 };
  const el = strip(v);
  fire(chip(el, NORRA), 'click');
  const rows = el.querySelectorAll('.rl-eco-less li');
  const row = (k) => rows.find((r) => r.getAttribute('data-area') === k);
  assert.ok(row('norra_hills'), 'a territory that pays nothing of what it prints is listed');
  assert.match(words(row('norra_hills')), /Grain: pays 0 of 4 printed, because it pays nothing yet, taken 20 March from Sudland/);
  assert.equal(row('norra_plain'), undefined, 'a territory that pays what it prints is not listed');
});

test('a moved industry and a part-paying capture are told apart from a plain shortfall', () => {
  const own = {
    income: [{ key: 'coal', name: 'Coal', unit: 'ktons', role: 'output', amount: 0 }],
    territories: [
      { area: 'a', name: 'A', yields: { coal: 2 }, factors: { output: 1 } },
      { area: 'b', name: 'B', yields: { coal: 8 }, factors: { output: 0.5 } },
    ],
  };
  const printed = new Map([['a', { coal: 8 }], ['b', { coal: 8 }]]);
  const out = eco.shortfalls(own, printed, new Map());
  assert.match(out[0].lines[0].why, /industry has moved/);
  assert.match(out[1].lines[0].why, /only 50 in 100 of it reaches you/);
});

// --- Rule 3: another nation's -------------------------------------------------------------

test('a tap on another nation\'s figure shows the figure and says it is read from the map, and no components', () => {
  const el = strip(rv());
  fire(chip(el, SUDLAND), 'click');
  const sheet = el.querySelector('.rl-eco-sheet');
  assert.match(words(sheet), /War-economy figure 1\.2/);
  assert.match(words(sheet), /Read from the map/);
  assert.equal(sheet.querySelectorAll('.rl-eco-income, .rl-eco-pools, .rl-eco-less').length, 0);
  assert.doesNotMatch(words(sheet), /Grain|Levies|Pitch/);
});

test('a client given another nation\'s components does not draw them', () => {
  const v = rv();
  v.economy.own.nation = { ...v.economy.figures[1].nation };
  const el = strip(v);
  fire(chip(el, SUDLAND), 'click');
  // a nation marked enemy never gets the own sheet, even if `own` named it
  assert.equal(el.querySelectorAll('.rl-eco-income').length, 0);
});

// --- Rule 4: the economy layer -------------------------------------------------------------

const layerMap = () => rv().map;
const draw = (map, layer) => territoryDrawing(map, SHAPES, { px: DESK, layer });
const pips = (pic, key) => pic.querySelectorAll('g.rl-eco-pips').find((g) => g.getAttribute('data-area') === key);

test('the economy layer is offered after the others, and the board does not open on it', () => {
  const view = territoryView(layerMap(), SHAPES, { mode: 'map' });
  const layers = view.querySelectorAll('[aria-label="Layer"] button').map(words);
  assert.equal(layers.at(-1), 'Economy');
  assert.equal(view.querySelectorAll('[aria-label="Layer"] button').find((b) => words(b) === 'Economy').getAttribute('aria-pressed'), 'false');
  assert.ok(view.querySelector('svg'));
  assert.equal(view.querySelectorAll('g.rl-eco-pips').length, 0, 'no pips on the first layer');
});

test('the economy layer draws each territory\'s yields as pips, by the world\'s resource, and no number', () => {
  const pic = draw(layerMap(), 'economy');
  const plain = pips(pic, 'norra_plain');
  assert.ok(plain);
  const resources = new Set(plain.querySelectorAll('circle.rl-eco-pip').map((c) => c.getAttribute('data-resource')));
  assert.deepEqual([...resources].sort(), ['grain', 'levies']);
  assert.equal(pips(pic, 'the_gulf'), undefined, 'a sea zone has none');
  assert.equal(plain.querySelectorAll('text').length, 0, 'no number is printed on the map');
  assert.doesNotMatch(words(pic.querySelector('.rl-tm-frame')).replace(/The [A-Z][a-z]+( [A-Z][a-z]+)?/g, ''), /\b\d+\b/);
});

test('a tap on a territory\'s pips shows its numbers and a second tap takes them away; the name carries them for a screen reader', () => {
  const pic = draw(layerMap(), 'economy');
  const plain = pips(pic, 'norra_plain');
  assert.match(plain.getAttribute('aria-label'), /^The Norra Plain: grain 10, levies 2000$/);
  fire(plain, 'click');
  assert.equal(words(plain.querySelector('text')), 'grain 10, levies 2000');
  fire(plain, 'click');
  assert.equal(plain.querySelectorAll('text').length, 0);
  plain.dispatchEvent({ type: 'keydown', key: 'Enter', preventDefault() {}, stopPropagation() {} });
  assert.equal(plain.querySelectorAll('text').length, 1, 'Enter does the same as a tap');
});

test('a bigger yield of a resource draws more pips than a smaller one', () => {
  const pic = draw(layerMap(), 'economy');
  const count = (key) => pips(pic, key).querySelectorAll('circle.rl-eco-pip').filter((c) => c.getAttribute('data-resource') === 'grain').length;
  assert.ok(count('norra_plain') > count('sudland_coast'));
});

test('c-economy.css uses tokens only, wraps its sheet and is linked from the page', () => {
  const css = read('css/c-economy.css').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.doesNotMatch(css, /#[0-9a-f]{3,8}\b/i);
  assert.doesNotMatch(css, /rgba?\(/);
  assert.match(css, /\.rl-eco-chip\s*\{[^}]*min-height: 44px/);
  assert.match(css, /overflow-wrap: anywhere/);
  assert.match(read('index.html'), /href="\/css\/c-economy\.css"/);
});
