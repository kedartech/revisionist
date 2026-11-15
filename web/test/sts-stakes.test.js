// The stakes strip: under the status strip, in both views, one tile per stake and then one per
// open mandate; a tile shows the name and days left, and the lean only when the data carries
// one; with no stakes and no mandates the strip is not drawn.
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
const { daysLeft, stakesStrip } = await import('../js/views/realism-stakes.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');
const stakes = () => structuredClone(fixture.stakes);

const tiles = (strip) => strip.querySelectorAll('.rl-stake');
const names = (strip) => tiles(strip).map((t) => words(t.querySelector('.rl-stake-name')));

/** The whole room for a fresh game, in the page, with no model or server behind it. */
function room(over = {}) {
  const doc = installDom();
  api.realism = async () => ({});
  const rv = { ...fixture, documents: fixture.listing, wake_tick: 1, ...over };
  const me = { account: { handle: 'josh' }, game: { id: `g-${Math.random()}`, name: 'Autumn 1941', view: { realism: rv, seat: { name: 'Franklin D. Roosevelt' } } } };
  const root = realismRoom({ me, refresh: async () => {}, go: () => {} });
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  return root;
}

/** The element right after the status strip in the room. */
function afterStrip(root) {
  const kids = root.children;
  const at = kids.findIndex((k) => k.classList.contains('rl-strip'));
  assert.ok(at >= 0, 'the status strip');
  return kids[at + 1] ?? null;
}

test('the fixture carries contests with and without a lean, and a mandate', () => {
  const s = fixture.stakes;
  assert.ok(s.contests.some((c) => c.lean) && s.contests.some((c) => !c.lean), 'both kinds of contest');
  assert.ok(s.mandates.length > 0, 'a mandate');
});

test('one tile per stake, in the data\'s order, then one per open mandate', () => {
  const strip = stakesStrip(stakes());
  const s = fixture.stakes;
  assert.deepEqual(names(strip), [...s.contests.map((c) => c.name), ...s.mandates.map((m) => m.text)]);
  const kinds = tiles(strip).map((t) => t.getAttribute('data-kind'));
  assert.deepEqual(kinds, [...s.contests.map(() => 'contest'), ...s.mandates.map(() => 'mandate')]);
  assert.equal(strip.getAttribute('role'), 'region');
  assert.ok(strip.getAttribute('aria-label'), 'a name for the region');
});

test('a tile shows the name and the days left', () => {
  const s = stakes();
  s.contests[0].days_left = 24;
  s.mandates[0].days_left = 6;
  const strip = stakesStrip(s);
  const t = tiles(strip);
  assert.equal(words(t[0].querySelector('.rl-stake-days')), '24 days left');
  assert.equal(words(t.at(-1).querySelector('.rl-stake-days')), '6 days left');
  for (const tile of t) assert.ok(words(tile.querySelector('.rl-stake-name')), 'a name on every tile');
});

test('days left reads one day, many days, and due now at zero', () => {
  assert.equal(daysLeft(1), '1 day left');
  assert.equal(daysLeft(2), '2 days left');
  assert.equal(daysLeft(48), '48 days left');
  assert.equal(daysLeft(0), 'Due now');
});

test('a contest\'s prize is its tile\'s title', () => {
  const strip = stakesStrip(stakes());
  assert.equal(tiles(strip)[0].getAttribute('title'), fixture.stakes.contests[0].prize);
});

test('the lean shows only on a contest whose data carries one', () => {
  const s = stakes();
  const strip = stakesStrip(s);
  const t = tiles(strip);
  s.contests.forEach((c, i) => {
    assert.equal(Boolean(t[i].querySelector('.rl-stake-lean')), Boolean(c.lean), c.name);
  });
  for (const m of t.slice(s.contests.length)) assert.equal(m.querySelector('.rl-stake-lean'), null, 'no lean on a mandate');
});

