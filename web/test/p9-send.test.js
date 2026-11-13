// Clear on send: the composer empties when a message goes, the words wait in the pending
// bubble, and a refused or failed send gives them back to the thread they were written in.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { installDom, words } from './dom-fake.js';
import { chatDock } from '../js/views/realism-chat.js';
import { beginSend, endSend } from '../js/views/realism-room.js';
import { threadItems } from '../js/views/realism-thread.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const fixture = JSON.parse(readFileSync(join(WEB, 'test/fixtures/realism-seat.json'), 'utf8'));

const HOPKINS = 'Harry Hopkins';
const ASKED = 'Will Moscow hold?';

const threads = () => ({
  aide: threadItems({ person: 'aide', help: fixture.help }),
  [HOPKINS]: threadItems({ person: HOPKINS, counsel: fixture.counsel, documents: fixture.listing }),
});

/** One draw of the dock with `thread` open, fed from the room's `ui` as the room feeds it. */
const draw = (ui, thread) => {
  installDom();
  const node = chatDock({
    state: { open: true, tab: 'chats', thread }, onState: () => {}, threads: threads(), seen: {},
    reach: fixture.reach, record: fixture.record, pending: ui.pending, drafts: ui.drafts, brief: null,
    ask: () => {}, consult: () => {}, onOpen: () => {}, useDraft: () => {}, contactsTab: null,
  });
  return { node, composer: node.querySelector('.rl-th-input') };
};

const typed = () => ({ busy: null, pending: null, error: null, drafts: { [HOPKINS]: ASKED, aide: 'And the bill?' } });

test('a send empties the composer on the next draw and the words wait in the pending bubble', () => {
  const ui = typed();
  assert.equal(draw(ui, HOPKINS).composer.value, ASKED, 'the typed words are in the composer before the send');
  assert.equal(beginSend(ui, HOPKINS, ASKED), true);
  assert.equal(ui.drafts[HOPKINS], undefined, 'the thread keeps no draft while the message is out');
  assert.deepEqual(ui.pending, { thread: HOPKINS, text: ASKED });
  const { node, composer } = draw(ui, HOPKINS);
  assert.equal(composer.value, '', 'the composer is empty while the answer is awaited');
  assert.equal(composer.readOnly, true);
  assert.match(words(node.querySelector('.rl-th')), /Will Moscow hold\?/, 'the pending bubble shows what was sent');
  assert.equal(ui.drafts.aide, 'And the bill?', 'another thread keeps its draft');
});

test('a send that does not start keeps the words in the composer', () => {
  const busy = { ...typed(), busy: 'Running the day…' };
  assert.equal(beginSend(busy, HOPKINS, ASKED), false);
  assert.equal(draw(busy, HOPKINS).composer.value, ASKED, 'not while the room is busy');
  const out = typed();
  beginSend(out, 'aide', 'And the bill?');
  assert.equal(beginSend(out, HOPKINS, ASKED), false);
  assert.equal(draw(out, HOPKINS).composer.value, ASKED, 'not while another message is out');
});

test('an answered send leaves the composer empty', () => {
  const ui = typed();
  beginSend(ui, HOPKINS, ASKED);
  endSend(ui, { refused: false, reply: 'Harry Hopkins has answered.' });
  assert.equal(ui.pending, null);
  const { composer } = draw(ui, HOPKINS);
  assert.equal(composer.value, '');
  assert.equal(composer.readOnly, false);
  assert.equal(ui.error, null);
});

test('a refused send gives the words back to the composer and says why', () => {
  const ui = typed();
  beginSend(ui, HOPKINS, ASKED);
  endSend(ui, { refused: true, reply: 'Harry Hopkins did not answer.' });
  const { composer } = draw(ui, HOPKINS);
  assert.equal(composer.value, ASKED);
  assert.equal(composer.readOnly, false);
  assert.equal(ui.error, 'Harry Hopkins did not answer.');
});

test('a failed send gives the words back to the composer and says why', () => {
  const ui = typed();
  beginSend(ui, 'aide', 'And the bill?');
  assert.equal(draw(ui, 'aide').composer.value, '');
  endSend(ui, { error: 'The model cannot be reached just now.' });
  assert.equal(draw(ui, 'aide').composer.value, 'And the bill?');
  assert.equal(ui.drafts[HOPKINS], ASKED, 'the other thread keeps its draft');
  assert.equal(ui.error, 'The model cannot be reached just now.');
});

test('a thread switch while the message is out loses neither the words nor the other draft', () => {
  const ui = typed();
  beginSend(ui, HOPKINS, ASKED);
  const away = draw(ui, 'aide');
  assert.equal(away.composer.value, 'And the bill?', 'the other thread shows its own draft');
  assert.equal(away.composer.readOnly, false, 'the other thread can still be written in');
  ui.drafts = { ...ui.drafts, aide: 'And the bill, by Friday?' };
  const back = draw(ui, HOPKINS);
  assert.equal(back.composer.value, '');
  assert.match(words(back.node.querySelector('.rl-th')), /Will Moscow hold\?/, 'the pending bubble is still there');
  endSend(ui, { error: 'The model cannot be reached just now.' });
  assert.equal(draw(ui, HOPKINS).composer.value, ASKED, 'the words return to the thread they were written in');
  assert.equal(draw(ui, 'aide').composer.value, 'And the bill, by Friday?', 'what was typed elsewhere meanwhile is kept');
});
