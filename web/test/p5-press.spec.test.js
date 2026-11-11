// Spec for Train 2 unit TH3, written with contract K2: the unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

const css = read('css/p5-press.css');

test('a press paper keeps its serif and paper tone in a frame headed INTERCEPT', () => {
  assert.match(css, /\.rl-page-press\b/);
  assert.match(css, /INTERCEPT/);
  assert.match(css, /var\(--font-read\)/);
  assert.match(css, /border/);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b/);
});

test('the paper view marks a press paper', () => {
  assert.match(read('js/views/realism.js'), /item\.kind === 'press' \? 'rl-page rl-page-press'/);
});
