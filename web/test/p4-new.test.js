// Unit tests for the new-game screens' helpers, against the fixture. Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { timelinePoints } from '../js/views/new-game.js';
import { PLAY_STYLES, figureGroups, pickLock, searchState } from '../js/views/realism-cast.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const fixture = JSON.parse(readFileSync(join(WEB, 'test', 'fixtures', 'realism-seat.json'), 'utf8'));
const ISO = /\d{4}-\d{2}-\d{2}/;

const strings = (v) => (typeof v === 'string' ? [v] : v && typeof v === 'object' ? Object.values(v).flatMap(strings) : []);

test('the timeline is in date order, startable only with a world', () => {
  const points = timelinePoints([
    { date: '1944-06-06', label: 'D-Day', curated: false, world: null },
    ...fixture.timeline,
  ]);
  assert.deepEqual(points.map((p) => p.label), ['Autumn 1941', 'D-Day']);
  assert.deepEqual(points.map((p) => p.startable), [true, false]);
  assert.equal(points[0].when, '1 September 1941');
  assert.deepEqual(points.map((p) => p.world), [fixture.timeline[0].world, null]);
});

test('timeline wording has no underscore or ISO date', () => {
  for (const p of timelinePoints(fixture.timeline)) {
    for (const text of [p.label, p.when]) {
      assert.ok(!text.includes('_'));
      assert.ok(!ISO.test(text));
    }
  }
});

test('the figure list drops anyone already in the cast, and empty groups', () => {
  const groups = figureGroups(fixture.figures, ['franklin d. roosevelt']);
  assert.deepEqual(groups, []);
  const kept = figureGroups(fixture.figures, ['Someone Else']);
  assert.equal(kept[0].figures[0].name, 'Franklin D. Roosevelt');
});

test('groups run by side, then kind of power, and the input is not mutated', () => {
  const f = (name) => ({ name, title: 'T' });
  const input = [
    { side: 'United States', power: 'Military command', figures: [f('B')] },
    { side: 'Germany', power: 'Military command', figures: [f('C')] },
    { side: 'United States', power: 'Head of government', figures: [f('A')] },
  ];
  const order = figureGroups(input, []).map((g) => `${g.side}/${g.power}`);
  assert.deepEqual(order, [
    'Germany/Military command', 'United States/Head of government', 'United States/Military command']);
  assert.equal(input[0].side, 'United States');
});

test('the play styles read in words, Beginner, Guided, Free', () => {
  assert.deepEqual(PLAY_STYLES.map((s) => s.label), ['Beginner', 'Guided', 'Free']);
  for (const s of PLAY_STYLES) {
    assert.ok(!s.label.includes('_') && !s.line.includes('_'));
    assert.ok(!ISO.test(s.line));
  }
  assert.equal(PLAY_STYLES.find((s) => s.value === 'free').line, 'You write every order yourself.');
});

test('figure groups carry no underscore or ISO date', () => {
  for (const t of figureGroups(fixture.figures, []).flatMap(strings)) {
    assert.ok(!t.includes('_') && !ISO.test(t));
  }
});

const SOME = figureGroups(fixture.figures, []);

test('a search with no loading and a non-empty list shows the list', () => {
  assert.deepEqual(searchState({ loading: false, shown: SOME, query: 'roo' }), { kind: 'list' });
});

test('a search still out shows the loading line', () => {
  assert.deepEqual(searchState({ loading: true, shown: [], query: '' }),
    { kind: 'loading', text: 'Searching…' });
});

test('loading wins over a non-empty list', () => {
  assert.deepEqual(searchState({ loading: true, shown: SOME, query: 'roo' }),
    { kind: 'loading', text: 'Searching…' });
});

test('a name not on the list offers to draw it up', () => {
  assert.deepEqual(searchState({ loading: false, shown: [], query: 'Zed Quill' }), {
    kind: 'none',
    text: 'No one on the list matches “Zed Quill”.',
    offer: 'Draw up Zed Quill',
  });
});

test('an empty date with no query says no one is listed', () => {
  assert.deepEqual(searchState({ loading: false, shown: [], query: '' }),
    { kind: 'empty', text: 'No one is listed for this date.' });
  assert.deepEqual(searchState({ loading: false, shown: [], query: '   ' }),
    { kind: 'empty', text: 'No one is listed for this date.' });
});

test('a query with surrounding spaces is trimmed in the text and the offer', () => {
  const state = searchState({ loading: false, shown: [], query: '  Ada Lovelace  ' });
  assert.equal(state.text, 'No one on the list matches “Ada Lovelace”.');
  assert.equal(state.offer, 'Draw up Ada Lovelace');
});

test('search wording has no underscore or ISO date in any kind', () => {
  const states = [
    searchState({ loading: true, shown: [], query: '' }),
    searchState({ loading: false, shown: SOME, query: 'roo' }),
    searchState({ loading: false, shown: [], query: 'Zed Quill' }),
    searchState({ loading: false, shown: [], query: '' }),
  ];
  for (const t of states.flatMap(strings)) {
    assert.ok(!t.includes('_') && !ISO.test(t));
  }
});

test('a pick in flight refuses a second pick until it settles', async () => {
  const lock = pickLock();
  let calls = 0;
  let release;
  const first = lock.run(() => new Promise((r) => { calls += 1; release = r; }));
  assert.equal(lock.busy, true);
  assert.equal(await lock.run(async () => { calls += 1; }), false);
  assert.equal(calls, 1);
  release();
  assert.equal(await first, true);
  assert.equal(lock.busy, false);
  assert.equal(await lock.run(async () => { calls += 1; }), true);
  assert.equal(calls, 2);
});

test('a pick that throws still frees the lock', async () => {
  const lock = pickLock();
  await assert.rejects(lock.run(async () => { throw new Error('x'); }));
  assert.equal(lock.busy, false);
});
