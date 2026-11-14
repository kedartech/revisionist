// Follow the thread: a redraw keeps the reader at the newest message when they were reading
// it, keeps their place when they had scrolled back, and a thread opens at its newest message.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { installDom } from './dom-fake.js';
import { h } from '../js/dom.js';
import { FOLLOW_SLACK, followNew, followThread } from '../js/views/realism-thread.js';

const HOPKINS = 'Harry Hopkins';

/** A thread box as the room reads it: scrollTop, scrollHeight, clientHeight. */
const box = (top, height, client = 400, thread = HOPKINS) => ({ thread, top, height, client });

test('a reader at the newest message stays at the newest message when the reply arrives', () => {
  assert.equal(followNew(box(600, 1000), box(0, 1300)), 900, 'exactly at the foot: the new foot');
  assert.equal(followNew(box(590, 1000), box(0, 1300)), 900, 'a few pixels short of the foot still counts as at the foot');
  assert.equal(followNew(box(600 - FOLLOW_SLACK, 1000), box(0, 1300)), 900, 'the edge of the slack still counts as at the foot');
});

test('a reader who scrolled back keeps their place when the reply arrives', () => {
  assert.equal(followNew(box(200, 1000), box(0, 1300)), 200);
  assert.equal(followNew(box(600 - FOLLOW_SLACK - 1, 1000), box(0, 1300)), 600 - FOLLOW_SLACK - 1, 'just past the slack is scrolled back');
  assert.equal(followNew(box(200, 1000), box(0, 500)), 100, 'a shorter thread clamps the place to its foot');
});

test('an empty thread counts as read to the foot', () => {
  assert.equal(followNew(box(0, 400), box(0, 400)), 0, 'nothing to scroll: the top');
  assert.equal(followNew(box(0, 400), box(0, 700)), 300, 'the first line in follows to the foot');
  assert.equal(followNew(null, box(0, 100)), 0, 'a short thread never scrolls past its top');
});

test('a thread opens at its newest message', () => {
  assert.equal(followNew(null, box(0, 1300)), 900, 'no saved place: the foot');
  assert.equal(followNew(box(200, 1000, 400, 'aide'), box(0, 1300)), 900, "another thread's place is not this one's");
});

test('the room keeps the place across redraws through one field on ui.chat', () => {
  installDom();
  const chat = { open: true, tab: 'chats', thread: HOPKINS, scroll: null };
  // each draw replaces the last one in the page, as a redraw does
  const draw = (height) => {
    const el = Object.assign(h('div', { class: 'rl-th' }), { scrollTop: 0, scrollHeight: height, clientHeight: 400 });
    document.body.replaceChildren(el);
    return el;
  };

  const first = draw(1000);
  followThread(chat, first);
  assert.equal(first.scrollTop, 600, 'first open lands at the foot');

  first.scrollTop = 100;
  first.dispatchEvent({ type: 'scroll' });
  assert.deepEqual(chat.scroll, box(100, 1000), 'scrolling back is saved on ui.chat');

  const second = draw(1300);
  followThread(chat, second);
  assert.equal(second.scrollTop, 100, 'the redraw keeps the place');

  Object.assign(first, { scrollTop: 0, scrollHeight: 0, clientHeight: 0 });
  first.dispatchEvent({ type: 'scroll' });
  assert.deepEqual(chat.scroll, box(100, 1000), 'a late scroll from the replaced thread is not the reader\'s place');

  second.scrollTop = 900;
  second.dispatchEvent({ type: 'scroll' });
  const third = draw(1500);
  followThread(chat, third);
  assert.equal(third.scrollTop, 1100, 'back at the foot, the next reply is followed');

  followThread(chat, null);
  assert.equal(chat.scroll, null, 'no thread drawn: the place is dropped, so the next open lands at the foot');
});
