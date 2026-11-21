// A held order that ends is told to its own seat, with the reason: the catch-up page's `held`
// steps (held, landed, failed, replaced, withdrawn) play among the seat's own orders and read as
// the line the server wrote from the seat's view, as text.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';

installDom();
const play = await import('../js/views/realism-playback.js');

const HELD = [
  { kind: 'held', on: '1900-04-02', what: 'held', line: 'Held until Ilse Varg allows it: as written.' },
  { kind: 'paper', on: '1900-04-03', paper: 'p-1', title: 'A request from Kara Lind' },
  { kind: 'held', on: '1900-04-05', what: 'failed', line: 'Your held order failed: The Norra Levy is not in service until 1 January 1901.' },
  { kind: 'stake', on: '1900-04-05', name: 'The Gulf crossing', what: 'moved' },
];
const page = (steps) => ({ number: 3, opened: '5 April 1900', days_passed: 3, papers: 1, filed: [], settled: [], steps });

test('a held step plays among the seat\'s own orders, after the papers and before the stakes', () => {
  assert.deepEqual(play.playOrder(HELD).map((s) => (s.kind === 'held' ? s.what : s.kind)), ['paper', 'held', 'failed', 'stake']);
});

test('a held step reads as the server\'s line, the failure with its reason', () => {
  installDom();
  const el = play.wakePlayer({ pages: [page(HELD)], reduced: true });
  const lines = el.querySelectorAll('li.rl-plb-step[data-kind="held"]').map((li) => words(li.querySelector('.rl-plb-cap')));
  assert.deepEqual(lines, [HELD[0].line, HELD[2].line]);
});

test('the line is drawn as text, never as markup', () => {
  installDom();
  const step = { kind: 'held', on: '1900-04-05', what: 'failed', line: 'Your held order failed: <b>no</b>.' };
  const el = play.wakePlayer({ pages: [page([step])], reduced: true });
  const cap = el.querySelector('li.rl-plb-step .rl-plb-cap');
  assert.equal(words(cap), step.line);
  assert.equal(cap.querySelectorAll('b').length, 0);
  assert.equal(play.stepLine({ kind: 'held', on: '1900-04-05', what: 'landed' }), '');
});

test('a held step with no usable line draws nothing, and a wake of only such steps draws no heading', () => {
  installDom();
  const blank = [{ kind: 'held', on: '1900-04-05', what: 'landed' }, { kind: 'held', on: '1900-04-05', what: 'held', line: '  ' }];
  const el = play.wakePlayer({ pages: [page([...blank, HELD[1]])], reduced: true });
  assert.equal(el.querySelectorAll('li.rl-plb-step').length, 1);
  assert.equal(el.querySelectorAll('li.rl-plb-wake').length, 1);
  assert.deepEqual(play.playOrder(blank), []);
  assert.equal(play.wakePlayer({ pages: [page(blank)], reduced: true }), null);
  assert.equal(play.playbackDialog({ pages: [page(blank)], reduced: true }), null);
});

test('another kind\'s line is unchanged', () => {
  installDom();
  assert.equal(play.stepLine({ kind: 'stake', name: 'The Gulf crossing', what: 'moved' }), 'The Gulf crossing: moved');
});
