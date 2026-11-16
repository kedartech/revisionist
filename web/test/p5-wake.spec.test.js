// Spec for Train 2 unit H (contract K2), revised for unit Q3 (contract KQ): Run the day now
// is hidden in a game with one player while a wake is open. The unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import * as wakeView from '../js/views/realism-wake.js';
import {
  DONE_HINT, RUN_NOW, comeBackLine, commitCount, commitLabel, wakeHeader,
} from '../js/views/realism-wake.js';
import { statusStrip } from '../js/views/realism-status.js';
import { buttons, installDom, words } from './dom-fake.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

test('the commit button says done for today, then who is still out', () => {
  assert.equal(commitLabel({ committed: 0, humans: 2, you_committed: false }), 'Done for today');
  assert.equal(commitLabel({ committed: 1, humans: 3, you_committed: true }), 'Done, waiting on 2 of 3');
  assert.equal(commitLabel({ committed: 2, humans: 2, you_committed: true }), 'Done');
  assert.equal(commitLabel({ committed: 1, humans: 1, you_committed: true }), 'Done');
});

test('the count says players done', () => {
  assert.equal(commitCount({ committed: 1, humans: 2 }), '1 of 2 players done');
  assert.equal(commitCount({ committed: 0, humans: 1 }), '0 of 1 player done');
});

test('the hint and the host confirm', () => {
  assert.equal(DONE_HINT, 'The day runs when everyone is done, or at the close.');
  assert.deepEqual({ ...RUN_NOW }, {
    button: 'Run the day now',
    heading: 'Run the day now?',
    text: 'It runs with every order as it stands. Your aide plays anyone who is not done. This can take a minute.',
    cancel: 'Cancel',
    confirm: 'Run it',
  });
});

