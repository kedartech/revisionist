// Unit tests for the reach panel's pure helpers, against the fixture. Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { channelsLine, collapseSplit, reachGroups } from '../js/views/realism-reach.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const fixture = JSON.parse(readFileSync(join(WEB, 'test', 'fixtures', 'realism-seat.json'), 'utf8'));
const reach = fixture.reach;
const EMPTY = { inner_circle: [], government: [], foreign: [], other: [] };

test('reachGroups keeps the four groups in order', () => {
  const groups = reachGroups(reach);
  assert.deepEqual(groups.map((g) => g.heading), ['Inner circle', 'Government', 'Foreign', 'Other']);
  assert.deepEqual(groups[0].people, reach.inner_circle);
});

test('reachGroups drops empty groups and returns nothing when all are empty', () => {
  assert.deepEqual(reachGroups(EMPTY), []);
  assert.deepEqual(reachGroups({ ...EMPTY, foreign: reach.foreign }).map((g) => g.heading), ['Foreign']);
  assert.deepEqual(reachGroups({ ...EMPTY, other: reach.other, inner_circle: reach.inner_circle })
    .map((g) => g.heading), ['Inner circle', 'Other']);
});

test('channelsLine joins channels in the order given', () => {
  assert.equal(channelsLine(['In person', 'Cable']), 'In person · Cable');
  assert.equal(channelsLine(['Letter']), 'Letter');
  assert.equal(channelsLine([]), '');
  assert.equal(channelsLine(null), '');
});

test('collapseSplit shows the first eight and folds the rest', () => {
  const people = Array.from({ length: 11 }, (_, i) => ({ name: `Person ${i}` }));
  const { shown, rest } = collapseSplit(people);
  assert.equal(shown.length, 8);
  assert.equal(rest.length, 3);
  assert.deepEqual([...shown, ...rest], people);
});

test('collapseSplit folds nothing for eight or fewer', () => {
  const people = Array.from({ length: 8 }, (_, i) => ({ name: `Person ${i}` }));
  assert.deepEqual(collapseSplit(people), { shown: people, rest: [] });
});

test('no string the panel shows contains an underscore', () => {
  const strings = ['Who you can reach'];
  for (const g of reachGroups(reach)) {
    strings.push(g.heading);
    for (const p of g.people) strings.push(p.name, p.title ?? '', channelsLine(p.channels));
  }
  for (const s of strings) assert.doesNotMatch(s, /_/, s);
});
