// Wave M wiring (contract KM): the room builds the threads from the data the server sends, the
// dock reaches each unit, every stub marker is gone and every stylesheet is linked. Red until
// the wave lands. Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { installDom, words } from './dom-fake.js';
import { chatDock } from '../js/views/realism-chat.js';
import { threadItems } from '../js/views/realism-thread.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

const UNITS = {
  M1: ['js/views/realism-launcher.js', 'css/p5-launcher.css'],
  M2: ['js/views/realism-thread.js', 'css/p5-thread.css'],
  M3: ['js/views/realism-typing.js', 'css/p5-typing.css'],
  M4: ['js/views/realism-chatlist.js', 'css/p5-chatlist.css'],
  M5: ['js/views/realism-contacts.js', 'css/p5-contacts.css'],
};

const threads = () => {
  const out = { aide: threadItems({ person: 'aide', help: fixture.help }) };
  for (const name of ['Harry Hopkins', 'Sam Rayburn', 'Harold R. Stark']) {
    out[name] = threadItems({ person: name, counsel: fixture.counsel, documents: fixture.listing });
  }
  return out;
};

const dock = (state, over = {}) => {
  installDom();
  return chatDock({
    state, onState: () => {}, threads: threads(), seen: {}, reach: fixture.reach, record: fixture.record,
    pending: null, drafts: {}, brief: null, ask: () => {}, consult: () => {}, onOpen: () => {},
    useDraft: () => {}, contactsTab: null, ...over,
  });
};

test('the room builds every thread from the server data and hands the dock what it needs', () => {
  const room = read('js/views/realism-room.js');
  for (const call of [
    /threadItems\(\{ person: 'aide', help: rv\.help \?\? \[\] \}\)/,
    /threadItems\(\{ person: name, counsel: rv\.counsel \?\? \[\], documents: rv\.documents \}\)/,
    /threads: all,/,
    /reach: rv\.reach,/,
    /record: rv\.record,/,
    /pending: ui\.pending,/,
    /drafts: ui\.drafts,/,
    /threadCounts\(all\)/,
  ]) assert.match(room, call);
  assert.doesNotMatch(read('js/views/realism.js'), /export function (bubble|counselThread|helpThread)\b/);
});

test('closed: the launcher with the unread count from every thread', () => {
  const node = dock({ open: false, tab: 'chats', thread: null });
  const btn = node.querySelector('.rl-msgr-btn');
  assert.ok(btn, 'the launcher');
  assert.equal(btn.getAttribute('aria-expanded'), 'false');
  assert.equal(words(btn.querySelector('.rl-msgr-count')), '6 unread');
});

test('open on Chats: a row per conversation, the aide first', () => {
  const node = dock({ open: true, tab: 'chats', thread: null });
  const rows = node.querySelectorAll('.rl-cl-row');
  assert.equal(rows.length, 3);
  assert.match(words(rows[0]), /Your aide/);
});

test('a thread with someone outside the inner circle, a message going out and the reply being written', () => {
  const node = dock({ open: true, tab: 'chats', thread: 'Harold R. Stark' },
    { pending: { thread: 'Harold R. Stark', text: 'And the third division?' } });
  assert.match(words(node.querySelector('.rl-th-head')), /Chief of Naval Operations/);
  assert.match(words(node), /A message changes nothing in the world and files no order\./);
  assert.equal(node.querySelectorAll('.rl-th-bubble.mine').length, 3);
  assert.match(words(node.querySelector('.rl-typing')), /Harold R\. Stark is writing/);
  assert.equal(node.querySelector('.rl-th-compose textarea').readOnly, true);
});

test('words typed in a thread reach the room under that thread, and the room keeps them without a redraw', () => {
  const typed = [];
  const node = dock({ open: true, tab: 'chats', thread: 'Harry Hopkins' }, { onType: (k, t) => typed.push([k, t]) });
  const ta = node.querySelector('.rl-th-compose textarea');
  ta.value = 'And the tanks';
  ta.dispatchEvent({ type: 'input', stopPropagation() {} });
  assert.deepEqual(typed, [['Harry Hopkins', 'And the tanks']]);
  assert.match(read('js/views/realism-room.js'), /onType: \(key, text\) => \{ ui\.drafts = \{ \.\.\.ui\.drafts, \[key\]: text \}; \}/);
});

test('every unit has replaced its contract stub', () => {
  for (const [unit, files] of Object.entries(UNITS)) {
    for (const f of files) assert.doesNotMatch(read(f), /contract stub/, `${unit}: ${f}`);
  }
});

test('every unit stylesheet is linked from the page', () => {
  const page = read('index.html');
  for (const [, css] of Object.values(UNITS)) assert.match(page, new RegExp(`href="/${css.replace('.', '\\.')}"`), css);
});
