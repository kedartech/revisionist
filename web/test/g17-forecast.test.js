// The forecast checked, on the card: under "Needs your answer", each filed order that came from a
// suggested action lists its expected moves with an outcome (it happened, it did not, not
// settled yet), the seat's record reads "Your staff were right N of M", and a choice the aide
// made is marked as the aide's, only when the data carries it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';

installDom();
const { needsAnswer } = await import('../js/views/realism-answer.js');
const { outcomeWords, recordLine } = await import('../js/views/realism-estimate.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const TODAY = '1941-10-20';

const move = (over = {}) => ({ on: 'figure', name: 'House Democrats', direction: 'gain', size: 1, sure: 'likely', outcome: 'held', ...over });
const order = (over = {}) => ({ id: 'o1', filed: '1 September 1941', asked: 'State our position plainly', aide: false,
  settles: '9 September 1941', moves: [move()], risks: null, ...over });
const desk = (forecast) => needsAnswer({ ...fixture.agenda, forecast }, { act: () => {}, today: TODAY });
const outcomes = (el) => el.querySelectorAll('.rl-fc-outcome').map(words);

test('the fixture carries one settled forecast and one open, the second chosen by the aide', () => {
  const { forecast } = fixture.agenda;
  assert.deepEqual(forecast.orders.map((o) => o.aide), [false, true]);
  assert.deepEqual(forecast.orders.flatMap((o) => o.moves.map((m) => m.outcome)), ['held', 'open']);
});

test('each filed order shows its expected move and its outcome', () => {
  const el = desk(fixture.agenda.forecast);
  const orders = el.querySelectorAll('.rl-fc-order');
  assert.equal(orders.length, 2);
  assert.equal(words(orders[0].querySelector('.rl-fc-asked')), 'State our position plainly · filed 1 September 1941');
  assert.equal(words(orders[0].querySelector('.rl-exp-name')), 'House Democrats');
  assert.equal(words(orders[0].querySelector('.rl-fc-expect')), 'One step in your favour · staff think it likely');
  assert.deepEqual(outcomes(el), ['It happened', 'Not settled yet']);
});

test('held, missed and open each read in their own words', () => {
  const el = desk({ checked: 1, held: 0, orders: [order({ moves: [move({ outcome: 'held' }), move({ outcome: 'missed' }), move({ outcome: 'open' })] })] });
  assert.deepEqual(outcomes(el), ['It happened', 'It did not happen', 'Not settled yet']);
  assert.deepEqual(el.querySelectorAll('.rl-fc-move').map((m) => m.getAttribute('data-outcome')), ['held', 'missed', 'open']);
});

test('a move that is not settled is never worded as a result', () => {
  assert.equal(outcomeWords('open'), 'Not settled yet');
  assert.equal(outcomeWords('held'), 'It happened');
  assert.equal(outcomeWords('missed'), 'It did not happen');
  const el = desk({ checked: 0, held: 0, orders: [order({ settles: null, moves: [move({ outcome: 'open' })] })] });
  assert.deepEqual(outcomes(el), ['Not settled yet']);
  assert.equal(el.querySelector('.rl-fc-settles'), null);
});

test('the record reads "Your staff were right N of M"', () => {
  assert.equal(recordLine({ checked: 3, held: 2, orders: [] }), 'Your staff were right 2 of 3');
  assert.equal(words(desk(fixture.agenda.forecast).querySelector('.rl-fc-record')), 'Your staff were right 1 of 1');
  assert.equal(recordLine({ checked: 0, held: 0, orders: [] }), null);
  const none = desk({ checked: 0, held: 0, orders: [order({ moves: [move({ outcome: 'open' })] })] });
  assert.equal(words(none.querySelector('.rl-fc-record')), 'None has settled yet');
});

test('the aide mark shows on a choice the aide made, and only there', () => {
  const el = desk(fixture.agenda.forecast);
  const [mine, aides] = el.querySelectorAll('.rl-fc-order');
  assert.equal(mine.querySelector('.rl-fc-aide'), null);
  assert.equal(words(aides.querySelector('.rl-fc-aide')), 'Chosen by your aide');
});

test('with no forecast in the data nothing is drawn and no aide mark appears', () => {
  for (const f of [undefined, null, { checked: 0, held: 0, orders: [] }]) {
    const el = desk(f);
    assert.equal(el.querySelector('.rl-fc'), null);
    assert.equal(el.querySelector('.rl-fc-aide'), null);
  }
});
