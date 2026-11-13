// Portraits in the console theme: a phosphor duotone from two tokens, so every photograph
// reads as one set. The frame is filled with --duo-light, the grey image multiplies onto it,
// ::after lightens the blacks to --duo-dark and ::before draws the scanlines.
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
const on = (re) => rules.filter((r) => r.sel.split(',').some((s) => re.test(s.trim())));
const has = (list, re) => list.some((r) => re.test(r.body));

test('a portrait path only from a bare lowercase image name', () => {
  assert.equal(portraitSrc('roosevelt.jpg'), '/assets/portraits/roosevelt.jpg');
  assert.equal(portraitSrc('sir-dudley-pound.webp'), '/assets/portraits/sir-dudley-pound.webp');
  for (const bad of ['../x.jpg', '/etc/passwd', 'a/b.jpg', 'A.jpg', 'x.gif', 'x.jpg?y', '', null, undefined, 3]) {
    assert.equal(portraitSrc(bad), null, String(bad));
  }
});

test('the frame is filled with the light tone and isolates its blend', () => {
  const frame = on(/^\.portrait-frame$/);
  assert.ok(has(frame, /background\s*:\s*var\(--duo-light\)/), 'frame filled with --duo-light');
  assert.ok(has(frame, /isolation\s*:\s*isolate/), 'isolation: isolate');
  assert.ok(has(frame, /position\s*:\s*relative/), 'the frame places its layers');
});

test('the grey image multiplies onto the frame', () => {
  const img = on(/\.portrait-frame\s*>\s*\.portrait$/);
  assert.ok(has(img, /filter\s*:\s*grayscale\(1\)/), 'a grey filter on the image');
  assert.ok(has(img, /mix-blend-mode\s*:\s*multiply/), 'the blend sits on the image itself');
});

test('::after lightens the blacks to the dark tone and ::before draws the scanlines', () => {
  const after = on(/^\.portrait-frame::after$/);
  assert.ok(has(after, /background\s*:\s*var\(--duo-dark\)/), '::after is --duo-dark');
  assert.ok(has(after, /mix-blend-mode\s*:\s*lighten/), '::after lightens');
  const before = on(/^\.portrait-frame::before$/);
  assert.ok(has(before, /repeating-linear-gradient/), 'scanlines on ::before');
  assert.ok(has(before, /z-index\s*:\s*1/), 'the scanlines sit over the blend');
  const off = on(/^html\[data-effects="off"\] \.portrait-frame::before$/);
  assert.ok(has(off, /content\s*:\s*none/), 'the scanlines go with the screen effects');
});

test('one theme only, and a monogram is left alone', () => {
  assert.doesNotMatch(css, /data-theme/);
  assert.ok(!rules.some((r) => /portrait-mono/.test(r.sel) && /filter|blend/.test(r.body)), 'no filter on a monogram');
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
