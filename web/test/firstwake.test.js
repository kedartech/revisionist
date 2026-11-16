// The first-wake card: three steps shown while wake 0 is open and the seat has not pressed
// Done. The server's wake header decides; the card keeps no browser storage.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { realismRoom, uiFor } = await import('../js/views/realism-room.js');
const { FIRST_WAKE, firstWakeCard, firstWakeDue } = await import('../js/views/realism-firstwake.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');

const open0 = { wake: 0, deadline: '1941-09-01T21:00:00+00:00', committed: 0, humans: 1, you_committed: false, is_host: true, can_close: true };

/** The whole room for a fresh game whose wake header is `wake`; `touched` lists storage calls. */
function room(wake, id = `g-${Math.random()}`) {
  const doc = installDom();
  const touched = [];
  globalThis.localStorage = {
    getItem: (k) => { touched.push(['get', k]); return null; },
    setItem: (k) => { touched.push(['set', k]); },
    removeItem: (k) => { touched.push(['remove', k]); },
  };
  globalThis.sessionStorage = globalThis.localStorage;
  api.realism = async () => ({});
  const rv = { ...fixture, documents: fixture.listing, wake_tick: 1, wake };
  const me = { account: { handle: 'josh' }, game: { id, name: 'Autumn 1941', view: { realism: rv, seat: { name: 'Franklin D. Roosevelt' } } } };
  const root = realismRoom({ me, refresh: async () => {}, go: () => {} });
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  return { root, id, touched, doc };
}

const key = (el, k) => el.dispatchEvent({ type: 'keydown', key: k, target: null, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() {} });

test('the card is due while wake 0 is open and the seat has not pressed Done', () => {
  assert.equal(firstWakeDue(open0, null), true);
});

test('the card is not due once the seat has pressed Done', () => {
  assert.equal(firstWakeDue({ ...open0, you_committed: true }, null), false);
  assert.equal(firstWakeDue({ ...open0, committed: 1, you_committed: true }, null), false);
});

test('the card is not due in a later wake, with no wake open, or with no wake header', () => {
  assert.equal(firstWakeDue({ ...open0, wake: 1 }, null), false);
  assert.equal(firstWakeDue({ ...open0, wake: 3 }, null), false);
  assert.equal(firstWakeDue({ ...open0, deadline: null }, null), false);
  assert.equal(firstWakeDue(undefined, null), false);
  assert.equal(firstWakeDue(null, null), false);
});

test('dismissing hides the card for that wake only', () => {
  assert.equal(firstWakeDue(open0, 0), false);
  assert.equal(firstWakeDue(open0, null), true);
  assert.equal(firstWakeDue(open0, 5), true, 'a dismissal made for another wake does not carry over');
});

test('the card gives the three steps in the plan\'s words', () => {
  const card = firstWakeCard(open0, { dismissed: null, onDismiss: () => {} });
  assert.deepEqual(FIRST_WAKE.steps, [
    'Read your aims, pinned on the Board.',
    'Choose an option for each matter.',
    'Press Done; come back when the notice says.',
  ]);
  const items = card.querySelectorAll('ol li').map(words);
  assert.deepEqual(items, FIRST_WAKE.steps);
  assert.equal(card.querySelectorAll('ol').length, 1);
});

test('the card is a labelled region with a heading', () => {
  const card = firstWakeCard(open0, { dismissed: null, onDismiss: () => {} });
  assert.equal(card.getAttribute('role'), 'region');
  assert.equal(card.getAttribute('aria-label'), FIRST_WAKE.label);
  assert.equal(words(card.querySelector('h2')), FIRST_WAKE.heading);
});

test('no card when it is not due', () => {
  assert.equal(firstWakeCard({ ...open0, you_committed: true }, { dismissed: null, onDismiss: () => {} }), null);
  assert.equal(firstWakeCard(open0, { dismissed: 0, onDismiss: () => {} }), null);
});

test('the Dismiss button calls onDismiss', () => {
  let n = 0;
  const card = firstWakeCard(open0, { dismissed: null, onDismiss: () => { n += 1; } });
  const [btn] = buttons(card, FIRST_WAKE.dismiss);
  assert.ok(btn, 'a Dismiss button');
  assert.equal(btn.getAttribute('type'), 'button');
  btn.click();
  assert.equal(n, 1);
});

test('Escape inside the card dismisses it from the keyboard; other keys do not', () => {
  let n = 0;
  const card = firstWakeCard(open0, { dismissed: null, onDismiss: () => { n += 1; } });
  key(card, 'Tab');
  key(card, 'Enter');
  assert.equal(n, 0);
  key(card, 'Escape');
  assert.equal(n, 1);
});

test('the room shows the card on the Board and on the Desk in wake 0', () => {
  const { root } = room(open0);
  assert.ok(root.querySelector('.rl-firstwake'), 'the card on the Board');
  buttons(root.querySelector('.rl-viewswitch'), 'Desk')[0].click();
  assert.ok(root.querySelector('.rl-firstwake'), 'the card on the Desk');
});

test('the room shows no card after Done, in a later wake, or with no wake open', () => {
  assert.equal(room({ ...open0, committed: 1, you_committed: true }).root.querySelector('.rl-firstwake'), null);
  assert.equal(room({ ...open0, wake: 1 }).root.querySelector('.rl-firstwake'), null);
  assert.equal(room({ ...open0, deadline: null }).root.querySelector('.rl-firstwake'), null);
});

test('the room keeps the card away after Dismiss, through a redraw, and hands focus on', () => {
  const { root, id, doc } = room(open0);
  const [btn] = buttons(root.querySelector('.rl-firstwake'), FIRST_WAKE.dismiss);
  btn.click();
  assert.equal(root.querySelector('.rl-firstwake'), null);
  assert.equal(uiFor(id).firstWakeOff, 0);
  buttons(root.querySelector('.rl-viewswitch'), 'Desk')[0].click();
  assert.equal(root.querySelector('.rl-firstwake'), null, 'still gone after a redraw');
  assert.ok(doc.activeElement.classList.contains('rl-pin'), 'focus lands on the pin');
});

test('the card is the first thing after the strips and before the view switch', () => {
  const { root } = room(open0);
  const kids = [...root.children];
  const at = kids.findIndex((el) => el.classList.contains('rl-firstwake'));
  const sw = kids.findIndex((el) => el.classList.contains('rl-viewswitch'));
  assert.ok(at > 0, 'the card is in the room');
  assert.equal(at + 1, sw, 'the switch follows the card');
});

test('the card keeps no browser storage: showing and dismissing it write nothing', () => {
  const { root, touched } = room(open0);
  assert.deepEqual(touched.filter(([op]) => op !== 'get'), [], 'no write while the room draws');
  const before = touched.length;
  buttons(root.querySelector('.rl-firstwake'), FIRST_WAKE.dismiss)[0].click();
  assert.deepEqual(touched.slice(before).filter(([op]) => op !== 'get'), [], 'no write on Dismiss');
  assert.deepEqual(touched.filter(([, k]) => /first/i.test(k)), [], 'no key of its own');
  assert.doesNotMatch(read('js/views/realism-firstwake.js'), /[sS]torage|cookie|indexedDB/);
});

test('the page links the card\'s stylesheet, which uses tokens only', () => {
  assert.match(read('index.html'), /<link rel="stylesheet" href="\/css\/p5-firstwake\.css">/);
  const css = read('css/p5-firstwake.css');
  assert.match(css, /\.rl-firstwake\b/);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b/);
});
