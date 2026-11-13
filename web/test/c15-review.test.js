// The console room's phone paths, from the 15a review: the messenger clears the tab bar, focus
// survives a panel switch and a closed messenger, and the aide's thread is the Messages tab.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { installDom } from './dom-fake.js';

installDom();
const { h } = await import('../js/dom.js');
const { sideSwitch, tabBar } = await import('../js/views/realism-tabs.js');
const { summaryTiles } = await import('../js/views/realism-status.js');
const room = await import('../js/views/realism-room.js');

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const uncomment = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));
const rv = { ...fixture, documents: fixture.listing };
const ui = { tab: 'desk', side: 'papers', chat: { open: false } };
const pick = () => {};

/** The rules of one `@media (max-width: Npx)` block, up to its closing brace at column 0. */
function phoneBlock(css, px) {
  const at = css.indexOf(`@media (max-width: ${px}px) {`);
  assert.ok(at >= 0, `a ${px}px block`);
  return css.slice(at, css.indexOf('\n}', at));
}

const roomParts = () => h('div', {},
  summaryTiles(rv, pick), sideSwitch(ui, pick), tabBar(rv, ui, pick),
  h('button', { type: 'button', class: 'rl-msgr-btn', 'aria-expanded': 'false' }, 'Messages'));

test('on a phone the open messenger stops at the tab bar, so its composer is not under it', () => {
  const shell = phoneBlock(uncomment(read('css/c-shell.css')), 767);
  const button = /\.rl-tabbar button \{[^}]*min-height: (\d+)px/.exec(shell);
  const border = /\.rl-tabbar \{[^}]*border-top: (\d+)px/.exec(shell);
  assert.ok(button && border, 'the tab bar sets its button height and top border');
  const bar = Number(button[1]) + Number(border[1]);
  const chat = phoneBlock(uncomment(read('css/p5-chat.css')), 767);
  const panel = /\.rl-msgr-panel \{([^}]*)\}/.exec(chat)?.[1] ?? '';
  const bottom = /(?:^|;)\s*bottom: (\d+)px/.exec(panel) ?? /inset: 0 0 (\d+)px/.exec(panel);
  assert.ok(bottom, 'the phone panel sets its bottom edge');
  assert.equal(Number(bottom[1]), bar);
});

test('a closed messenger gives focus back to the launcher, or on a phone to the Messages tab', () => {
  const root = roomParts();
  const { closedChatTarget } = room;
  assert.equal(typeof closedChatTarget, 'function');
  assert.equal(closedChatTarget(root, false), root.querySelector('.rl-msgr-btn'));
  const tab = closedChatTarget(root, true);
  assert.ok(tab?.closest('.rl-tabbar'), 'a tab bar button');
  assert.match(tab.textContent, /^Messages/);
});

test('a tab, side or tile pick keeps focus on the same switch after the redraw', () => {
  const { switchPlace, switchAt } = room;
  assert.equal(typeof switchPlace, 'function');
  assert.equal(typeof switchAt, 'function');
  const before = roomParts();
  const after = roomParts();
  for (const sel of ['.rl-tabbar', '.rl-sideswitch', '.rl-tiles']) {
    const all = before.querySelector(sel).querySelectorAll('button');
    const el = all[1];
    const place = switchPlace(el);
    assert.deepEqual(place, { sel, at: 1 }, sel);
    const again = switchAt(after, place);
    assert.equal(again, after.querySelector(sel).querySelectorAll('button')[1], sel);
  }
  assert.equal(switchPlace(before.querySelector('.rl-msgr-btn')), null, 'not a panel switch');
  assert.equal(switchPlace(null), null);
});

test('the room puts focus back after a pick: the messenger for Messages, else the switch used', () => {
  const src = read('js/views/realism-room.js');
  const pickSrc = src.slice(src.indexOf('const pick = '), src.indexOf('function build()'));
  assert.match(pickSrc, /const place = switchPlace\(document\.activeElement\);/);
  assert.match(pickSrc, /if \(p\.tab === 'messages'\) refocus\(ui\.chat\);/);
  assert.match(pickSrc, /else switchAt\(root, place\)\?\.focus\(\);/);
  assert.match(src, /const target = !chat\.open \? closedChatTarget\(root, phoneWidth\(\)\)/);
});

test('when the aide writes, its thread opens and the phone tab bar marks Messages', () => {
  const { openAide } = room;
  assert.equal(typeof openAide, 'function');
  const state = { tab: 'orders', chat: { open: false, tab: 'contacts', thread: null } };
  openAide(state);
  assert.deepEqual(state.chat, { open: true, tab: 'chats', thread: 'aide' });
  assert.equal(state.tab, 'messages');
  assert.match(read('js/views/realism-room.js'), /if \(r\.help\) openAide\(ui\);/);
});
