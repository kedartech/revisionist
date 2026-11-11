// Spec for Train 3 unit TH4, written with contract K3: the unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { portraitSrc } from '../js/views/realism-dossier.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const raw = read('css/p5-portrait.css');
const css = raw.replace(/\/\*[\s\S]*?\*\//g, '');
const rules = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({ sel: m[1].trim(), body: m[2] }));

test('a portrait path only from a bare lowercase image name', () => {
  assert.equal(portraitSrc('roosevelt.jpg'), '/assets/portraits/roosevelt.jpg');
  assert.equal(portraitSrc('sir-dudley-pound.webp'), '/assets/portraits/sir-dudley-pound.webp');
  for (const bad of ['../x.jpg', '/etc/passwd', 'a/b.jpg', 'A.jpg', 'x.gif', 'x.jpg?y', '', null, undefined, 3]) {
    assert.equal(portraitSrc(bad), null, String(bad));
  }
});

test('the terminal look: a green duotone on the image and scanlines over the frame', () => {
  const img = rules.filter((r) => /\.portrait\b(?![-\w])/.test(r.sel) && !/data-theme="paper"/.test(r.sel));
  assert.ok(img.some((r) => /filter\s*:/.test(r.body)), 'a filter on .portrait');
  const frame = rules.filter((r) => /\.portrait-frame::after/.test(r.sel));
  assert.ok(frame.some((r) => /repeating-linear-gradient/.test(r.body)), 'scanlines on .portrait-frame::after');
});

test('none of it under paper, and a monogram is left alone', () => {
  const paper = rules.filter((r) => /html\[data-theme="paper"\]/.test(r.sel));
  assert.ok(paper.some((r) => /\.portrait\b/.test(r.sel) && /filter\s*:\s*none/.test(r.body)), 'paper resets the filter');
  assert.ok(paper.some((r) => /\.portrait-frame::after/.test(r.sel) && /(content\s*:\s*none|display\s*:\s*none)/.test(r.body)), 'paper drops the scanlines');
  assert.ok(!rules.some((r) => /portrait-mono/.test(r.sel) && /filter/.test(r.body)), 'no filter on a monogram');
});

test('scoped, tokens only, linked, no stub left', () => {
  assert.doesNotMatch(raw, /contract stub/);
  assert.match(read('index.html'), /href="\/css\/p5-portrait\.css"/);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(/);
  for (const { sel } of rules) {
    if (/^(from|to|\d+%)$/.test(sel) || sel.startsWith('@')) continue;
    for (const s of sel.split(',')) assert.match(s.trim(), /\.portrait/, s);
  }
});
