// Spec for Train 2 unit TH2, written with contract K2: the unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

const css = read('css/effects.css').replace(/\/\*[\s\S]*?\*\//g, '');
const blocks = (text) => [...text.matchAll(/([^{}]+)\{/g)].map((m) => m[1].trim()).filter(Boolean);

test('every effect rule is scoped to effects on, or is a keyframe or the reduced-motion block', () => {
  const outer = css.replace(/@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, '').replace(/@media[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, '');
  const selectors = blocks(outer).flatMap((s) => s.split(','));
  assert.ok(selectors.length >= 3, 'scanlines, glow and the cursor');
  for (const sel of selectors) assert.match(sel.trim(), /^html\[data-effects="on"\]/, sel);
});

test('scanlines, glow and a blinking cursor, all stopped under reduced motion', () => {
  assert.match(css, /@keyframes/);
  assert.match(css, /text-shadow/);
  assert.match(css, /repeating-linear-gradient/);
  const reduced = /@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*)\}\s*$/m.exec(css);
  assert.ok(reduced, 'a reduced-motion block');
  assert.match(reduced[1], /animation:\s*none/);
});

test('linked from the page, colours only from tokens', () => {
  assert.match(read('index.html'), /href="\/css\/effects\.css"/);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b/);
});
