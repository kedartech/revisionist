// The host hands a leader to a new player, from the game menu (HND): the leaders nobody
// plays, one invite code, and the words that the change comes at the next wake.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { api } from '../js/api.js';
import { buttons, fire, installDom, words } from './dom-fake.js';

installDom();
const { gameMenu, uiFor } = await import('../js/views/realism-room.js');

const settle = () => new Promise((r) => setTimeout(r, 0));
const HOST = { name: 'Autumn 1941', host: true, paused: false };
const GUEST = { name: 'Autumn 1941', host: false };
const LEADERS = [
  { key: 'e.goering', name: 'Hermann Goering', office: 'Reichsmarschall' },
  { key: 'e.ciano', name: 'Galeazzo Ciano', office: 'Foreign Minister of Italy' },
];
const LIST = { reply: '2 leader(s) can be handed to a new player.', refused: false, leaders: LEADERS };
const CODE = { reply: 'Send this code to the new player privately. It works once: they take up Hermann Goering from wake 4.', refused: false, code: 'ABCD-2345', from_wake: 4 };

/** The menu for `game`, with `api.game` answering from `answer(action, body)`; every call is recorded. */
function menu(game, answer) {
  const doc = installDom();
  uiFor(`g-${Math.random()}`);
  const calls = [];
  api.game = async (action, body) => {
    calls.push([action, body]);
    return answer(action, body);
  };
  const [open, dialog] = gameMenu(game, { go: () => {}, refresh: async () => {} }, { idle: () => true });
  doc.body.append(open, dialog);
  open.click();
  return { dialog, calls };
}

const section = (dialog) => dialog.querySelector('.rl-handover');
const handCalls = (calls) => calls.filter(([a]) => a === 'handover-list' || a === 'handover');
const easy = (action) => (action === 'handover-list' ? LIST : action === 'handover' ? CODE : { reply: '', refused: false });

test('the host\'s menu reads the leaders when it opens and lists each with its office', async () => {
  const { dialog, calls } = menu(HOST, easy);
  await settle();
  assert.deepEqual(handCalls(calls), [['handover-list', undefined]]);
  assert.ok(dialog.querySelectorAll('h3').map(words).includes('Hand a leader to a new player'));
  const rows = section(dialog).querySelectorAll('li');
  assert.equal(rows.length, 2);
  assert.match(words(rows[0]), /Hermann Goering/);
  assert.match(words(rows[0]), /Reichsmarschall/);
  assert.match(words(rows[1]), /Galeazzo Ciano/);
  assert.equal(buttons(rows[0], 'Hand to a new player').length, 1);
});

test('a menu shown to someone other than the host has no hand-over section and asks for no list', async () => {
  const { dialog, calls } = menu(GUEST, easy);
  await settle();
  assert.equal(section(dialog), null);
  assert.deepEqual(handCalls(calls), []);
  assert.equal(buttons(dialog, 'Hand to a new player').length, 0);
  assert.ok(!words(dialog).includes('Hand a leader'));
});

test('the section says the change takes effect at the next wake before and after a code', async () => {
  const { dialog } = menu(HOST, easy);
  await settle();
  assert.match(words(section(dialog)), /takes effect at the next wake/);
  buttons(dialog, 'Hand to a new player')[0].click();
  await settle();
  assert.match(words(section(dialog)), /takes effect at the next wake/);
});

test('Hand to a new player sends that leader\'s key to handover and shows the code and its reply', async () => {
  const { dialog, calls } = menu(HOST, easy);
  await settle();
  buttons(dialog, 'Hand to a new player')[1].click();
  await settle();
  assert.deepEqual(calls.at(-1), ['handover', { leader: 'e.ciano' }]);
  const code = dialog.querySelector('input[name="code"]');
  assert.equal(code.value, 'ABCD-2345');
  assert.ok(code.hasAttribute('readonly'));
  assert.equal(dialog.querySelector(`label[for="${code.id}"]`).textContent, 'Invite code');
  assert.match(words(section(dialog)), /they take up Hermann Goering from wake 4/);
});

test('each hand-over button is a named button: its leader is its description', async () => {
  const { dialog } = menu(HOST, easy);
  await settle();
  const [first] = buttons(dialog, 'Hand to a new player');
  assert.equal(first.getAttribute('type'), 'button');
  assert.equal(first.hasAttribute('tabindex'), false);
  const named = dialog.querySelector(`[id="${first.getAttribute('aria-describedby')}"]`);
  assert.match(words(named), /Hermann Goering/);
});

