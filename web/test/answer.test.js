// Answering another seat's request, writing to a leader who answers in person, and the
// notice address in the game menu (RQC). Run: node --test web/test/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { api } from '../js/api.js';
import { buttons, fire, installDom, words } from './dom-fake.js';

installDom();
const { answerItems, needsAnswer } = await import('../js/views/realism-answer.js');
const { requestChoices } = await import('../js/views/realism-requests.js');
const { threadView } = await import('../js/views/realism-thread.js');
const { chatDock } = await import('../js/views/realism-chat.js');
const { endSend, gameMenu, letterDraft, uiFor } = await import('../js/views/realism-room.js');

const request = (extra = {}) => ({
  id: 'p.req1', kind: 'Request', issuer: 'Franklin D. Roosevelt',
  text: 'Ask the Prime Minister to take fifty old destroyers (50 ships)',
  issued: '9 October 1941', deadline: '11 October 1941', cause: null, options: [], plan: [], ...extra,
});
const crisis = { id: 'c1', kind: 'Crisis', issuer: null, text: 'Convoy lost.', issued: '1 October 1941', deadline: '15 October 1941', cause: null,
  options: [{ label: 'Go', to: null, risk: '', historical: false, pick: 'p-c1', taken: false }], plan: [] };

/** The section for `items`, with every `act` call recorded. */
function section(items, style = 'beginner') {
  const doc = installDom();
  const calls = [];
  const act = (...args) => calls.push(args);
  const node = needsAnswer({ style, items, initiative: [] }, { act, today: '9 October 1941' });
  doc.body.append(node);
  return { node, calls };
}

for (const style of ['free', 'guided', 'beginner']) {
  test(`a request is answered with Accept or Decline under the ${style} style`, () => {
    assert.deepEqual(requestChoices(style, request()), { kind: 'request', options: [] });
    assert.deepEqual(answerItems({ style, items: [request()], initiative: [] })[0].choices, { kind: 'request', options: [] });
  });
}

test('a desk matter keeps its own choices', () => {
  assert.equal(requestChoices('beginner', crisis).kind, 'options');
  assert.equal(requestChoices('free', crisis).kind, 'none');
});

test('Accept posts the answer true and Decline posts false, for that request', () => {
  const { node, calls } = section([request()]);
  buttons(node, 'Accept')[0].click();
  buttons(node, 'Decline')[0].click();
  assert.equal(calls.length, 2);
  assert.deepEqual(calls.map(([, action, body]) => [action, body]), [
    ['answer', { item: 'p.req1', accept: true }],
    ['answer', { item: 'p.req1', accept: false }],
  ]);
});

test('each request answers for its own id', () => {
  const { node, calls } = section([request({ id: 'p.a' }), request({ id: 'p.b', issuer: 'Cordell Hull' })]);
  buttons(node, 'Accept')[1].click();
  assert.deepEqual(calls[0].slice(1), ['answer', { item: 'p.b', accept: true }]);
});

test('a request shows who asks, its terms and its due day', () => {
  const { node } = section([request()]);
  const text = words(node);
  assert.match(text, /Request from Franklin D\. Roosevelt/);
  assert.match(text, /fifty old destroyers \(50 ships\)/);
  assert.match(text, /Due by 11 October 1941/);
  assert.match(text, /2 days left/);
});

test('the buttons say the answer goes out on the due day and can be changed until then', () => {
  const { node } = section([request()]);
  assert.match(words(node), /Your answer goes out on the day it is due; you can change it until then\./);
  const hint = node.querySelector('.rl-ans-when');
  for (const b of [buttons(node, 'Accept')[0], buttons(node, 'Decline')[0]]) {
    assert.equal(b.getAttribute('aria-describedby'), hint.id);
    assert.equal(b.disabled, false);
  }
});

test('a request the seat has answered says so, and both answers stay so it can be changed', () => {
  const { node, calls } = section([request({ cause: 'You have agreed to it.' })]);
  assert.equal(words(node.querySelector('.rl-ans-given')), 'You have agreed to it.');
  buttons(node, 'Decline')[0].click();
  assert.deepEqual(calls.map(([, action, body]) => [action, body]), [['answer', { item: 'p.req1', accept: false }]]);
});

