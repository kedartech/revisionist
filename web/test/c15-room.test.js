// The console room after the 15a wave: the strip alone carries the date and Done for today,
// and a phone tab other than Messages closes the messenger (Josh, 13 Nov).
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { buttons, installDom, words } from './dom-fake.js';

installDom();
const { DONE_HINT, wakeHeader } = await import('../js/views/realism-wake.js');
const { pickPanel } = await import('../js/views/realism-room.js');

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));
const act = () => {};

test('the header wake keeps when it closes and the count, and leaves Done for today to the strip', () => {
  const open = wakeHeader(fixture.wake_solo, { act });
  assert.equal(fixture.wake_solo.you_committed, false);
  assert.equal(buttons(open, 'Done for today').length, 0);
  assert.ok(!words(open).includes(DONE_HINT), 'no hint under a button that is not there');
  assert.match(words(open), /Closes /);
  assert.match(words(open), /0 of 1 player done/);
  const sealed = wakeHeader(fixture.wake, { act });
  assert.equal(fixture.wake.you_committed, true);
  assert.doesNotMatch(words(sealed), /Done, waiting on/);
  assert.match(words(sealed), /1 of 2 players done/);
});

test('the room header keeps the pace line and leaves the date to the strip', () => {
  const room = read('js/views/realism-room.js');
  const build = room.slice(room.indexOf('function build()'));
  assert.match(build, /class: 'stack rl-clock' \}, paceHeader\(rv\.clock\)\)/);
  assert.doesNotMatch(build, /class: 'title' \}, worldDate/);
  assert.match(build, /statusStrip\(rv, ui, \{ act \}\)/);
});

test('on a phone, a tab other than Messages closes the messenger and keeps its thread', () => {
  const ui = { tab: 'messages', side: 'papers', chat: { open: true, thread: 'Harry Hopkins' } };
  for (const tab of ['papers', 'desk', 'orders']) {
    pickPanel(ui, { tab: 'messages' }, true);
    assert.equal(ui.chat.open, true);
    pickPanel(ui, { tab }, true);
    assert.equal(ui.tab, tab);
    assert.equal(ui.chat.open, false, tab);
    assert.equal(ui.chat.thread, 'Harry Hopkins');
  }
});

test('wider than a phone, a tile leaves the messenger as it is; the side switch never touches it', () => {
  const ui = { tab: 'desk', side: 'papers', chat: { open: true, thread: null } };
  pickPanel(ui, { tab: 'orders' }, false);
  assert.equal(ui.tab, 'orders');
  assert.equal(ui.chat.open, true);
  pickPanel(ui, { side: 'orders' }, true);
  assert.equal(ui.side, 'orders');
  assert.equal(ui.chat.open, true);
});

test('the room reads phone width at the tab bar\'s own breakpoint', () => {
  const room = read('js/views/realism-room.js');
  const shell = read('css/c-shell.css');
  const at = /matchMedia\?\.\('\(max-width: (\d+)px\)'\)/.exec(room);
  assert.ok(at, 'the room asks matchMedia for a max-width');
  const block = shell.slice(shell.indexOf(`@media (max-width: ${at[1]}px)`));
  assert.ok(shell.includes(`@media (max-width: ${at[1]}px)`), 'c-shell.css has the same breakpoint');
  assert.match(block, /\.rl-tabbar \{ display: grid/);
  assert.match(room, /pickPanel\(ui, p, phoneWidth\(\)\)/);
});
