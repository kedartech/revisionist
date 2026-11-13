// The pick-confirm foot. When the confirm step opens, the dossier dialog focuses "Yes, play ..."
// and the browser scrolls only far enough to show the focused button. A scroll margin under the
// foot buttons, in spacing tokens, makes that scroll bring the rest of the foot (the wrapped
// "Close" row on wide screens) and the dialog's own padding into view, so the buttons have room
// under them.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const uncomment = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '');
const rules = (css) => [...css.matchAll(/([^{}@]+)\{([^{}]*)\}/g)].map((m) => ({ sel: m[1].trim(), body: m[2] }));
const SHEET = uncomment(read('css/p5-castdossier.css'));
const SPACE = Object.fromEntries(
  [...read('css/tokens.css').matchAll(/--(space-\d+):\s*(\d+)px/g)].map((m) => [m[1], Number(m[2])]),
);

/** The scroll-margin-block-end value of each rule whose selector list names `.rl-cd-foot button`. */
const footMargins = () => rules(SHEET)
  .filter((r) => r.sel.split(',').some((s) => s.trim() === '.rl-cd-foot button'))
  .map((r) => r.body.match(/scroll-margin-block-end:\s*([^;]+);/)?.[1].trim())
  .filter((v) => v !== undefined);

/** Resolves `var(--space-N)` or `calc(var(--space-N) + ...)`; null for anything else. */
const resolve = (value) => {
  const inner = value.replace(/^calc\((.*)\)$/, '$1');
  const parts = inner.split('+').map((p) => p.trim());
  let px = 0;
  for (const p of parts) {
    const m = p.match(/^var\(--(space-\d+)\)$/);
    if (!m || SPACE[m[1]] === undefined) return null;
    px += SPACE[m[1]];
  }
  return px;
};

test('the foot buttons keep room under them when focus scrolls the dialog', () => {
  const margins = footMargins();
  assert.equal(margins.length, 1, 'one scroll-margin-block-end rule on .rl-cd-foot button, not overridden');
  const px = resolve(margins[0]);
  assert.notEqual(px, null, `spacing tokens only, got "${margins[0]}"`);
  // At 768 to 1440 px the wrapped "Close" row plus the dialog padding sit 69 px under the
  // primary button; the margin covers that so the focus scroll lands at the dialog's end.
  assert.ok(px >= 69, `margin ${px}px covers the last button row and the dialog padding`);
});

test('the margin sits on the foot buttons, not on the dialog padding', () => {
  const sheet = rules(SHEET).find((r) => r.sel === '.rl-cd')?.body ?? '';
  assert.match(sheet, /padding:\s*1\.25rem;/, 'the dialog padding is unchanged');
  assert.doesNotMatch(sheet, /scroll-padding/, 'no scroll padding on the whole dialog');
});
