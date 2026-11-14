// Messages opens larger on a desktop screen: from 1200 px the panel is wider and taller; under
// 1200 px the console theme's layout (a side panel from 768, a full screen under 768) stands.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const uncomment = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '');
const css = uncomment(read('css/p5-chat.css'));

/** The body of the first `@media <query> { ... }` block in `text`, or null. */
function media(text, query) {
  const at = text.indexOf(`@media ${query}`);
  if (at < 0) return null;
  let depth = 0;
  for (let i = text.indexOf('{', at); i < text.length; i++) {
    if (text[i] === '{') depth++;
    else if (text[i] === '}' && --depth === 0) return text.slice(text.indexOf('{', at) + 1, i);
  }
  return null;
}

/** The declarations of `.rl-msgr-panel` in `text` (top level only), as a map. */
function panel(text) {
  const out = {};
  for (const m of text.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (!m[1].split(',').some((s) => s.trim() === '.rl-msgr-panel')) continue;
    for (const d of m[2].split(';')) {
      const [k, ...v] = d.split(':');
      if (k.trim()) out[k.trim()] = v.join(':').trim();
    }
  }
  return out;
}

/** The largest length in px a declaration can reach, reading px and rem (16 px). */
function largest(value) {
  const sizes = [...value.matchAll(/([\d.]+)(px|rem)\b/g)].map(([, n, u]) => Number(n) * (u === 'rem' ? 16 : 1));
  return Math.max(0, ...sizes);
}

const desk = () => media(css, '(min-width: 1200px)');

test('from 1200 px the panel is wider than the side panel and has a set height', () => {
  const block = desk();
  assert.ok(block, 'a block from 1200 px');
  const base = panel(css.slice(0, css.indexOf('@media')));
  const wide = panel(block);
  assert.ok(wide.width, 'a width from 1200 px');
  assert.ok(largest(wide.width) > largest(base.width), `${wide.width} is wider than ${base.width}`);
  assert.ok(wide.height, 'a height from 1200 px, so a short thread opens at full size');
  assert.ok(largest(wide.height) > largest(base['max-height']), `${wide.height} is taller than ${base['max-height']}`);
  assert.match(wide.height, /vh/, 'the height follows the screen, so the composer stays on it');
  assert.equal(wide['max-height'], 'none', 'the side panel cap does not hold the desktop height down');
});

test('under 1200 px nothing changes: the only breakpoints are the phone ones and the desktop one', () => {
  const queries = [...css.matchAll(/@media\s*([^{]+)\{/g)].map((m) => m[1].trim()).sort();
  assert.deepEqual(queries, ['(max-width: 480px)', '(max-width: 767px)', '(min-width: 1200px)']);
  assert.equal(panel(css.slice(0, css.indexOf('@media'))).width, '380px');
});

test('the desktop size is tokens and lengths only, no colour', () => {
  assert.doesNotMatch(desk() ?? '', /#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/);
});
