// The own aim on screen (OWB), one test or more per rule: 1. while the window is open the third
// aim carries "Write your own" and the ladder of patterns, easiest first, each with its
// difficulty; 2. choosing one shows its blanks as pickers of the values the server sent, and the
// check's answer is shown before anything is stored; 3. setting it replaces the third aim's line,
// marked as the player's own, and after the window the control is gone; 4. the first-wake card
// names the choice once.
// Keeps: the client decides nothing. Mutant: a value offered that the server did not send.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, fire, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { stakesStrip, ownAimOf, resetOwn } = await import('../js/views/realism-stakes.js');
const { realismRoom } = await import('../js/views/realism-room.js');
const { firstWakeCard, firstWakeWords } = await import('../js/views/realism-firstwake.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const tick = () => new Promise((r) => setTimeout(r, 0));
const calls = [];

const STANDS = { reply: 'It stands: Take The Isle for Norra.', refused: false, aim: { stands: true, text: 'Take The Isle for Norra.', reasons: [] } };
const CANNOT = { reply: 'It cannot stand as filled.', refused: true, aim: { stands: false, text: null, reasons: ['Norra already holds it.', 'It is out of reach.'] } };

function wire(over = {}) {
  calls.length = 0;
  api.realism = async (action, body) => {
    calls.push([action, body]);
    return over[action] ?? STANDS;
  };
}

function strip(stakes = fixture.stakes, ownAim = fixture.own_aim, onAimSet = () => calls.push(['onset'])) {
  resetOwn();
  const doc = installDom();
  const el = stakesStrip(stakes, { ownAim, onAimSet });
  doc.body.append(el);
  return el;
}

const thirdRow = (el) => el.querySelectorAll('li.rl-aim')[2];
const ladderOf = (el) => el.querySelectorAll('button.rl-own-pattern');
const selectsOf = (el) => el.querySelectorAll('select');

async function openLadder(el) {
  fire(buttons(thirdRow(el), 'Write your own')[0], 'click');
  await tick();
}

test('1: the third aim carries Write your own and the ladder, easiest first, each with its difficulty', async () => {
  wire();
  const el = strip();
  assert.equal(buttons(thirdRow(el), 'Write your own').length, 1);
  assert.equal(buttons(el, 'Write your own').length, 1, 'one control, on the aim the server names');
  assert.equal(ladderOf(el).length, 0, 'the ladder is shut until asked for');
  await openLadder(el);
  const rungs = ladderOf(el).map(words);
  assert.equal(rungs.length, fixture.own_aim.patterns.length);
  assert.match(rungs[0], /Keep … at … or more\./);
  assert.match(rungs[0], /Difficulty 3/);
  assert.match(rungs[1], /Difficulty 4/);
  assert.match(rungs[2], /Your government would issue it/);
  assert.doesNotMatch(rungs[0], /government/);
  assert.match(words(thirdRow(el)), /It replaces: Hold the plain\./);
});

test('1: with no ladder from the server there is no control', () => {
  wire();
  const el = strip(fixture.stakes, null);
  assert.equal(buttons(el, 'Write your own').length, 0);
  assert.equal(ladderOf(el).length, 0);
});

test('2: a pattern\'s blanks are pickers of exactly the values the server sent', async () => {
  wire();
  const el = strip();
  await openLadder(el);
  fire(ladderOf(el)[0], 'click');
  const sels = selectsOf(el);
  assert.equal(sels.length, 2);
  const offered = sels.map((s) => s.querySelectorAll('option').map(words).filter((t) => t !== 'Choose…'));
  const sent = fixture.own_aim.patterns[0].blanks.map((b) => b.values.map((v) => v.label));
  assert.deepEqual(offered, sent);
  assert.equal(calls.length, 0, 'nothing is checked or stored by choosing a pattern');
});

test('2: the check answers before anything is stored, with the values the server sent', async () => {
  wire({ 'aim-check': STANDS });
  const el = strip();
  await openLadder(el);
  fire(ladderOf(el)[2], 'click');
  const [place] = selectsOf(el);
  place.value = '1';
  fire(place, 'change');
  await tick();
  assert.deepEqual(calls, [['aim-check', { key: 'take_ground', values: { place: '8G8AZ9CP6FGAQ40JKEY4K0V9BS' } }]]);
  assert.match(words(el), /It stands: Take The Isle for Norra\./);
  assert.equal(calls.filter(([a]) => a === 'aim-set').length, 0);
});

test('2: a numeric blank goes back as the number the server sent', async () => {
  wire();
  const el = strip();
  await openLadder(el);
  fire(ladderOf(el)[0], 'click');
  const [group, line] = selectsOf(el);
  group.value = '2';
  fire(group, 'change');
  line.value = '1';
  fire(line, 'change');
  await tick();
  assert.deepEqual(calls.at(-1), ['aim-check', { key: 'keep_support', values: { group: 'greys', line: 65 } }]);
});

test('2: a refusal shows its reasons and the aim cannot be set', async () => {
  wire({ 'aim-check': CANNOT });
  const el = strip();
  await openLadder(el);
  fire(ladderOf(el)[2], 'click');
  const [place] = selectsOf(el);
  place.value = '0';
  fire(place, 'change');
  await tick();
  const text = words(el);
  assert.match(text, /It cannot stand as filled\./);
  assert.match(text, /Norra already holds it\./);
  assert.match(text, /It is out of reach\./);
  const set = el.querySelectorAll('button.rl-own-set')[0];
  assert.equal(set.disabled, true);
});

test('2: nothing is checked until every blank is chosen', async () => {
  wire();
  const el = strip();
  await openLadder(el);
  fire(ladderOf(el)[0], 'click');
  const [group] = selectsOf(el);
  group.value = '0';
  fire(group, 'change');
  await tick();
  assert.equal(calls.length, 0);
});

test('3: setting stores through aim-set and reads the room again', async () => {
  wire({ 'aim-check': STANDS, 'aim-set': { ...STANDS, reply: 'Your own aim is set: Take The Isle for Norra.' } });
  const el = strip();
  await openLadder(el);
  fire(ladderOf(el)[2], 'click');
  const [place] = selectsOf(el);
  place.value = '1';
  fire(place, 'change');
  await tick();
  const set = el.querySelectorAll('button.rl-own-set')[0];
  assert.equal(set.disabled, false);
  fire(set, 'click');
  await tick();
  assert.deepEqual(calls.slice(-2), [['aim-set', { key: 'take_ground', values: { place: '8G8AZ9CP6FGAQ40JKEY4K0V9BS' } }], ['onset']]);
});

test('3: a set the server refuses shows its reasons and does not read the room again', async () => {
  wire({ 'aim-check': STANDS, 'aim-set': { reply: 'Your own aim was not set.', refused: true, aim: { stands: false, text: null, reasons: ['The window has closed.'] } } });
  const el = strip();
  await openLadder(el);
  fire(ladderOf(el)[2], 'click');
  const [place] = selectsOf(el);
  place.value = '0';
  fire(place, 'change');
  await tick();
  fire(el.querySelectorAll('button.rl-own-set')[0], 'click');
  await tick();
  assert.match(words(el), /The window has closed\./);
  assert.equal(calls.filter(([a]) => a === 'onset').length, 0);
});

test('3: an own aim set replaces the third line, marked as the player\'s own, and the control is gone', () => {
  wire();
  const stakes = structuredClone(fixture.stakes);
  stakes.aims[2] = { ...stakes.aims[2], text: 'Take The Isle for Norra.', source: 'player' };
  const el = strip(stakes, null);
  const row = thirdRow(el);
  assert.match(words(row), /Take The Isle for Norra\./);
  assert.match(words(row), /Your own/);
  assert.equal(row.querySelectorAll('.rl-aim-own').length, 1);
  assert.equal(buttons(el, 'Write your own').length, 0);
  assert.equal(el.querySelectorAll('.rl-aim-own').length, 1, 'only the aim the player wrote is marked');
});

test('4: the first-wake card names the own aim once', () => {
  const wake = { wake: 0, deadline: '1941-09-01T21:00:00+00:00', you_committed: false };
  const stakes = structuredClone(fixture.stakes);
  stakes.aims[2] = { ...stakes.aims[2], text: 'Take The Isle for Norra.', source: 'player' };
  const own = ownAimOf(stakes);
  assert.equal(own.aim, 3);
  const doc = installDom();
  const card = firstWakeCard(wake, { dismissed: null, onDismiss() {}, own });
  doc.body.append(card);
  const text = words(card);
  assert.equal(text.split('Take The Isle for Norra.').length - 1, 1);
  assert.match(text, /Your aim 3 is your own: Take The Isle for Norra\./);
  const plain = words(firstWakeCard(wake, { dismissed: null, onDismiss() {} }));
  assert.doesNotMatch(plain, /your own/);
  const w = firstWakeWords(wake, { own });
  assert.equal(w.steps.filter((s) => s.includes('your own')).length, 1);
  assert.equal(firstWakeWords(wake, {}).steps.some((s) => s.includes('your own')), false);
});

test('4: no own aim, no mention', () => {
  assert.equal(ownAimOf(fixture.stakes), null);
});

test('rules: the stylesheet draws the own aim from tokens only', () => {
  const css = readFileSync(new URL('../css/c-stakes.css', import.meta.url), 'utf8');
  assert.match(css, /\.rl-own\b/);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/);
});

function whole(rv) {
  const doc = installDom();
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
  globalThis.sessionStorage = globalThis.localStorage;
  api.realism = async () => ({});
  const view = { ...rv, documents: rv.listing, wake_tick: 1 };
  const me = { account: { handle: 'josh' }, game: { id: `g-${Math.random()}`, name: 'Autumn 1941', view: { realism: view, seat: { name: 'Franklin D. Roosevelt' } } } };
  const root = realismRoom({ me, refresh: async () => { calls.push(['refresh']); }, go: () => {} });
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  return root;
}

test('the room offers the control from the server\'s ladder, and draws none without one', () => {
  resetOwn();
  const wake = { wake: 0, deadline: '1941-09-01T21:00:00+00:00', committed: 0, humans: 1, you_committed: false, is_host: true, can_close: true };
  const on = whole({ ...fixture, wake });
  assert.ok(buttons(on, 'Write your own').length >= 1);
  const { own_aim: _gone, ...without } = fixture;
  const off = whole({ ...without, wake });
  assert.equal(buttons(off, 'Write your own').length, 0);
});
