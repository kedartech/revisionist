// Spec for Train 3 unit P2, written with contract K3: the unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { sideChips, tableRows, figureGroups } from '../js/views/realism-castlist.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-cast.json'));
const ISO = /\b\d{4}-\d{2}-\d{2}\b/;

const cast = fixture.roster.map((c) => c.name);
const groups = figureGroups(fixture.figures, cast);

test('chips: All first with every figure, then each side in order with its count', () => {
  assert.deepEqual(sideChips(groups), [
    { side: null, label: 'All', count: 5 },
    { side: 'Germany', label: 'Germany', count: 1 },
    { side: 'United Kingdom', label: 'United Kingdom', count: 1 },
    { side: 'United States', label: 'United States', count: 3 },
  ]);
  assert.deepEqual(sideChips([]), []);
});

test('rows leave out the cast and follow the groups', () => {
  const rows = tableRows(fixture.figures, { cast });
  assert.deepEqual(rows.map((r) => r.name), ['Karl Dönitz', 'Sir Dudley Pound', 'Sam Rayburn', 'Harold R. Stark', 'Ernest J. King']);
  assert.deepEqual(rows[1], { name: 'Sir Dudley Pound', title: 'First Sea Lord', side: 'United Kingdom', power: 'Navy' });
  assert.ok(!rows.some((r) => r.name === 'Franklin D. Roosevelt'));
});

test('a chosen side keeps its rows only; null is everyone', () => {
  const us = tableRows(fixture.figures, { cast, side: 'United States' });
  assert.deepEqual(us.map((r) => r.name), ['Sam Rayburn', 'Harold R. Stark', 'Ernest J. King']);
  assert.equal(tableRows(fixture.figures, { cast, side: null }).length, 5);
  assert.deepEqual(tableRows(fixture.figures, { cast, side: 'Italy' }), []);
});

test('a missing title is null, and the input is not changed', () => {
  const before = JSON.stringify(fixture.figures);
  const rows = tableRows([{ side: 'Italy', power: 'Navy', figures: [{ name: 'Arturo Riccardi' }] }], { cast: [] });
  assert.equal(rows[0].title, null);
  assert.equal(JSON.stringify(fixture.figures), before);
});

test('the view: search, chips as tabs, one table, the draw offer', () => {
  const src = read('js/views/realism-castlist.js');
  for (const s of [/'tablist'/, /'tab'/, /aria-selected/, /'table'/, /Find someone/, /searchState\(/, /onDraw\(/, /onOpen\(/, /'status'/, /type: 'search'/]) {
    assert.match(src, s);
  }
});

test('no HTML parsing, no inline style, no stub left, linked and scoped', () => {
  const src = read('js/views/realism-castlist.js');
  assert.doesNotMatch(src, /innerHTML|outerHTML|insertAdjacentHTML|style=|\.style\.|contract stub/);
  const css = read('css/p5-castlist.css').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.doesNotMatch(read('css/p5-castlist.css'), /contract stub/);
  assert.ok(css.trim().length > 0, 'the stylesheet has rules');
  assert.ok(read('index.html').includes('href="/css/p5-castlist.css"'), 'linked from the page');
  const outer = css.replace(/@(media|container|supports)[^{]+\{/g, '').replace(/@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, '');
  const sels = [...outer.matchAll(/([^{}]+)\{/g)].flatMap((m) => m[1].split(',')).map((s) => s.trim()).filter(Boolean);
  for (const sel of sels) assert.match(sel, /\.rl-cl/, sel);
});
