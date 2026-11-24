// Posts on screen: the seat's own card shows its post with its ladder under it; a change of post
// pending on the seat heads what needs it, with when it lands; a person the seat may move shows
// the moves the server sent, each with the rung it leads to, and choosing one runs the check and
// a confirm chip; a seat with no post opens on what it can still do. The client decides nothing:
// every move, rung and landing day drawn here is one the server's `posts` block sent.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { courtBoard } = await import('../js/views/realism-court.js');
const { needLines, needsList, dueWords } = await import('../js/views/realism-needs.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));

const STARK = 'VAKP5F7QBGTN3YCP8CKDF4TN1E';
const KIMMEL = 'KIMMEL0000000000000000000A';
const PYE = 'PYE000000000000000000000AA';

/** Stark's view: Chief of Naval Operations, on a ladder of two rungs, with moves on two people. */
function posted(more = {}) {
  const r = structuredClone(fixture);
  r.posts = {
    post: { id: 'cno', name: 'Chief of Naval Operations' },
    ladder: [
      { id: 'cinc-pac', name: 'Commander in Chief, Pacific Fleet', free: false },
      { id: 'com-batfor', name: 'Commander, Battle Force', free: true },
    ],
    moved_by: ['President of the United States'],
    pending: [],
    moves: [
      { person: KIMMEL, name: 'Husband E. Kimmel', post: 'cinc-pac', office: 'Commander in Chief, Pacific Fleet',
        move: 'relieve', down: 'Husband E. Kimmel', rung: 'Commander, Battle Force', question: false },
      { person: PYE, name: 'William S. Pye', post: 'cinc-pac', office: 'Commander in Chief, Pacific Fleet',
        move: 'appoint', down: 'Husband E. Kimmel', rung: 'Commander, Battle Force', question: false },
    ],
    ...more,
  };
  return r;
}

/** A seat relieved of every post: the room the server sends it. */
function relieved(room = {}) {
  const r = structuredClone(fixture);
  r.agenda = { ...r.agenda, items: [] };
  r.orders = { ...r.orders, orders: [] };
  r.posts = {
    post: null, ladder: [], moved_by: [], pending: [], moves: [],
    room: {
      inner_circle: ['Harry L. Hopkins'],
      letters: [{ id: 'd-letter-1', title: 'A letter from Hyde Park' }],
      aims: ['Keep the fleet in being'],
      through: [{ person: 'KCGWPP4ACP8FAQ882NJAGZB8H5', name: 'Harry L. Hopkins', authority: ['Lend-Lease allocation'] }],
      ...room,
    },
  };
  return r;
}

const ui = (piece = null) => ({ view: 'board', board: 'court', piece, theatre: { mode: 'map', scope: 'reports' }, chat: { open: false, tab: 'chats', thread: null }, draft: null });
const board = (r, u = ui(), more = {}) => courtBoard(r, u, { pick: () => {}, act: () => {}, ...more });
const person = (id, name) => ({ kind: 'person', person: id, name });
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

// --- rule 1: the seat's own card shows its post, and under it the ladder ------------------------

test('the seat\'s own card names its post, then its ladder in order, each rung free or held', () => {
  const view = board(posted());
  const card = view.querySelector('.rl-post-card');
  assert.ok(card, 'the seat has its own card on the Court');
  assert.equal(words(card.querySelector('.rl-post-name')), 'Chief of Naval Operations');
  const ladder = card.querySelector('.rl-post-ladder');
  assert.ok(ladder, 'a ladder under the post');
  const kids = [...card.children];
  assert.ok(kids.indexOf(card.querySelector('.rl-post-name')) < kids.indexOf(ladder), 'the ladder sits under the post');
  assert.deepEqual(ladder.querySelectorAll('li').map(words),
    ['Commander in Chief, Pacific Fleet · held', 'Commander, Battle Force · free']);
  assert.equal(words(card.querySelector('.rl-post-movers')), 'Who may move you: President of the United States');
});

test('the card stands when the court has not reached the view, and is absent with the posts rule off', () => {
  const r = posted();
  delete r.court;
  assert.equal(words(board(r).querySelector('.rl-post-name')), 'Chief of Naval Operations');
  const off = structuredClone(fixture);
  assert.equal(board(off).querySelector('.rl-post-card'), null);
});

test('a post with no ladder says so rather than drawing an empty list', () => {
  const view = board(posted({ ladder: [] }));
  assert.equal(view.querySelector('.rl-post-ladder'), null);
  assert.equal(words(view.querySelector('.rl-post-noladder')), 'No ladder runs below this post.');
});

// --- rule 2: a change pending on the seat heads what needs it, with when it lands ---------------

test('a pending change of post is the first line of what needs you, with the day it lands', () => {
  const r = posted({
    pending: [{ id: 'd-notice-1', post: 'Chief of Naval Operations', move: 'relieve', lands: 'at the close of the next wake', wake: 6, rung: 'Commander, Battle Force' }],
  });
  r.agenda = { ...r.agenda, items: [{ id: 'm-early', kind: 'Mandate', text: 'An early mandate', issuer: 'The President', deadline: '1941-10-01', issued: '1941-09-01' }] };
  const lines = needLines(r);
  assert.equal(lines[0].kind, 'post', 'ahead of a matter due earlier');
  assert.equal(lines[0].what, 'You are to be relieved as Chief of Naval Operations, down to Commander, Battle Force');
  assert.equal(dueWords(lines[0]), 'Lands at the close of the next wake (wake 6)');
  assert.equal(lines[0].from, 'President of the United States');
  const list = needsList(r, lines);
  const first = list.querySelector('.rl-need');
  assert.equal(first.getAttribute('data-kind'), 'post');
  assert.equal(words(first.querySelector('.rl-need-due')), 'Lands at the close of the next wake (wake 6)');
});

test('a change waiting for the office question says it lands only at the sitting, and names no rung', () => {
  const r = posted({
    pending: [{ id: 'd-notice-2', post: 'Chief of Naval Operations', move: 'relieve', lands: 'only at the sitting of the office question', wake: null, rung: null }],
  });
  const [line] = needLines(r);
  assert.equal(line.what, 'You are to be relieved as Chief of Naval Operations');
  assert.equal(dueWords(line), 'Lands only at the sitting of the office question');
});

test('an appointment pending on the seat reads as one; with nothing pending there is no post line', () => {
  const r = posted({
    pending: [{ id: 'd-notice-3', post: 'Commander in Chief, Pacific Fleet', move: 'appoint', lands: 'at the close of this wake', wake: 5, rung: 'Commander in Chief, Pacific Fleet' }],
  });
  assert.equal(needLines(r)[0].what, 'You are to be appointed Commander in Chief, Pacific Fleet');
  assert.equal(needLines(posted()).filter((l) => l.kind === 'post').length, 0);
  assert.equal(needLines(structuredClone(fixture)).filter((l) => l.kind === 'post').length, 0);
});

// --- rule 3: the moves open on a person, each with its rung; choosing runs the check and a chip --

test('the people the seat may move are listed on its card, and picking one shows the moves the server sent', () => {
  const picks = [];
  const view = board(posted(), ui(), { pick: (p) => picks.push(p) });
  const who = view.querySelectorAll('.rl-post-people button').map(words);
  assert.deepEqual(who, ['Husband E. Kimmel', 'William S. Pye']);
  view.querySelectorAll('.rl-post-people button')[0].click();
  assert.deepEqual(picks.at(-1), { piece: { kind: 'person', person: KIMMEL, name: 'Husband E. Kimmel' } });
  const picked = board(posted(), ui(person(KIMMEL, 'Husband E. Kimmel')));
  const moves = picked.querySelectorAll('.rl-post-move');
  assert.deepEqual(moves.map(words), ['Relieve as Commander in Chief, Pacific Fleet: Husband E. Kimmel goes to Commander, Battle Force']);
});

test('an appointment names who it puts down and the rung that person lands on; a move into a seat\'s last authority says it waits', () => {
  const r = posted();
  r.posts.moves.push({ person: PYE, name: 'William S. Pye', post: 'com-batfor', office: 'Commander, Battle Force',
    move: 'restore', down: null, rung: null, question: true });
  const picked = board(r, ui(person(PYE, 'William S. Pye')));
  assert.deepEqual(picked.querySelectorAll('.rl-post-move').map(words), [
    'Appoint as Commander in Chief, Pacific Fleet: Husband E. Kimmel goes to Commander, Battle Force',
    'Restore as Commander, Battle Force: nobody is put down; it waits for the office question',
  ]);
});

test('mutant: a move the server did not send is never offered', () => {
  // the server sends Kimmel a relieve only: no appoint or restore is drawn for him, and a person
  // with no move from the server has no move at all, whatever their office
  const picked = board(posted(), ui(person(KIMMEL, 'Husband E. Kimmel')));
  const labels = picked.querySelectorAll('.rl-post-move').map(words);
  assert.equal(labels.length, 1);
  assert.ok(labels.every((l) => l.startsWith('Relieve')));
  const r = posted();
  r.posts.moves = [];
  assert.equal(board(r, ui(person(KIMMEL, 'Husband E. Kimmel'))).querySelectorAll('.rl-post-move').length, 0);
  assert.equal(board(r).querySelector('.rl-post-people'), null);
});

test('choosing a move runs the server\'s check with its fields; an allowed check shows the confirm chip, which files it', async () => {
  const calls = [];
  api.realism = async (action, body) => { calls.push([action, body]); return { reply: '', refused: false, check: 'allowed', who: null, reason: '' }; };
  const acts = [];
  const u = ui(person(KIMMEL, 'Husband E. Kimmel'));
  const redraws = [];
  const pick = (p) => { Object.assign(u, p); redraws.push(p); };
  let view = board(posted(), u, { pick, act: (...a) => acts.push(a) });
  view.querySelector('.rl-post-move').click();
  await settle();
  assert.deepEqual(calls, [['check', { move: 'relieve', person: KIMMEL, post: 'cinc-pac' }]]);
  view = board(posted(), u, { pick, act: (...a) => acts.push(a) });
  const chip = view.querySelector('.rl-post-chip');
  assert.ok(chip, 'the confirm chip');
  assert.equal(buttons(chip, 'Not now').length, 1);
  buttons(chip, 'Confirm the move')[0].click();
  assert.equal(acts.length, 1);
  assert.equal(acts[0][1], 'move');
  assert.deepEqual(acts[0][2], { move: 'relieve', person: KIMMEL, post: 'cinc-pac' });
  view = board(posted(), u, { pick, act: (...a) => acts.push(a) });
  assert.equal(view.querySelector('.rl-post-chip'), null, 'the chip is gone once filed');
});

test('a check refused shows the server\'s reason and no confirm; a locked or question check shows its words with the chip', async () => {
  const answers = [
    { check: 'beyond', who: null, reason: 'Your card does not command that post.' },
    { check: 'locked', who: 'The President', reason: 'The President must allow it.' },
    { check: 'question', who: null, reason: 'It goes to the office question.' },
  ];
  for (const a of answers) {
    api.realism = async () => ({ reply: '', refused: false, ...a });
    const u = ui(person(KIMMEL, 'Husband E. Kimmel'));
    const pick = (p) => Object.assign(u, p);
    board(posted(), u, { pick }).querySelector('.rl-post-move').click();
    await settle();
    const view = board(posted(), u, { pick });
    assert.equal(words(view.querySelector('.rl-post-check')), a.reason);
    assert.equal(Boolean(view.querySelector('.rl-post-chip')), a.check !== 'beyond', a.check);
  }
  api.realism = async () => { throw new Error('down'); };
  const u = ui(person(KIMMEL, 'Husband E. Kimmel'));
  const pick = (p) => Object.assign(u, p);
  board(posted(), u, { pick }).querySelector('.rl-post-move').click();
  await settle();
  const view = board(posted(), u, { pick });
  assert.equal(view.querySelector('.rl-post-chip'), null);
  assert.equal(words(view.querySelector('.rl-post-check')), 'The check did not come back. Try again.');
});

test('every move and confirm is a button the keyboard reaches', () => {
  const picked = board(posted(), ui(person(KIMMEL, 'Husband E. Kimmel')));
  for (const b of picked.querySelectorAll('.rl-post-move')) assert.equal(b.tagName, 'BUTTON');
  for (const b of picked.querySelectorAll('.rl-post-people button')) assert.equal(b.getAttribute('type'), 'button');
});

// --- rule 4: a seat with no post opens on what it can still do --------------------------------

test('a seat with no post opens its card on what it can still do', () => {
  const view = board(relieved());
  const card = view.querySelector('.rl-post-card');
  assert.equal(words(card.querySelector('.rl-post-name')), 'You hold no post');
  const room = card.querySelector('.rl-post-room');
  assert.ok(room);
  assert.equal(words(room.querySelector('h3')), 'What you can still do');
  const text = words(room);
  assert.match(text, /Harry L\. Hopkins/);
  assert.match(text, /A letter from Hyde Park/);
  assert.match(text, /Keep the fleet in being/);
  assert.match(text, /Act through Harry L\. Hopkins: Lend-Lease allocation/);
  assert.equal(view.querySelector('.rl-post-card'), [...view.children][1], 'first under the heading');
});

test('what needs you, empty for a seat with no post, shows what it can still do and never an empty room', () => {
  // the fixture's battles, held orders and floor measures are other kinds' lines: the list is drawn with none
  const r = relieved();
  const list = needsList(r, []);
  assert.equal(list.querySelector('.rl-needs-none'), null);
  assert.equal(words(list.querySelector('.rl-post-room h3')), 'What you can still do');
  const bare = relieved({ inner_circle: [], letters: [], aims: [], through: [] });
  const view = board(bare);
  const room = view.querySelector('.rl-post-room');
  assert.ok(room.querySelectorAll('li').length >= 1, 'a line is always there');
  assert.match(words(room), /Write an order in your own words/);
  const bareList = needsList(bare, []);
  assert.match(words(bareList.querySelector('.rl-post-room')), /Write an order in your own words/);
});

test('a posted seat with nothing waiting keeps the plain empty line', () => {
  const r = posted();
  r.agenda = { ...r.agenda, items: [] };
  r.orders = { ...r.orders, orders: [] };
  const list = needsList(r, []);
  assert.equal(list.querySelector('.rl-post-room'), null);
  assert.ok(list.querySelector('.rl-needs-none'));
});
