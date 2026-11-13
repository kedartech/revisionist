// Spec for 15a unit U8 (sheets and overlays), written with the console contract: the unit makes
// it pass and never edits it. The press keeps its period face inside a violet intercept frame;
// sheet heads read like the kit panel head; the CRT scanlines soften and gain a light vignette,
// still only while the screen effects are on.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const uncomment = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '');
const OWNS = ['css/p5-overlay.css', 'css/p5-happened.css', 'css/p4-reveal.css', 'css/p5-press.css', 'css/p4-news.css', 'css/p5-wake.css', 'css/effects.css'];
const rules = (css) => [...css.matchAll(/([^{}@]+)\{([^{}]*)\}/g)].map((m) => ({ sel: m[1].trim(), body: m[2] }));
const rule = (css, sel) => rules(css).filter((r) => r.sel.split(',').some((s) => s.trim() === sel)).map((r) => r.body).join(';');

test('the press keeps its period face inside a violet intercept frame', () => {
  const press = uncomment(read('css/p5-press.css'));
  const page = rule(press, '.rl-page.rl-page-press');
  assert.match(page, /font-family:\s*var\(--font-press\)/);
  assert.match(page, /border:\s*1px dashed var\(--intel\)/);
  assert.match(page, /background:\s*var\(--intel-soft\)/);
  assert.match(rule(press, '.rl-page-press::before'), /color:\s*var\(--intel\)/, 'the INTERCEPT mark in the intel colour');
});

test('sheet heads read like the kit panel head', () => {
  const hap = rule(uncomment(read('css/p5-happened.css')), '.rl-hap h2');
  assert.match(hap, /var\(--font-chrome\)/);
  assert.match(hap, /text-transform:\s*uppercase/);
  assert.match(hap, /letter-spacing/);
  const ovl = rule(uncomment(read('css/p5-overlay.css')), '.rl-ovl-msg');
  assert.match(ovl, /font:\s*600\b/);
});

test('softer scanlines and a light vignette, only while the effects are on', () => {
  const fx = uncomment(read('css/effects.css'));
  const screen = rule(fx, 'html[data-effects="on"] body::after');
  assert.match(screen, /repeating-linear-gradient/);
  assert.match(screen, /radial-gradient/, 'a vignette');
  const mix = /color-mix\(in srgb, var\(--fg\) (\d+)%/.exec(screen);
  assert.ok(mix && Number(mix[1]) <= 4, 'the scanline at 4% of the text colour or less');
});

test('owned files: tokens only, no colour literal, no inline style', () => {
  for (const f of OWNS) {
    const css = uncomment(read(f));
    assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(/, f);
    assert.doesNotMatch(css, /style=/, f);
  }
});
