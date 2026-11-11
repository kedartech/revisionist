// Spec for Train 2 unit V, written with contract K2: the unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { QUIET_LINES, overlayLines } from '../js/views/realism-overlay.js';

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
