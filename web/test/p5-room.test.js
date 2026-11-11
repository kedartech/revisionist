// The room hub (contract K2): the parts of realism-room.js that run without a page.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { happenedDue, orderContacts, uiFor } from '../js/views/realism-room.js';
import { happenedStore } from '../js/views/realism-happened.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');

const inner = [{ person: 'Harry Hopkins', channel: 'in_person', channels: ['in_person', 'letter'] }];

test('a contact from the messenger joins the order form with its channels', () => {
  const stark = { name: 'Harold R. Stark', title: 'Chief of Naval Operations', channel_keys: ['in_person', 'cable'] };
  assert.deepEqual(orderContacts(inner, stark), [...inner,
    { person: 'Harold R. Stark', title: 'Chief of Naval Operations', channel: 'in_person', channels: ['in_person', 'cable'] }]);
  assert.equal(orderContacts(inner, null), inner);
  assert.equal(orderContacts(inner, { name: 'Harry Hopkins', channel_keys: ['letter'] }), inner);
});

test('a contact with no channel is left off the order form', () => {
  assert.equal(orderContacts(inner, { name: 'Burton K. Wheeler', title: null, channel_keys: [] }), inner);
  assert.equal(orderContacts(inner, { name: 'Burton K. Wheeler', title: null }), inner);
});

test('the room keeps its picks for one game and starts clean in another', () => {
  const ui = uiFor('g1');
  ui.draft = { to: 'Harry Hopkins', channel: 'letter', text: 'Come at once' };
  ui.orderTo = { name: 'Harold R. Stark', channel_keys: ['cable'] };
  assert.equal(uiFor('g1').draft.text, 'Come at once');
  const other = uiFor('g2');
  assert.equal(other.draft, null);
  assert.equal(other.orderTo, null);
  assert.equal(other.contact, null);
  assert.deepEqual(other.chat, { open: false, tab: 'chats', thread: null });
});

test('closing the What happened sheet by any means counts as seen', () => {
  const room = read('js/views/realism-room.js');
  assert.match(room, /happened\?\.addEventListener\('close', \(\) => \{[^}]*shown\.write\(page\.number\)/);
  assert.match(room, /happened\?\.addEventListener\('close', \(\) => \{[^}]*ui\.happenedSeen = page\.number/);
});

test('the page reads browser storage only through browserStorage', () => {
  for (const f of ['js/app.js', 'js/views/realism-room.js']) {
    assert.doesNotMatch(read(f), /window\.localStorage/, f);
    assert.match(read(f), /browserStorage\(window\)/, f);
  }
});

test('What happened shows once per wake even where storage is blocked', () => {
  const blocked = happenedStore({ getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } }, 'c1');
  assert.equal(happenedDue({ number: 3 }, blocked, null), true);
  assert.equal(happenedDue({ number: 3 }, blocked, 3), false);
  assert.equal(happenedDue({ number: 4 }, blocked, 3), true);
  assert.equal(happenedDue(null, blocked, null), false);
  assert.equal(happenedDue({ number: 0 }, blocked, null), false);
});

test('the desk foot repeats Done for today without a second live count', () => {
  const src = read('js/views/realism-wake.js');
  const foot = src.slice(src.indexOf('export function commitPanel'), src.indexOf('/** The order the aide read'));
  assert.doesNotMatch(foot, /aria-live/);
});
