// Spec for 15a unit U7 (select, dossiers, intro), written with the console contract: the unit
// makes it pass and never edits it. Headings use the console head face at semibold; cards and
// dossier sheets are rounded console panels; every portrait frame is a 3:4 duotone frame.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const uncomment = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '');
const OWNS = ['css/p5-castcard.css', 'css/p5-castdossier.css', 'css/p5-castlist.css', 'css/p5-dossier.css', 'css/p5-crawl.css', 'css/p5-intro.css'];
const rules = (css) => [...css.matchAll(/([^{}@]+)\{([^{}]*)\}/g)].map((m) => ({ sel: m[1].trim(), body: m[2] }));
const rule = (css, sel) => rules(css).filter((r) => r.sel.split(',').some((s) => s.trim() === sel)).map((r) => r.body).join(';');

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

test('cast cards and dossier sheets are rounded console panels', () => {
  const card = rule(uncomment(read('css/p5-castcard.css')), '.rl-cc');
  assert.match(card, /border-radius:\s*var\(--radius\)/);
  assert.match(card, /background:\s*var\(--surface\)/);
  const sheet = rule(uncomment(read('css/p5-castdossier.css')), '.rl-cd');
  assert.match(sheet, /border-radius:\s*var\(--radius\)/);
});

test('portrait frames are 3:4', () => {
  assert.match(uncomment(read('css/p5-castcard.css')), /\.rl-cc-figure \.portrait-frame\s*\{[^}]*aspect-ratio:\s*3 \/ 4/);
  assert.match(rule(uncomment(read('css/p5-castdossier.css')), '.rl-cd-portrait'), /aspect-ratio:\s*3 \/ 4/);
  assert.match(rule(uncomment(read('css/p5-dossier.css')), '.rl-dos-portrait'), /aspect-ratio:\s*3 \/ 4/);
});

test('the crawl reads in the console palette', () => {
  const crawl = uncomment(read('css/p5-crawl.css'));
  assert.match(crawl, /var\(--accent\)|var\(--fg-strong\)/);
  assert.doesNotMatch(crawl, /Libre Caslon|serif/, 'the period face stays with the press');
});

test('owned files: tokens only, no colour literal, no inline style', () => {
  for (const f of OWNS) {
    const css = uncomment(read(f));
    assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(/, f);
    assert.doesNotMatch(css, /style=/, f);
  }
});