test('a request not yet answered has no answer line', () => {
  const { node } = section([request()]);
  assert.equal(node.querySelector('.rl-ans-given'), null);
});

test('requests come before desk matters and the Choose button stays on a desk matter', () => {
  const { node } = section([crisis, request()]);
  const text = words(node);
  assert.ok(text.indexOf('Request from Franklin D. Roosevelt') < text.indexOf('Convoy lost.'));
  assert.equal(buttons(node, 'Choose').length, 1);
  assert.equal(buttons(node, 'Accept').length, 1);
});

test('the keyboard path: the two answers are buttons that a key press reaches, Accept first', () => {
  const { node } = section([request()]);
  const order = node.querySelectorAll('button').map(words);
  assert.deepEqual(order, ['Accept', 'Decline']);
  for (const b of node.querySelectorAll('button')) assert.equal(b.getAttribute('type'), 'button');
});

// --- a decision held for another seat -------------------------------------------------

const decision = (extra = {}) => request({
  id: 'p.dec1', kind: 'Decision', text: 'Release the convoy escort', actions: ['pass', 'expedite', 'stall', 'leak', 'refuse'], ...extra,
});
const DECISION_LINE = 'Your decision is kept until it is due. You can change it until then.';

test('a held decision draws one button per allowed action, labelled as the room labels steps', () => {
  const { node } = section([decision({ actions: ['pass', 'stall', 'refuse'] })]);
  assert.deepEqual(node.querySelectorAll('button').map(words), ['Pass it on', 'Stall', 'Refuse']);
  assert.equal(buttons(node, 'Accept').length, 0);
  assert.equal(buttons(node, 'Decline').length, 0);
});

test('a decision button posts the step action for that decision, with the item id as the order', () => {
  const { node, calls } = section([decision()]);
  buttons(node, 'Stall')[0].click();
  buttons(node, 'Leak')[0].click();
  assert.deepEqual(calls.map(([label, action, body]) => [label, action, body]), [
    ['Recording your decision…', 'step', { order_id: 'p.dec1', action: 'stall', params: {} }],
    ['Recording your decision…', 'step', { order_id: 'p.dec1', action: 'leak', params: {} }],
  ]);
});

test('a held decision says the choice is kept until it is due and can be changed, never to write an order', () => {
  const { node } = section([decision()]);
  const text = words(node);
  assert.ok(text.includes(DECISION_LINE));
  assert.ok(!text.includes('Answer it with an order of your own.'));
  assert.ok(!text.includes('Your answer goes out'));
});

test('a chosen decision shows its cause above the buttons, which stay', () => {
  const { node, calls } = section([decision({ cause: 'You have chosen to stall.' })]);
  assert.equal(words(node.querySelector('.rl-ans-given')), 'You have chosen to stall.');
  const labels = node.querySelectorAll('button').map(words);
  assert.equal(labels.length, 5);
  buttons(node, 'Refuse')[0].click();
  assert.deepEqual(calls[0].slice(1), ['step', { order_id: 'p.dec1', action: 'refuse', params: {} }]);
});

test('a decision not yet chosen has no choice line', () => {
  assert.equal(section([decision()]).node.querySelector('.rl-ans-given'), null);
});

test('a held decision from an older payload draws the line and no buttons', () => {
  const { actions, ...older } = decision();
  const { node } = section([older]);
  assert.equal(node.querySelectorAll('button').length, 0);
  assert.ok(words(node).includes(DECISION_LINE));
  assert.ok(!words(node).includes('Answer it with an order of your own.'));
});

test('the keyboard path: each decision button is a typed button tied to the line, in the offered order', () => {
  const { node } = section([decision()]);
  const all = node.querySelectorAll('button');
  assert.deepEqual(all.map(words), ['Pass it on', 'Expedite', 'Stall', 'Leak', 'Refuse']);
  const hint = node.querySelector('.rl-ans-when');
  for (const b of all) {
    assert.equal(b.getAttribute('type'), 'button');
    assert.equal(b.getAttribute('aria-describedby'), hint.id);
    assert.equal(b.disabled, false);
  }
});

