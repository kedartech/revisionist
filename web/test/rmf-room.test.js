// Room fixes from the review: the game menu sends one call per click while one is out, and
// words offered to the order form wait for Replace when the player has typed a draft.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { api } from '../js/api.js';
import { buttons, fire, installDom, words } from './dom-fake.js';

installDom();
const { REPLACE_ASK, gameMenu, offerLine, offerOrder, settleOffer, uiFor } = await import('../js/views/realism-room.js');

/** A promise to settle by hand, so a test can look at the menu while the call is out. */
function deferred() {
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  return { promise, resolve };
}

/** The menu for a game, with `api.game` answering from `answer` and every call recorded. */
function menu(game, answer) {
  const doc = installDom();
  uiFor(`g-${Math.random()}`);
  const calls = [];
  const out = deferred();
  // the menu also reads the notice address when it opens: that read is tested in answer.test.js
  api.game = (action, body) => { if (action !== 'notice-address') calls.push([action, body]); return answer ?? out.promise; };
  const ctx = { go: () => {}, refresh: async () => {} };
  const [open, dialog] = gameMenu(game, ctx, { idle: () => true });
  doc.body.append(open, dialog);
  open.click();
  return { dialog, calls, out };
}

const HOST = { name: 'Autumn 1941', host: true, paused: false };
const settle = () => new Promise((r) => setTimeout(r, 0));

test('a second click on Pause while the first is out sends nothing', () => {
  const { dialog, calls } = menu(HOST);
  const [pause] = buttons(dialog, 'Pause');
  fire(pause, 'click');
  fire(pause, 'click');
  assert.deepEqual(calls.map(([a]) => a), ['pause']);
});

test('End the game clicked twice while the first is out sends one end', () => {
  const { dialog, calls } = menu(HOST);
  buttons(dialog, 'End game…')[0].click();
  const [end] = buttons(dialog, 'End the game');
  fire(end, 'click');
  fire(end, 'click');
  assert.deepEqual(calls.map(([a]) => a), ['end']);
});

test('Leave the game clicked twice while the first is out sends one leave', () => {
  const { dialog, calls } = menu({ name: 'Autumn 1941', host: false });
  buttons(dialog, 'Leave game…')[0].click();
  const [leave] = buttons(dialog, 'Leave the game');
  fire(leave, 'click');
  fire(leave, 'click');
  assert.deepEqual(calls.map(([a]) => a), ['leave']);
});

test('the menu buttons are held while a call is out and come back after a refusal', async () => {
  const { dialog, calls, out } = menu({ ...HOST, paused: true });
  buttons(dialog, 'Resume')[0].click();
  const held = ['Resume', 'End game…', 'Set'].map((label) => buttons(dialog, label)[0]);
  for (const b of held) assert.equal(b.disabled, true, words(b));
  assert.equal(buttons(dialog, 'Close')[0].disabled, false, 'Close stays usable');
  out.resolve({ refused: true, reply: 'Only the host can resume.' });
  await settle();
  for (const b of held) assert.equal(b.disabled, false, words(b));
  assert.match(words(dialog), /Only the host can resume\./);
  buttons(dialog, 'Resume')[0].click();
  assert.equal(calls.length, 2, 'a click after the refusal is sent');
});

test('the menu buttons come back after a failed call', async () => {
  const doc = installDom();
  uiFor('g-failed');
  api.game = async () => { throw new Error('The game server did not respond.'); };
  const [open, dialog] = gameMenu(HOST, { go: () => {}, refresh: async () => {} }, { idle: () => true });
  doc.body.append(open, dialog);
  open.click();
  buttons(dialog, 'Pause')[0].click();
  await settle();
  assert.equal(buttons(dialog, 'Pause')[0].disabled, false);
  assert.match(words(dialog), /did not respond/);
});

test('words offered over a typed draft wait, and the draft survives', () => {
  const state = { draft: { to: 'Harry Hopkins', channel: 'letter', text: 'Send the destroyers.' }, proposal: null, offer: null };
  assert.equal(offerOrder(state, 'Ask Congress to arm the merchant ships.'), false);
  assert.equal(state.draft.text, 'Send the destroyers.');
  assert.equal(state.offer, 'Ask Congress to arm the merchant ships.');
});

test('Keep mine drops the offer and keeps the draft; Replace puts the offered words in', () => {
  const typed = { to: 'Harry Hopkins', channel: 'letter', text: 'Send the destroyers.' };
  const kept = { draft: { ...typed }, proposal: null, offer: null };
  offerOrder(kept, 'Arm the merchant ships.');
  settleOffer(kept, false);
  assert.deepEqual(kept.draft, typed);
  assert.equal(kept.offer, null);
  const swapped = { draft: { ...typed }, proposal: { person: 'Harry Hopkins' }, offer: null };
  offerOrder(swapped, 'Arm the merchant ships.');
  settleOffer(swapped, true);
  assert.deepEqual(swapped.draft, { to: 'Harry Hopkins', channel: 'letter', text: 'Arm the merchant ships.' });
  assert.equal(swapped.proposal, null);
  assert.equal(swapped.offer, null);
});

test('with an empty draft the offered words go straight in, as before', () => {
  for (const draft of [null, { to: '', channel: '', text: '' }, { to: 'Cordell Hull', channel: 'cable', text: '  ' }]) {
    const state = { draft, proposal: { person: 'x' }, offer: null };
    assert.equal(offerOrder(state, 'Arm the merchant ships.'), true);
    assert.equal(state.draft.text, 'Arm the merchant ships.');
    assert.equal(state.draft.to, draft?.to ?? '');
    assert.equal(state.proposal, null);
    assert.equal(state.offer, null);
  }
});

test('the offer line asks once, with Replace and Keep mine', () => {
  installDom();
  const picked = [];
  const line = offerLine({ onReplace: () => picked.push('replace'), onKeep: () => picked.push('keep') });
  assert.equal(REPLACE_ASK, 'Replace your draft with this order?');
  assert.match(words(line), /^Replace your draft with this order\?/);
  buttons(line, 'Replace')[0].click();
  buttons(line, 'Keep mine')[0].click();
  assert.deepEqual(picked, ['replace', 'keep']);
});