test('a refusal says why, shows no code and leaves the list to try again', async () => {
  const { dialog, calls } = menu(HOST, (a) => (a === 'handover'
    ? { reply: 'That leader is not free to hand over.', refused: true, code: 'LEAK-0000', from_wake: null }
    : easy(a)));
  await settle();
  buttons(dialog, 'Hand to a new player')[0].click();
  await settle();
  assert.match(words(section(dialog)), /That leader is not free to hand over\./);
  assert.equal(dialog.querySelector('input[name="code"]'), null);
  assert.equal(buttons(dialog, 'Hand to a new player').length, 2);
  buttons(dialog, 'Hand to a new player')[0].click();
  assert.equal(handCalls(calls).filter(([a]) => a === 'handover').length, 2);
});

test('with no leader free the section says so and offers no button', async () => {
  const { dialog } = menu(HOST, (a) => (a === 'handover-list'
    ? { reply: 'No leader is free to hand over.', refused: false, leaders: [] }
    : easy(a)));
  await settle();
  assert.match(words(section(dialog)), /No leader is free to hand over\./);
  assert.equal(section(dialog).querySelectorAll('li').length, 0);
  assert.equal(buttons(dialog, 'Hand to a new player').length, 0);
});

test('a refused or failed list says so and the rest of the menu still works', async () => {
  const refused = menu(HOST, (a) => (a === 'handover-list' ? { reply: 'The game is not in play.', refused: true, leaders: [] } : easy(a)));
  await settle();
  assert.match(words(section(refused.dialog)), /The game is not in play\./);
  const down = menu(HOST, (a) => { if (a === 'handover-list') throw new Error('The game server did not respond.'); return easy(a); });
  await settle();
  assert.match(words(section(down.dialog)), /did not respond/);
  assert.equal(buttons(down.dialog, 'Pause').length, 1);
  assert.equal(buttons(down.dialog, 'Pause')[0].disabled, false);
});

test('a second click while the first hand-over is out sends one call, and the buttons come back', async () => {
  let release;
  const slow = new Promise((r) => { release = r; });
  const { dialog, calls } = menu(HOST, (a) => (a === 'handover' ? slow : easy(a)));
  await settle();
  const [first] = buttons(dialog, 'Hand to a new player');
  fire(first, 'click');
  fire(first, 'click');
  assert.equal(handCalls(calls).filter(([a]) => a === 'handover').length, 1);
  assert.equal(first.disabled, true);
  assert.equal(buttons(dialog, 'Close')[0].disabled, false);
  release(CODE);
  await settle();
  assert.equal(buttons(dialog, 'Hand to a new player')[0].disabled, false);
});

test('a slow list does not hold the menu: Pause works while the list is out', async () => {
  const never = new Promise(() => {});
  const { dialog, calls } = menu(HOST, (a) => (a === 'handover-list' ? never : easy(a)));
  buttons(dialog, 'Pause')[0].click();
  assert.deepEqual(calls.map(([a]) => a), ['handover-list', 'notice-address', 'pause']);
});

test('the code is replaced, not stacked, when another leader is handed over', async () => {
  const { dialog } = menu(HOST, (a, body) => (a === 'handover'
    ? { ...CODE, code: body.leader === 'e.ciano' ? 'WXYZ-9876' : 'ABCD-2345' }
    : easy(a)));
  await settle();
  buttons(dialog, 'Hand to a new player')[0].click();
  await settle();
  buttons(dialog, 'Hand to a new player')[1].click();
  await settle();
  const codes = dialog.querySelectorAll('input[name="code"]');
  assert.equal(codes.length, 1);
  assert.equal(codes[0].value, 'WXYZ-9876');
});

test('after a code is shown, focus is on the code so the keyboard can copy it', async () => {
  const { dialog } = menu(HOST, easy);
  await settle();
  buttons(dialog, 'Hand to a new player')[0].click();
  await settle();
  assert.equal(document.activeElement, dialog.querySelector('input[name="code"]'));
});

test('the menu does not keep saying Working… once a hand-over is answered', async () => {
  const { dialog } = menu(HOST, easy);
  await settle();
  buttons(dialog, 'Hand to a new player')[0].click();
  assert.match(words(dialog.querySelector('.outcome')), /Working…/);
  await settle();
  assert.equal(words(dialog.querySelector('.outcome')), '');
});