test('a decision and a request keep their own buttons side by side', () => {
  const { node } = section([request(), decision({ actions: ['pass'] })]);
  assert.deepEqual(node.querySelectorAll('button').map(words), ['Accept', 'Decline', 'Pass it on']);
});

// --- counsel that points to the letter thread ------------------------------------------

const REFUSAL = 'Winston Churchill answers in person. Write to them; your letter reaches their desk.';
const fresh = () => ({
  chat: { open: false, tab: 'chats', thread: null }, letters: [], pending: { thread: 'Winston Churchill', text: 'Will you send ships?' },
  drafts: {}, error: null,
});

test('a counsel refusal carrying thread opens that leader\'s thread, keeps the words and says why', () => {
  const state = fresh();
  endSend(state, { refused: true, reply: REFUSAL, thread: 'Winston Churchill' });
  assert.deepEqual(state.chat, { open: true, tab: 'chats', thread: 'Winston Churchill' });
  assert.deepEqual(state.letters, ['Winston Churchill']);
  assert.equal(state.drafts['Winston Churchill'], 'Will you send ships?');
  assert.equal(state.error, REFUSAL);
});

test('a refusal with no thread leaves the messenger where it was', () => {
  const state = fresh();
  endSend(state, { refused: true, reply: 'Churchill did not answer.' });
  assert.deepEqual(state.chat, { open: false, tab: 'chats', thread: null });
  assert.deepEqual(state.letters, []);
});

test('the same leader is listed once however often the refusal comes', () => {
  const state = fresh();
  endSend(state, { refused: true, reply: REFUSAL, thread: 'Winston Churchill' });
  state.pending = { thread: 'Winston Churchill', text: 'Again?' };
  endSend(state, { refused: true, reply: REFUSAL, thread: 'Winston Churchill' });
  assert.deepEqual(state.letters, ['Winston Churchill']);
});

test('a letter is an order form draft on the letter channel, to that person', () => {
  assert.deepEqual(letterDraft('Winston Churchill', 'Send ships.'), { to: 'Winston Churchill', channel: 'letter', text: 'Send ships.' });
});

test('a letter thread offers a letter composer and sends the words as a letter', () => {
  const doc = installDom();
  const sent = [];
  const nodes = threadView({ name: 'Winston Churchill', items: [], letter: true, onSend: (t) => sent.push(t) });
  const root = doc.body;
  root.append(...nodes);
  assert.match(words(root), /Winston Churchill answers in person\. Write to them; your letter reaches their desk\./);
  const form = root.querySelector('form.rl-th-compose');
  const ta = root.querySelector('textarea');
  assert.equal(ta.getAttribute('aria-label'), 'Letter');
  assert.equal(buttons(root, 'Send letter').length, 1);
  ta.value = 'Please send the ships.';
  fire(form, 'submit');
  assert.deepEqual(sent, ['Please send the ships.']);
});

test('a thread that is not a letter thread keeps the message composer', () => {
  const doc = installDom();
  doc.body.append(...threadView({ name: 'Harry Hopkins', items: [] }));
  assert.equal(doc.body.querySelector('textarea').getAttribute('aria-label'), 'Message');
  assert.equal(buttons(doc.body, 'Send').length, 1);
  assert.doesNotMatch(words(doc.body), /answers in person/);
});

test('the dock sends a letter thread\'s words to the letter call, not to counsel', () => {
  const doc = installDom();
  const calls = [];
  const dock = chatDock({
    state: { open: true, tab: 'chats', thread: 'Winston Churchill' }, onState: () => {}, threads: { 'Winston Churchill': [] }, seen: {},
    reach: { government: [{ name: 'Winston Churchill', channel_keys: ['letter'], channels: ['Letter'] }] }, record: null,
    pending: null, drafts: {}, letters: ['Winston Churchill'],
    consult: (to, t) => calls.push(['consult', to, t]), letter: (to, t) => calls.push(['letter', to, t]),
  });
  doc.body.append(dock);
  const ta = doc.body.querySelector('textarea');
  ta.value = 'Ships, please.';
  fire(doc.body.querySelector('form.rl-th-compose'), 'submit');
  assert.deepEqual(calls, [['letter', 'Winston Churchill', 'Ships, please.']]);
});

