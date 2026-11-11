// Spec for Train 2 unit M1, written with contract K2: the unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { answerItems, optionAction } from '../js/views/realism-answer.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

const matter = (id, issuer, extra = {}) => ({ id, kind: 'Crisis', issuer, text: `Text ${id}`, issued: '1 October 1941',
  deadline: '15 October 1941', options: [{ label: 'Go', to: null, risk: '', historical: false, pick: `p-${id}`, taken: false }],
  plan: [], ...extra });

test('leader requests come first, then the desk matters, each with its choices', () => {
  const agenda = { style: 'beginner', items: [matter('m1', null), matter('r1', 'Winston Churchill'), matter('m2', null)], initiative: [] };
  const out = answerItems(agenda);
  assert.deepEqual(out.map((i) => i.id), ['r1', 'm1', 'm2']);
  assert.deepEqual(Object.keys(out[0]).sort(), ['choices', 'dates', 'heading', 'id', 'text']);
  assert.equal(out[0].heading, 'Crisis from Winston Churchill');
  assert.equal(out[1].heading, 'Crisis');
  assert.equal(out[0].text, 'Text r1');
  assert.equal(out[0].dates, 'Issued 1 October 1941 · Due by 15 October 1941');
  assert.equal(out[0].choices.kind, 'options');
  assert.equal(out[0].choices.options[0].pick, 'p-r1');
});

test('a guided item offers its plan and a free item offers nothing, but both are listed', () => {
  const plan = [{ label: 'Step', to: null, risk: '', historical: false, pick: 'g', taken: false }];
  assert.equal(answerItems({ style: 'guided', items: [matter('m', null, { options: [], plan })], initiative: [] })[0].choices.kind, 'plan');
  const free = answerItems({ style: 'free', items: [matter('m', null, { options: [] })], initiative: [] });
  assert.equal(free.length, 1);
  assert.deepEqual(free[0].choices, { kind: 'none', options: [] });
});

test('nothing waiting gives an empty list', () => {
  assert.deepEqual(answerItems({ style: 'beginner', items: [], initiative: [] }), []);
  assert.deepEqual(answerItems(fixture.agenda).map((i) => i.id), ['a1']);
});

test('an option is chosen once, then reads Filed', () => {
  assert.deepEqual(optionAction({ taken: false }), { word: 'Choose', button: true });
  assert.deepEqual(optionAction({ taken: true }), { word: 'Filed', button: false });
});

test('the section words', () => {
  const src = read('js/views/realism-answer.js');
  for (const words of ['Needs your answer', 'File this plan', 'Answer it with an order of your own.', 'Nothing is waiting on you. Your ideas are below.']) {
    assert.ok(src.includes(`'${words}'`), words);
  }
  assert.match(src, /act\('Filing it…', 'option', \{ pick/);
});
