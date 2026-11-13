// Spec for 15a unit U6 (messages), written with the console contract: the unit makes it pass and
// never edits it. The messenger is a console panel; my messages sit on the soft accent ground,
// theirs on the second surface; on a phone the panel fills the screen; text is never dimmed with
// opacity.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const uncomment = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '');
const OWNS = ['css/p5-chat.css', 'css/p5-chatlist.css', 'css/p5-thread.css', 'css/p5-typing.css', 'css/p5-contacts.css'];
/** The body of every top-level rule whose selector list names `sel` exactly. */
const rule = (css, sel) => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
  .filter((m) => m[1].split(',').some((s) => s.trim() === sel)).map((m) => m[2]).join(';');
/** The body of the first `@media <query> { ... }` block in `css`, or null. */
function media(css, query) {
  const at = css.indexOf(`@media ${query}`);
  if (at < 0) return null;
  let depth = 0;
  for (let i = css.indexOf('{', at); i < css.length; i++) {
    if (css[i] === '{') depth++;
    else if (css[i] === '}' && --depth === 0) return css.slice(css.indexOf('{', at) + 1, i);
  }
  return null;
}

test('the messenger is a console panel', () => {
  const panel = rule(uncomment(read('css/p5-chat.css')), '.rl-msgr-panel');
  assert.match(panel, /background:\s*var\(--surface\)/);
  assert.match(panel, /border:\s*1px solid var\(--rule\)/);
  assert.match(panel, /border-radius:\s*var\(--radius\)/);
});

test('my messages on the soft accent ground, theirs on the second surface', () => {
  const css = uncomment(read('css/p5-thread.css'));
  const mine = rule(css, '.rl-th-bubble.mine');
  assert.match(mine, /background:\s*var\(--accent-soft\)/);
  assert.match(mine, /color:\s*var\(--fg-strong\)/);
  assert.match(rule(css, '.rl-th-bubble.theirs'), /background:\s*var\(--surface-2\)/);
});

test('on a phone the panel fills the screen and keeps its close in the header', () => {
  const phone = media(uncomment(read('css/p5-chat.css')), '(max-width: 767px)');
  assert.ok(phone, 'a block under 768 px');
  assert.match(phone, /\.rl-msgr-panel\s*\{[^}]*inset:\s*0/);
  assert.match(phone, /\.rl-msgr-head\s*\{[^}]*min-height:\s*44px/);
});

test('no text is dimmed with opacity', () => {
  for (const f of OWNS.filter((n) => !n.includes('typing'))) assert.doesNotMatch(uncomment(read(f)), /opacity\s*:/, f);
});

test('owned files: tokens only, no colour literal', () => {
  for (const f of OWNS) assert.doesNotMatch(uncomment(read(f)), /#[0-9a-fA-F]{3,8}\b|rgba?\(/, f);
});
