// Spec for 15a unit U9 (lobby and account), written with the console contract: the unit makes
// it pass and never edits it. Sign-in, recovery codes, new game and Session Zero sit on console
// panels with semibold heads; the legacy war room takes tokens only.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const uncomment = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '');
const OWNS = ['css/app.css', 'css/p4-new.css'];
const rules = (css) => [...css.matchAll(/([^{}@]+)\{([^{}]*)\}/g)].map((m) => ({ sel: m[1].trim(), body: m[2] }));
const rule = (css, sel) => rules(css).filter((r) => r.sel.split(',').some((s) => s.trim() === sel)).map((r) => r.body).join(';');

test('the sign-in card is a console panel', () => {
  const card = rule(uncomment(read('css/app.css')), '.auth-card');
  assert.match(card, /background:\s*var\(--surface\)/);
  assert.match(card, /border:\s*1px solid var\(--rule\)/);
  assert.match(card, /border-radius:\s*var\(--radius\)/);
});

test('every heading in the console head face is semibold', () => {
  const light = [];
  for (const f of OWNS) {
    for (const r of rules(uncomment(read(f)))) {
      if (!/var\(--font-head\)/.test(r.body)) continue;
      if (!/font:\s*600\b|font-weight:\s*600\b/.test(r.body)) light.push(`${f}: ${r.sel}`);
    }
  }
  assert.deepEqual(light, []);
});

test('Session Zero and the cast cards sit on console panels', () => {
  const css = uncomment(read('css/app.css'));
  for (const sel of ['.char', '.aside-card', '.offers']) {
    assert.match(rule(css, sel), /border:\s*1px solid var\(--rule\)/, sel);
    assert.match(rule(css, sel), /border-radius:\s*var\(--radius\)/, sel);
  }
  assert.match(rule(css, '.rail-step[aria-current]'), /var\(--accent\)/, 'the current step keeps its accent mark');
  assert.match(rule(css, '.codes'), /var\(--font-code\)/, 'recovery codes in mono');
});

test('owned files: tokens only, no colour literal, no inline style, no theme selector', () => {
  for (const f of OWNS) {
    const css = uncomment(read(f));
    assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(/, f);
    assert.doesNotMatch(css, /style=|data-theme/, f);
  }
});
