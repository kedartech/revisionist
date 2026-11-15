// Expected moves on a suggested action: under "Needs your answer", an option that carries
// `expects` shows one row per entry with the target's name, a five-step bar marking the
// expected step as a gain or a cost, and the words for its size and how sure the staff are;
// `risks` show as three chips with a level each, the risk sentence kept as a caption; an
// option with neither looks as it did before.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';

installDom();
const { needsAnswer } = await import('../js/views/realism-answer.js');
const { expectWords, riskChips, stepCells } = await import('../js/views/realism-estimate.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const TODAY = '1941-10-20';

const move = (over = {}) => ({ on: 'figure', name: 'Allied merchant losses to U-boats, Sep 1941', direction: 'gain', size: 1, sure: 'likely', ...over });
const option = (over = {}) => ({ label: 'Order the escort forward', to: 'Harold R. Stark', risk: 'The Germans may take it as an act of war.',
  historical: true, pick: 'p1', taken: false, expects: [], risks: null, ...over });
const item = (extra = {}) => ({ id: 'a1', kind: 'Order', issuer: 'Franklin D. Roosevelt', text: 'Keep the convoys moving.', issued: '12 October 1941',
  deadline: '26 October 1941', cause: null, options: [], plan: [], ...extra });
const desk = (style, it) => needsAnswer({ style, items: [it], initiative: [] }, { act: () => {}, today: TODAY });
const offered = (o) => desk('beginner', item({ options: [o] })).querySelector('.rl-ans-option');
const lines = (el) => el.querySelectorAll('.rl-ans-line').map(words);
const marks = (row) => row.querySelectorAll('.rl-exp-bar i').map((c) => c.getAttribute('data-step') ?? '');

test('the fixture offers an option with four expected moves and risk levels', () => {
  const [o] = fixture.agenda.items[0].options;
  assert.equal(o.expects.length, 4);
  assert.deepEqual(o.risks, { escalation: 2, refusal: 0, exposure: 1 });
});

test('an option with expected moves shows one row each: the name, a five-step bar and the words', () => {
  const o = fixture.agenda.items[0].options[0];
  const el = offered(o);
  const rows = el.querySelectorAll('.rl-exp-row');
  assert.equal(rows.length, 4);
  assert.deepEqual(rows.map((r) => words(r.querySelector('.rl-exp-name'))), [
    'Allied merchant losses to U-boats, Sep 1941',
    'Adolf Hitler, stance to you',
    'Sir Dudley Pound, regard for you',
    'Revising the Neutrality Act',
  ]);
  assert.deepEqual(rows.map((r) => words(r.querySelector('.rl-exp-glyph'))), ['▲', '▼', '▲', '▲']);
  assert.deepEqual(rows.map((r) => words(r.querySelector('.rl-exp-words'))), [
    'One step in your favour · staff think it likely',
    'One step against you · a guess',
    'One step in your favour · firm',
    'One step in your favour · staff think it likely',
  ]);
  for (const r of rows) assert.equal(r.querySelectorAll('.rl-exp-bar i').length, 5);
  assert.equal(rows[0].querySelector('.rl-exp-bar').getAttribute('aria-hidden'), 'true');
});

test('the bar marks where it stands in the middle, a gain to the right and a cost to the left, one step or two', () => {
  assert.deepEqual(stepCells(move({ direction: 'gain', size: 1 })), ['', '', 'now', 'gain', '']);
  assert.deepEqual(stepCells(move({ direction: 'gain', size: 2 })), ['', '', 'now', 'gain', 'gain']);
  assert.deepEqual(stepCells(move({ direction: 'cost', size: 1 })), ['', 'cost', 'now', '', '']);
  assert.deepEqual(stepCells(move({ direction: 'cost', size: 2 })), ['cost', 'cost', 'now', '', '']);
  const el = offered(option({ expects: [move({ direction: 'cost', size: 2, sure: 'guess' })] }));
  const [row] = el.querySelectorAll('.rl-exp-row');
  assert.deepEqual(marks(row), ['cost', 'cost', 'now', '', '']);
  assert.equal(words(row.querySelector('.rl-exp-read')), '▼ Two steps against you · a guess');
});

test('the words name the size, the side and how sure the staff are', () => {
  assert.equal(expectWords(move({ size: 2, direction: 'gain', sure: 'firm' })), 'Two steps in your favour · firm');
  assert.equal(expectWords(move({ size: 1, direction: 'cost', sure: 'likely' })), 'One step against you · staff think it likely');
});

test('risk levels show as three chips with a level each, and the risk sentence stays as a caption', () => {
  const el = offered(fixture.agenda.items[0].options[0]);
  const chips = el.querySelectorAll('.rl-exp-chip');
  assert.equal(chips.length, 3);
  assert.deepEqual(chips.map((c) => c.getAttribute('aria-label')), ['Escalation: 2 of 3', 'Refusal: 0 of 3', 'Exposure: 1 of 3']);
  assert.deepEqual(chips.map((c) => words(c.querySelector('.rl-exp-level'))), ['●●○', '○○○', '●○○']);
  assert.equal(words(el.querySelector('.rl-exp-cap')), 'The Germans may take it as an act of war.');
  assert.deepEqual(lines(el), ['To Harold R. Stark'], 'the sentence is the caption, not a second risk line');
});

test('the chips read the level they are given, not a fixed one', () => {
  const chips = riskChips({ escalation: 3, refusal: 1, exposure: 0 }).querySelectorAll('.rl-exp-chip');
  assert.deepEqual(chips.map((c) => words(c.querySelector('.rl-exp-level'))), ['●●●', '●○○', '○○○']);
});

test('an option with neither looks as it does today', () => {
  for (const o of [option(), option({ expects: undefined, risks: undefined })]) {
    const el = offered(o);
    assert.equal(el.querySelector('.rl-exp'), null);
    assert.deepEqual(lines(el), ['To Harold R. Stark', 'Risk: The Germans may take it as an act of war.']);
    assert.equal(el.children.length, 4, 'label, two lines, the button');
  }
});

test('moves with no risk levels keep the risk line, and levels with no moves draw no rows', () => {
  const moves = offered(option({ expects: [move()] }));
  assert.equal(moves.querySelectorAll('.rl-exp-row').length, 1);
  assert.equal(moves.querySelector('.rl-exp-chip'), null);
  assert.equal(moves.querySelector('.rl-exp-cap'), null);
  assert.deepEqual(lines(moves), ['To Harold R. Stark', 'Risk: The Germans may take it as an act of war.']);
  const levels = offered(option({ risks: { escalation: 1, refusal: 1, exposure: 1 } }));
  assert.equal(levels.querySelector('.rl-exp-row'), null);
  assert.equal(levels.querySelectorAll('.rl-exp-chip').length, 3);
});

test('a guided plan shows its shared moves and chips once, under the steps', () => {
  const step = (label, pick) => option({ label, pick, expects: [move({ on: 'stake', name: 'Revising the Neutrality Act', size: 2, sure: 'guess' })],
    risks: { escalation: 0, refusal: 1, exposure: 2 }, risk: 'Word of the count may get out.' });
  const s = desk('guided', item({ plan: [step('Ask the Speaker for a count', 'w1'), step('Brief the leaders', 'w1')] }));
  assert.equal(s.querySelectorAll('.rl-exp').length, 1);
  assert.equal(s.querySelectorAll('.rl-exp-row').length, 1);
  assert.equal(s.querySelectorAll('.rl-exp-chip').length, 3);
  assert.equal(words(s.querySelector('.rl-exp-cap')), 'Word of the count may get out.');
  assert.deepEqual(lines(s), ['To Harold R. Stark', 'To Harold R. Stark']);
  assert.equal(s.querySelector('.rl-ans-plan .rl-exp'), null, 'not inside a step');
});

test('a guided plan with neither keeps each step as it is today', () => {
  const s = desk('guided', item({ plan: [option({ label: 'Ask the Speaker for a count' })] }));
  assert.equal(s.querySelector('.rl-exp'), null);
  assert.deepEqual(lines(s), ['To Harold R. Stark', 'Risk: The Germans may take it as an act of war.']);
});