test('a lean draws ten steps, as many on as its step, toward the first side, and names who it favours', () => {
  const s = stakes();
  s.contests = [{ name: 'A', prize: 'p', sides: ['Ayes', 'Noes'], days_left: 3, lean: { step: 7, favours: 'Ayes' } }];
  s.mandates = [];
  const lean = tiles(stakesStrip(s))[0].querySelector('.rl-stake-lean');
  const bar = lean.querySelector('.rl-stake-bar');
  const cells = bar.querySelectorAll('span');
  assert.equal(cells.length, 10);
  assert.equal(cells.filter((c) => c.classList.contains('on')).length, 7);
  assert.ok(cells.slice(0, 7).every((c) => c.classList.contains('on')), 'the steps on come first');
  assert.equal(bar.getAttribute('role'), 'img');
  assert.equal(bar.getAttribute('aria-label'), '7 of 10 steps toward Ayes');
  assert.equal(words(lean.querySelector('.rl-stake-side')), 'Leaning to Ayes');
});

test('a lean that favours no side says so', () => {
  const s = { contests: [{ name: 'A', prize: 'p', sides: ['Ayes', 'Noes'], days_left: 3, lean: { step: 6, favours: null } }], mandates: [] };
  const lean = tiles(stakesStrip(s))[0].querySelector('.rl-stake-lean');
  assert.equal(words(lean.querySelector('.rl-stake-side')), 'No side ahead');
  assert.equal(lean.querySelector('.rl-stake-bar').querySelectorAll('span.on').length, 6);
});

test('no stakes and no mandates: no strip', () => {
  assert.equal(stakesStrip({ contests: [], mandates: [] }), null);
  assert.equal(stakesStrip(undefined), null);
  assert.equal(stakesStrip(null), null);
  assert.equal(stakesStrip({}), null);
});

test('contests alone, or mandates alone, still draw the strip', () => {
  const s = stakes();
  assert.equal(tiles(stakesStrip({ contests: s.contests, mandates: [] })).length, s.contests.length);
  assert.equal(tiles(stakesStrip({ contests: [], mandates: s.mandates })).length, s.mandates.length);
});

test('the room shows the strip right under the status strip on the Desk view', () => {
  const root = room();
  assert.ok(root.querySelector('main.rl-room'), 'the Desk view');
  const next = afterStrip(root);
  assert.ok(next?.classList.contains('rl-stakes'), 'the stakes strip follows the status strip');
  assert.equal(root.querySelectorAll('.rl-stakes').length, 1);
});

test('the room shows the strip right under the status strip on the Board view', () => {
  const root = room();
  buttons(root.querySelector('.rl-viewswitch'), 'Board')[0].click();
  assert.ok(root.querySelector('.rl-board'), 'the Board view');
  const next = afterStrip(root);
  assert.ok(next?.classList.contains('rl-stakes'), 'the stakes strip follows the status strip');
  assert.equal(root.querySelectorAll('.rl-stakes').length, 1);
});

test('the room draws no strip when the seat has no stakes and no mandates', () => {
  for (const over of [{ stakes: { contests: [], mandates: [] } }, { stakes: undefined }]) {
    const root = room(over);
    assert.equal(root.querySelector('.rl-stakes'), null);
    buttons(root.querySelector('.rl-viewswitch'), 'Board')[0].click();
    assert.equal(root.querySelector('.rl-stakes'), null, 'nor on the Board');
  }
});

test('the strip\'s file builds text nodes only, and its stylesheet is linked and uses tokens only', () => {
  const js = read('js/views/realism-stakes.js');
  assert.doesNotMatch(js, /innerHTML|outerHTML|insertAdjacentHTML|style=/);
  assert.ok(read('index.html').includes('href="/css/c-stakes.css"'), 'linked from the page');
  const css = read('css/c-stakes.css').replace(/\/\*[\s\S]*?\*\//g, '');
  for (const sel of ['.rl-stakes', '.rl-stake', '.rl-stake-bar', '.rl-stake-bar span.on']) assert.ok(css.includes(sel), sel);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(/, 'tokens only');
  const phone = css.slice(css.indexOf('@media (max-width: 767px)'));
  assert.ok(phone.length < css.length, 'a phone block');
  assert.match(css, /\.rl-stakes-list \{[^}]*overflow-x: auto/, 'the tiles scroll sideways, not the page');
});
