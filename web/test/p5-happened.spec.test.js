// Spec for Train 2 unit W (contract K2), revised for unit Q4 (contract KQ): each line is a
// sentence. The unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import * as happened from '../js/views/realism-happened.js';
import { HAPPENED_PREFIX, changedFigures, happenedLines, happenedStore, shouldShow } from '../js/views/realism-happened.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

const memory = () => {
  const data = new Map();
  return { data, getItem: (k) => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)) };
};

test('one sentence per order moving or settled since the last wake', () => {
  assert.deepEqual(happenedLines(fixture.record), [
    '“Give a naval order: Escort the convoys, The Iceland route” is under way, with Franklin D. Roosevelt.',
    '“Escort the convoys to Iceland and shoot on sight” is under way, with Harold R. Stark.',
    '“Send a bill to Congress: Revise the Neutrality Act” is under way, with Sam Rayburn.',
    '“Ask Senator Wheeler to drop his filibuster” has been rebuffed. “Wheeler would not be moved while the America First rallies go on.”',
    '“Allocate Lend-Lease aid: Britain, 40” has been enacted.',
    '“Close the Pan American Highway to German trade” has been refused. “Hull would not act without the Latin American governments.”',
    '“Ask the Navy for a report on Pacific bases” has lapsed.',
    '“Send a bill to Congress: Extend the draft to men of forty” has been withdrawn.',
    '“Ask the Speaker to hold the vote until November” has been agreed to. “The Speaker will hold it.”',
    '“Give a naval order: Patrol the Denmark Strait” has been carried out.',
    '“Give a naval order: Escort the HX convoys to the meeting point” has been carried out loosely.',
    '“Give a naval order: Base a destroyer squadron at Reykjavik” has been carried out late.',
    '“Allocate Lend-Lease aid: Soviet Union, 30” has been carried out in part.',
  ]);
  const quiet = { orders: [{ ...fixture.record.orders[0], holder: null }], wake: { ...fixture.record.wake, settled: [] } };
  assert.deepEqual(happenedLines(quiet), ['“Give a naval order: Escort the convoys, The Iceland route” is under way.']);
  assert.deepEqual(happenedLines({ orders: [], wake: null }), []);
});

test('the sentence table covers every settled status, and an unknown one still reads', () => {
  const table = happened.STATUS_SENTENCE;
  assert.ok(table && Object.isFrozen(table), 'STATUS_SENTENCE is a frozen table');
  assert.deepEqual(Object.keys(table).sort(), [
    'agreed', 'carried out', 'carried out in part', 'carried out late', 'carried out loosely',
    'enacted', 'lapsed', 'rebuffed', 'refused', 'withdrawn',
  ]);
  const odd = { orders: [{ ...fixture.record.orders[3], status: 'mislaid', said: null }], wake: fixture.record.wake };
  assert.deepEqual(happenedLines(odd), ['“Ask Senator Wheeler to drop his filibuster”: mislaid.']);
});

test('figures that moved between the last two readings', () => {
  const out = changedFigures(fixture.situation);
  assert.ok(out.includes('Allied merchant losses to U-boats, Sep 1941: 231,000 to 209,835 GRT'), out.join(' | '));
  const flat = { figures: [{ label: 'Flat', unit: null, disagree: false, sources: [{ history: [{ value: 5 }, { value: 5 }] }] },
    { label: 'Bare', unit: null, disagree: false, sources: [{ history: [{ value: 1 }, { value: 2 }] }] },
    { label: 'One', unit: 'ships', disagree: false, sources: [{ history: [{ value: 1 }] }] }] };
  assert.deepEqual(changedFigures(flat), ['Bare: 1 to 2']);
  assert.deepEqual(changedFigures({ figures: [] }), []);
});

test('the sheet shows once per wake, never for wake 0', () => {
  const s = memory();
  const store = happenedStore(s, 'c1');
  assert.equal(store.read(), 0);
  assert.equal(shouldShow({ number: 0 }, store), false);
  assert.equal(shouldShow({ number: 3 }, store), true);
  store.write(3);
  assert.equal(shouldShow({ number: 3 }, store), false);
  assert.equal(shouldShow({ number: 4 }, store), true);
  assert.ok(s.data.has(`${HAPPENED_PREFIX}c1`));
  assert.equal(HAPPENED_PREFIX, 'rv.happened.');
  s.setItem(`${HAPPENED_PREFIX}c2`, 'junk');
  assert.equal(happenedStore(s, 'c2').read(), 0);
  assert.equal(happenedStore(undefined, 'c1').read(), 0);
  assert.doesNotThrow(() => happenedStore(undefined, 'c1').write(2));
  const blocked = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } };
  assert.equal(happenedStore(blocked, 'c1').read(), 0);
  assert.doesNotThrow(() => happenedStore(blocked, 'c1').write(2));
});

test('the sheet words', () => {
  const src = read('js/views/realism-happened.js');
  for (const words of ['What happened', 'To the desk']) assert.ok(src.includes(`'${words}'`), words);
  assert.match(src, /days have passed/);
  assert.match(src, /new papers in your tray/);
});