// --- the notice address in the game menu ------------------------------------------------

const settle = () => new Promise((r) => setTimeout(r, 0));
const GAME = { name: 'Autumn 1941', host: false };

function menu(answer) {
  const doc = installDom();
  uiFor(`g-${Math.random()}`);
  const calls = [];
  api.game = async (action, body) => { calls.push([action, body]); return answer(action, body); };
  const [open, dialog] = gameMenu(GAME, { go: () => {}, refresh: async () => {} }, { idle: () => true });
  doc.body.append(open, dialog);
  open.click();
  return { dialog, calls };
}

const FOUND = { reply: 'Notices go to nobody yet, in America/New_York.', refused: false, address: '', zone: 'America/New_York' };

test('the menu has a Notices: your email section; opening it reads the address and zone', async () => {
  const { dialog, calls } = menu(() => ({ ...FOUND, address: 'ada@example.org' }));
  await settle();
  assert.deepEqual(calls, [['notice-address', undefined]]);
  assert.ok(dialog.querySelectorAll('h3').map(words).includes('Notices: your email'));
  assert.equal(dialog.querySelector('input[name="address"]').value, 'ada@example.org');
  assert.equal(dialog.querySelector('input[name="zone"]').value, 'America/New_York');
});

test('Save sends the typed address and zone to notice-address and shows its reply', async () => {
  const { dialog, calls } = menu((action, body) => (body ? { reply: 'Notices go to bea@example.org, in Europe/London.', refused: false, ...body } : FOUND));
  await settle();
  dialog.querySelector('input[name="address"]').value = ' bea@example.org ';
  dialog.querySelector('input[name="zone"]').value = 'Europe/London';
  fire(dialog.querySelector('form.rl-notice'), 'submit');
  await settle();
  assert.deepEqual(calls.at(-1), ['notice-address', { address: 'bea@example.org', zone: 'Europe/London' }]);
  assert.match(words(dialog), /Notices go to bea@example\.org, in Europe\/London\./);
});

test('an empty address clears it; an empty zone is left out so the stored one stays', async () => {
  const { dialog, calls } = menu((action, body) => (body ? { reply: 'Notices are off.', refused: false, address: '', zone: 'America/New_York' } : { ...FOUND, address: 'ada@example.org' }));
  await settle();
  dialog.querySelector('input[name="address"]').value = '';
  dialog.querySelector('input[name="zone"]').value = '';
  fire(dialog.querySelector('form.rl-notice'), 'submit');
  await settle();
  assert.deepEqual(calls.at(-1), ['notice-address', { address: '' }]);
});

test('a refusal keeps what was typed and says why', async () => {
  const { dialog } = menu((action, body) => (body
    ? { reply: 'That does not look like an email address.', refused: true, address: '', zone: 'America/New_York' } : FOUND));
  await settle();
  dialog.querySelector('input[name="address"]').value = 'not-an-address';
  fire(dialog.querySelector('form.rl-notice'), 'submit');
  await settle();
  assert.equal(dialog.querySelector('input[name="address"]').value, 'not-an-address');
  assert.match(words(dialog), /does not look like an email address/);
});

test('the notice fields are labelled and the form submits on Enter (a submit button)', async () => {
  const { dialog } = menu(() => FOUND);
  await settle();
  for (const name of ['address', 'zone']) {
    const input = dialog.querySelector(`input[name="${name}"]`);
    const label = dialog.querySelectorAll('label').find((l) => l.getAttribute('for') === input.id);
    assert.ok(label, `${name} has a label`);
  }
  assert.equal(dialog.querySelector('form.rl-notice button[type="submit"]').textContent, 'Save');
});