test('the views use the words, and the old ones are gone', () => {
  const src = read('js/views/realism-wake.js');
  const views = src.slice(src.indexOf('function commitControl'));
  assert.match(views, /commitLabel\(wake\)/);
  assert.match(views, /DONE_HINT/);
  assert.match(views, /RUN_NOW\.heading/);
  assert.match(views, /act\(RUNNING, 'close'/);
  assert.doesNotMatch(src, /Wake \$\{wake\.wake\}/, 'the header names no wake number');
  for (const old of ['Close the wake now', 'Close this wake?', 'Commit my orders', 'players committed']) assert.ok(!src.includes(old), old);
});

test('the host may run the day now with company, or to recover a game with no wake open', () => {
  const { canRunNow } = wakeView;
  assert.equal(typeof canRunNow, 'function');
  assert.equal(canRunNow({ can_close: true, humans: 2, deadline: '1941-10-20T21:00:00+00:00' }), true);
  assert.equal(canRunNow({ can_close: true, humans: 1, deadline: '1941-10-20T21:00:00+00:00' }), false);
  assert.equal(canRunNow({ can_close: true, humans: 1, deadline: null }), true);
  assert.equal(canRunNow({ can_close: false, humans: 3, deadline: null }), false);
  assert.equal(canRunNow({ can_close: false, humans: 1, deadline: null }), false);
});

test('the header shows Run the day now only when canRunNow says so', () => {
  installDom();
  const act = () => {};
  assert.equal(fixture.wake.humans, 2);
  assert.equal(fixture.wake_solo.humans, 1);
  assert.equal(buttons(wakeHeader(fixture.wake, { act }), RUN_NOW.button).length, 1);
  assert.equal(buttons(wakeHeader(fixture.wake_solo, { act }), RUN_NOW.button).length, 0);
  assert.equal(buttons(wakeHeader({ ...fixture.wake_solo, deadline: null }, { act }), RUN_NOW.button).length, 1);
  const src = read('js/views/realism-wake.js');
  assert.match(src.slice(src.indexOf('export function wakeHeader')), /canRunNow\(wake\)/);
});

// The "when you come back" line (CBL): what is due and when the wake closes, in the reader's zone.
const CLOSE = '1941-10-20T21:00:00+00:00'; // Monday 20 October, 9 pm in UTC
const seat = (over = {}, { orders = [], items = [] } = {}) => ({
  clock: { world_date: '1941-10-20' },
  record: { orders },
  agenda: { style: 'beginner', items },
  wake: { wake: 3, deadline: CLOSE, committed: 0, humans: 2, you_committed: false, is_host: false, can_close: false, ...over },
});
const order = (holder, due, extra = {}) => ({ id: holder, holder, to: holder, due, moving: true, ...extra });
const matter = (kind, issuer, deadline) => ({ id: `${kind}${issuer}`, kind, issuer, deadline, text: 'x' });

test('before Done: up to the soonest answers due, when the wake closes, and that the aide plays', () => {
  const rv = seat({}, {
    orders: [order('Harold R. Stark', '21 October 1941')],
    items: [matter('Order', 'Franklin D. Roosevelt', '26 October 1941')],
  });
  assert.equal(comeBackLine(rv, 'UTC'),
    'When you come back: Harold R. Stark\'s answer due 21 October 1941; the order from Franklin D. Roosevelt due 26 October 1941.'
    + ' The wake closes by Monday 20 October, 9 pm; if you have not pressed Done by then, your aide plays your seat.');
});

test('three dates at most, soonest first, from the record and the mandates together', () => {
  const rv = seat({}, {
    orders: [order('A', '30 October 1941'), order('B', '22 October 1941'), order('C', null), order('D', '1941-10-24', { moving: true })],
    items: [matter('Crisis', null, '23 October 1941'), matter('Order', 'E', null)],
  });
  const line = comeBackLine(rv, 'UTC');
  const dues = [...line.matchAll(/due (\d+ October 1941)/g)].map((m) => m[1]);
  assert.deepEqual(dues, ['22 October 1941', '23 October 1941', '24 October 1941']);
  assert.doesNotMatch(line, /30 October/);
  assert.match(line, /the crisis due 23 October 1941/);
});

test('an order that has settled or has no answer day adds no date; with none, the line says nothing is due', () => {
  const rv = seat({}, { orders: [order('A', '22 October 1941', { moving: false }), order('B', null)] });
  assert.match(comeBackLine(rv, 'UTC'), /^When you come back: nothing is due\. The wake closes by /);
});

test('after Done: the same dates, then when the next wake opens, and no aide clause', () => {
  const rv = seat({ you_committed: true, committed: 1 }, { orders: [order('Stark', '21 October 1941')] });
  assert.equal(comeBackLine(rv, 'UTC'),
    'When you come back: Stark\'s answer due 21 October 1941. The next wake opens by Monday 20 October, 9 pm.');
});

test('the close is read in the reader\'s zone', () => {
  const rv = seat({ deadline: '2026-11-03T02:00:00Z' });
  assert.match(comeBackLine(rv, 'America/New_York'), /closes by Monday 2 November, 9 pm;/);
  assert.match(comeBackLine(rv, 'Asia/Tokyo'), /closes by Tuesday 3 November, 11 am;/);
});

test('no wake open, no line', () => {
  assert.equal(comeBackLine(seat({ deadline: null }), 'UTC'), null);
});

test('the line keeps to counts: no other seat\'s state, and nothing about who is away', () => {
  const rv = seat({ committed: 2, humans: 3 }, { orders: [order('Stark', '21 October 1941')] });
  assert.doesNotMatch(comeBackLine(rv, 'UTC'), /\d of \d|players?\b|away|absent|waiting on|committed|everyone/i);
  const after = seat({ committed: 2, humans: 3, you_committed: true }, { orders: [order('Stark', '21 October 1941')] });
  assert.doesNotMatch(comeBackLine(after, 'UTC'), /\d of \d|players?\b|away|absent|waiting on|committed|everyone/i);
});

test('the strip carries the line, after the date and the countdown, before and after Done', () => {
  installDom();
  const act = () => {};
  const deadline = new Date(Date.now() + 3 * 3600_000).toISOString();
  for (const you_committed of [false, true]) {
    const rv = { ...seat({ deadline, you_committed, committed: you_committed ? 1 : 0 }), documents: fixture.listing };
    const strip = statusStrip(rv, { tab: 'desk' }, { act });
    const line = strip.querySelector('.rl-comeback');
    assert.ok(line, 'a .rl-comeback paragraph');
    assert.equal(line.tagName, 'P');
    assert.match(words(line), /^When you come back: /);
    assert.equal(words(line).includes('your aide plays your seat'), !you_committed);
    assert.equal(words(line).includes('The next wake opens by'), you_committed);
    const at = (el) => strip.children.indexOf(el);
    assert.ok(at(line) > at(strip.querySelector('.rl-date')), 'read after the date');
    assert.ok(at(line) > at(strip.querySelector('.rl-countdown')), 'read after the countdown');
    assert.equal(at(line), strip.children.length - 1, 'last in reading order, so the keyboard order matches the picture');
  }
  const idle = statusStrip({ ...seat({ deadline: null }), documents: fixture.listing }, { tab: 'desk' }, { act });
  assert.equal(idle.querySelector('.rl-comeback'), null, 'no line while no wake is open');
});

test('the line sits on its own row in the strip', () => {
  assert.match(read('css/p5-wake.css'), /\.rl-comeback\s*\{[^}]*flex-basis:\s*100%/);
});
