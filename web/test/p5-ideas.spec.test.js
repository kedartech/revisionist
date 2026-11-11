// Spec for Train 2 unit M2, written with contract K2: the unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { ideas } from '../js/views/realism-ideas.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

const opt = (label, extra = {}) => ({ label, to: null, risk: '', historical: false, pick: `p-${label}`, taken: false, ...extra });
const draft = (label) => ({ label, terms: [], lever: 'send_bill' });

test('options first, then drafts, each tagged with its type', () => {
  const out = ideas({ style: 'beginner', items: [], initiative: [opt('A'), opt('B')] }, { drafts: [draft('C')] });
  assert.deepEqual(out.map((i) => [i.type, i.label]), [['option', 'A'], ['option', 'B'], ['draft', 'C']]);
  assert.equal(out[0].pick, 'p-A');
  assert.equal(out[2].lever, 'send_bill');
});

test('a draft that repeats an option is dropped, case and spacing ignored', () => {
  const out = ideas({ style: 'beginner', items: [], initiative: [opt('Ask the Speaker for a count')] },
    { drafts: [draft('  ask the  speaker for a COUNT '), draft('Something else')] });
  assert.deepEqual(out.map((i) => i.label), ['Ask the Speaker for a count', 'Something else']);
});

test('taken options go last, in their order', () => {
  const out = ideas({ style: 'beginner', items: [], initiative: [opt('A', { taken: true }), opt('B'), opt('C', { taken: true })] }, null);
  assert.deepEqual(out.map((i) => i.label), ['B', 'A', 'C']);
});

test('no brief, no drafts; the fixture lists its initiative', () => {
  assert.deepEqual(ideas({ style: 'free', items: [], initiative: [] }, null), []);
  assert.deepEqual(ideas(fixture.agenda, null).map((i) => i.label), ['Ask the Speaker for a count']);
});

test('the section words', () => {
  const src = read('js/views/realism-ideas.js');
  for (const words of ['Ideas', 'Choose', 'Filed', 'Open the form']) assert.ok(src.includes(`'${words}'`), words);
});
