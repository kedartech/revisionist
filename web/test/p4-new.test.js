// Unit tests for the new-game screens' helpers, against the fixture. Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { timelinePoints } from '../js/views/new-game.js';
import { PLAY_STYLES, figureGroups } from '../js/views/realism-cast.js';

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
