// "The world" tab of the press desk (DV2): the public developments that have fired, newest first,
// each with its day, category and headline, and the orders it suggests, each one a button that
// puts the words in the order form. The tab shows only when the server sends the world.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { buttons, installDom, words } from './dom-fake.js';
import { WORLD_TAB, pressDock, pressMarks, pressTab, pressPapers } from '../js/views/realism-press.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const uncomment = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

const LEDGER = 'The Washington Ledger';
const page = (id, arrives) => ({ id, kind: 'press', title: id, author: LEDGER, issued: arrives, arrives,
  channel: 'press', classification: 'open', unread: false, flagged: false, group: null, ack: false, answer: false });
const papers = pressPapers([page('l1', '1941-09-05'), page('l2', '1941-09-12')]);
const WORLD = fixture.world;

const dock = (state, extra = {}) => pressDock({ state, onState() {}, papers, marks: {}, world: WORLD, ...extra });

test('the fixture carries the world as the server sends it', () => {
  assert.ok(Array.isArray(WORLD) && WORLD.length >= 2);
  for (const d of WORLD) assert.deepEqual(Object.keys(d).sort(), ['asks', 'category', 'headline', 'id', 'on']);
  assert.ok(WORLD.some((d) => d.asks.length) && WORLD.some((d) => !d.asks.length));
});

test('a "The world" tab sits after the papers, and only when the server sends the world', () => {
  installDom();
  const tabs = (el) => [...el.querySelectorAll('[role="tab"]')].map((b) => words(b));
  assert.deepEqual(tabs(dock({ open: true, tab: null })), [LEDGER, 'The world']);
  assert.deepEqual(tabs(dock({ open: true, tab: null }, { world: undefined })), [LEDGER], 'an older server: no tab');
  const noPapers = pressDock({ state: { open: true, tab: null }, onState() {}, papers: [], marks: {}, world: [] });
  assert.deepEqual(tabs(noPapers), ['The world'], 'the world shows with no paper yet');
});

test('the tab picked stays while the world is sent, and falls back to the first paper otherwise', () => {
  assert.equal(pressTab(papers, WORLD_TAB, true), WORLD_TAB);
  assert.equal(pressTab(papers, WORLD_TAB, false), LEDGER);
  assert.equal(pressTab(papers, WORLD_TAB), LEDGER);
  assert.equal(pressTab(papers, LEDGER, true), LEDGER);
  assert.equal(pressTab([], null, true), null);
});

test('the world lists each development newest first with its day, category, headline and asks', () => {
  installDom();
  const desk = dock({ open: true, tab: WORLD_TAB });
  const tab = [...desk.querySelectorAll('[role="tab"]')].find((b) => words(b) === 'The world');
  assert.equal(tab.getAttribute('aria-selected'), 'true');
  const panel = desk.querySelector('[role="tabpanel"]');
  assert.equal(panel.getAttribute('aria-label'), 'The world');
  const items = panel.querySelectorAll('.rl-world-item');
  assert.equal(items.length, WORLD.length);
  assert.deepEqual(items.map((li) => words(li.querySelector('.rl-world-head'))), WORLD.map((d) => d.headline));
  assert.equal(words(items[0].querySelector('.rl-world-meta')), '11 September 1941 · Public figures');
  assert.equal(words(items[1].querySelector('.rl-world-meta')), '4 September 1941 · Espionage');
  assert.deepEqual(items[0].querySelectorAll('.rl-world-asks li').map((li) => words(li.querySelector('.rl-world-ask'))),
    ['Answer Lindbergh in a public statement']);
  assert.equal(items[1].querySelectorAll('.rl-world-asks li').length, 0, 'a suggestive one offers nothing');
  assert.equal(panel.querySelectorAll('.rl-pd-list').length, 0, 'no paper\'s pages on the world tab');
});

test('the world is listed newest first whatever order it arrives in', () => {
  installDom();
  const desk = dock({ open: true, tab: WORLD_TAB }, { world: [...WORLD].reverse() });
  const heads = desk.querySelectorAll('.rl-world-item .rl-world-head').map((el) => words(el));
  assert.deepEqual(heads, WORLD.map((d) => d.headline));
});

test('an ask is a button that hands its words to the order form, and nothing is filed', () => {
  installDom();
  const asked = [];
  const desk = dock({ open: true, tab: WORLD_TAB }, { onAsk: (text) => asked.push(text) });
  const [btn] = buttons(desk, 'Write it as an order');
  assert.equal(btn.getAttribute('aria-label'), 'Write it as an order: Answer Lindbergh in a public statement');
  btn.click();
  assert.deepEqual(asked, ['Answer Lindbergh in a public statement']);
  const bare = dock({ open: true, tab: WORLD_TAB });
  assert.equal(buttons(bare, 'Write it as an order').length, 0, 'no handler, no button');
});

test('an empty world says so', () => {
  installDom();
  const desk = dock({ open: true, tab: WORLD_TAB }, { world: [] });
  assert.match(words(desk.querySelector('[role="tabpanel"]')), /Nothing in the world has made the news yet/);
});

test('the world tab marks no paper seen', () => {
  const counts = { [LEDGER]: 2 };
  assert.deepEqual(pressMarks(counts, { [LEDGER]: 0 }, { open: true, tab: WORLD_TAB }), { [LEDGER]: 0 });
});

test('the room sends the world to the desk and an ask to the order form', () => {
  const room = uncomment(read('js/views/realism-room.js'));
  assert.match(room, /world: rv\.world/);
  assert.match(room, /pressTab\(papers, ui\.press\.tab, Array\.isArray\(rv\.world\)\)/);
  assert.match(room, /onAsk: writeOrder/);
  assert.match(room, /function writeOrder\(text\)/);
  assert.match(room, /startsWith\('n\.'\)/, 'a news idea opens the form instead of filing');
  assert.match(room, /if \(news\) return writeOrder\(news\.label\)/);
});

test('the world styles live in the press sheet, tokens only', () => {
  const css = read('css/p5-press.css');
  for (const cls of ['.rl-world-item', '.rl-world-meta', '.rl-world-head', '.rl-world-asks']) assert.ok(css.includes(cls), cls);
  const world = css.split('\n').filter((l) => l.includes('rl-world')).join('\n');
  assert.doesNotMatch(world, /#[0-9a-fA-F]{3,8}\b/, 'no raw colours');
});
