// Spec for Train 2 unit V (contract K2), revised for unit Q2 (contract KQ): at most eight
// lines a wake, the window moving on each wake. The unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import * as overlay from '../js/views/realism-overlay.js';
import { QUIET_LINES, overlayLines, wakeOverlay } from '../js/views/realism-overlay.js';
import { installDom } from './dom-fake.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

test('the setting gives the lines: facts, then dated events', () => {
  assert.deepEqual(overlayLines(fixture.setting), [
    ...fixture.setting.facts,
    '17 October 1941: USS Kearny is torpedoed off Iceland.',
    '31 October 1941: USS Reuben James is sunk.',
  ]);
});

test('with no setting text, three fixed period-neutral lines', () => {
  assert.equal(QUIET_LINES.length, 3);
  assert.ok(QUIET_LINES.every((l) => typeof l === 'string' && l.length > 10 && !/\d{4}/.test(l)));
  assert.deepEqual(overlayLines({ situation: null, sides: [], crawl: [], facts: [], dates: [] }), [...QUIET_LINES]);
  assert.deepEqual(overlayLines(null), [...QUIET_LINES]);
});

test('the layer holds the room, and moves by CSS only', () => {
  const src = read('js/views/realism-overlay.js');
  assert.match(src, /'alertdialog'/);
  assert.match(src, /'aria-busy'/);
  assert.doesNotMatch(src, /setInterval|setTimeout|requestAnimationFrame/);
  const css = read('css/p5-overlay.css');
  assert.match(css, /@keyframes/);
  assert.match(css, /prefers-reduced-motion/);
});

const many = (n) => ({ facts: Array.from({ length: n }, (_, i) => `Line ${i + 1}.`), dates: [] });
const nums = (lines) => lines.map((l) => Number(l.match(/\d+/)[0]));

test('eight slots; eight lines or fewer come out as they are on every wake', () => {
  assert.equal(overlay.OVERLAY_SLOTS, 8);
  const five = overlayLines(fixture.setting);
  for (const turn of [0, 1, 2, 7]) assert.deepEqual(overlayLines(fixture.setting, turn), five);
  assert.deepEqual(overlayLines(many(8), 3), many(8).facts);
});

test('more than eight: eight in a row from (turn * 8) % n, wrapping', () => {
  const s = many(18);
  assert.deepEqual(nums(overlayLines(s)), [1, 2, 3, 4, 5, 6, 7, 8]);
  assert.deepEqual(nums(overlayLines(s, 0)), [1, 2, 3, 4, 5, 6, 7, 8]);
  assert.deepEqual(nums(overlayLines(s, 1)), [9, 10, 11, 12, 13, 14, 15, 16]);
  assert.deepEqual(nums(overlayLines(s, 2)), [17, 18, 1, 2, 3, 4, 5, 6]);
  assert.deepEqual(nums(overlayLines(s, 3)), [7, 8, 9, 10, 11, 12, 13, 14]);
  assert.deepEqual(nums(overlayLines(many(9), 1)), [9, 1, 2, 3, 4, 5, 6, 7]);
});

test('every line is shown within ceil(n / 8) wakes', () => {
  for (const n of [9, 16, 17, 18, 25, 40]) {
    const seen = new Set();
    for (let turn = 0; turn < Math.ceil(n / 8); turn += 1) for (const l of overlayLines(many(n), turn)) seen.add(l);
    assert.equal(seen.size, n, `n=${n}`);
  }
});

test('the layer never draws more than eight lines', () => {
  installDom();
  const lines = many(18).facts;
  const layer = wakeOverlay({ message: 'The day is running', lines });
  assert.equal(layer.querySelectorAll('li').length, 8);
  assert.deepEqual(layer.querySelectorAll('li').map((li) => li.textContent), lines.slice(0, 8));
  assert.equal(wakeOverlay({ message: 'm', lines: lines.slice(0, 3) }).querySelectorAll('li').length, 3);
});

test('one delay rule per slot, a cycle of eight times three seconds, no style attribute', () => {
  const css = read('css/p5-overlay.css');
  const slots = [...css.matchAll(/\.rl-ovl-line:nth-child\((\d+)\)\s*\{\s*animation-delay:\s*([\d.]+)s;\s*\}/g)];
  assert.deepEqual(slots.map((m) => Number(m[1])), [1, 2, 3, 4, 5, 6, 7, 8]);
  assert.deepEqual(slots.map((m) => Number(m[2])), [0, 3, 6, 9, 12, 15, 18, 21]);
  assert.match(css, /animation: rl-ovl-show 24s linear infinite both;/);
  const src = read('js/views/realism-overlay.js');
  assert.doesNotMatch(src, /style=|\.style\.|'style'/);
});
