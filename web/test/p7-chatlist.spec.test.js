// Spec for wave M unit M4 (the Chats list), written with contract KM: the unit makes it pass and
// never edits it. Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { installDom, words } from './dom-fake.js';
import { chatList, chatRows } from '../js/views/realism-chatlist.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

const at = (side, text, iso) => ({ side, kind: 'counsel', text, day: `${Number(iso.slice(8))} October 1941`, iso, docId: null });
const THREADS = {
  aide: [
    at('mine', 'How do I get a bill to the floor?', '1941-10-14'),
    at('theirs', 'Through the Speaker: Sam Rayburn schedules it. The bill form does it.', '1941-10-14'),
    at('theirs', 'Your order to Wheeler did not go through: he would not take it while the rallies go on.', '1941-10-16'),
  ],
  'Harry Hopkins': [
    at('mine', 'How much did we ship in September?', '1941-10-13'),
    at('theirs', 'Short of the promise by a third. My memo has the figures.', '1941-10-13'),
    at('theirs', 'Letter received: Lend-Lease shipments, September tonnage', '1941-10-16'),
    at('theirs', 'Harriman thinks so, if the tanks arrive before the ports freeze.', '1941-10-17'),
  ],
  'Sam Rayburn': [
    at('theirs', 'On your order: Send a bill to Congress', '1941-10-12'),
    at('theirs', 'Letter received: House count on the Neutrality Act revision', '1941-10-19'),
  ],
  'Harold R. Stark': [
    at('theirs', 'Clear orders to shoot first, Mr. President.', '1941-10-15'),
    at('mine', 'Can the escorts reach Iceland by the 25th? And how many divisions does King hold?', '1941-10-19'),
  ],
  'Burton K. Wheeler': [],
};
const input = { threads: THREADS, reach: fixture.reach, record: fixture.record, seen: { 'Harry Hopkins': 2, aide: 2 } };

test('the aide first, then the newest conversation, ties by name; no row without a line', () => {
  assert.deepEqual(chatRows(input).map((r) => r.key), ['aide', 'Harold R. Stark', 'Sam Rayburn', 'Harry Hopkins']);
});

test('a row: initials, office, the last line cut to 60 characters, its day, what is new, what they hold', () => {
  const rows = Object.fromEntries(chatRows(input).map((r) => [r.key, r]));
  assert.deepEqual(rows['Harold R. Stark'], {
    key: 'Harold R. Stark', name: 'Harold R. Stark', initials: 'HS', title: 'Chief of Naval Operations',
    preview: 'You: Can the escorts reach Iceland by the 25th? And how man…', day: '19 October 1941',
    unread: 1, holds: 'Has your order: Escort the convoys to Iceland and shoot on sight',
  });
  assert.equal(rows['Sam Rayburn'].preview, 'Letter received: House count on the Neutrality Act revision');
  assert.equal(rows['Sam Rayburn'].holds, 'Has your order: Send a bill to Congress: Revise the Neutrality Act');
  assert.equal(rows['Sam Rayburn'].unread, 2);
  assert.equal(rows['Harry Hopkins'].unread, 1);
  assert.equal(rows['Harry Hopkins'].holds, null);
  assert.equal(rows['Harry Hopkins'].initials, 'HH');
  assert.deepEqual(rows.aide, {
    key: 'aide', name: 'Your aide', initials: 'YA', title: null,
    preview: 'Your order to Wheeler did not go through: he would not take…', day: '16 October 1941',
    unread: 0, holds: null,
  });
});

test('with nothing said yet, the aide is still listed', () => {
  assert.deepEqual(chatRows({ threads: { aide: [] }, reach: fixture.reach, record: fixture.record, seen: {} }), [
    { key: 'aide', name: 'Your aide', initials: 'YA', title: null, preview: null, day: null, unread: 0, holds: null },
  ]);
});

test('the list: a button per row that opens it, with the new mark said aloud', () => {
  installDom();
  const opened = [];
  const rows = chatRows(input);
  const list = chatList({ rows, onOpen: (k) => opened.push(k) });
  assert.ok(list, 'a list');
  const buttons = list.querySelectorAll('.rl-cl-row');
  assert.equal(buttons.length, 4);
  assert.match(words(buttons[1]), /Harold R\. Stark/);
  assert.equal(words(buttons[1].querySelector('.rl-cl-preview')), rows[1].preview);
  assert.match(words(buttons[1]), /New: /);
  assert.doesNotMatch(words(buttons[0]), /New: /, 'nothing new from the aide');
  buttons[2].click();
  assert.deepEqual(opened, ['Sam Rayburn']);
});

test('only the aide: the list says how to start a conversation', () => {
  installDom();
  const rows = chatRows({ threads: { aide: [] }, reach: fixture.reach, record: fixture.record, seen: {} });
  const list = chatList({ rows, onOpen: () => {} });
  assert.equal(list.querySelectorAll('.rl-cl-row').length, 1);
  assert.match(words(list), /No conversations yet\. Start one from Contacts\./);
});

test('rows fit a phone and take colours from the tokens', () => {
  const css = read('css/p5-chatlist.css');
  assert.doesNotMatch(css, /contract stub/);
  assert.match(css, /\.rl-cl-row\s*\{/);
  assert.match(css, /\.rl-cl-preview\s*\{[^}]*(text-overflow|overflow-wrap)/);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b/);
});

test('a contact with no name on record still gets a row', () => {
  const rows = chatRows({ ...input, threads: { aide: [], '': [at('theirs', 'Unsigned.', '1941-10-12')] } });
  assert.equal(rows.length, 2);
  assert.equal(typeof rows[1].initials, 'string');
});
