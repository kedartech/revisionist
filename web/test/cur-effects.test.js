// One cursor, and the screen effects built in (run plan item, 14 Nov). The blinking cursor sits
// on the game's name alone; scanlines with the vignette, the heading glow, the cursor and the
// portrait scanlines are always on, with no setting; reduced motion stops the blink and high
// contrast drops both scanline layers.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { header } from '../js/views/frame.js';
import { installDom, words } from './dom-fake.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const uncomment = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '');
const effects = uncomment(read('css/effects.css'));
const portrait = uncomment(read('css/p5-portrait.css'));

/** Rules outside any at-rule block: { sel, body }. */
function topRules(css) {
  const flat = css
    .replace(/@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, '')
    .replace(/@media[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, '');
  return [...flat.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({ sel: m[1].trim(), body: m[2] }));
}

/** The inside of `@media <query> { ... }`, or null. */
function media(css, query) {
  const at = css.indexOf(`@media ${query}`);
  if (at < 0) return null;
  const open = css.indexOf('{', at);
  let depth = 0;
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === '{') depth += 1;
    else if (css[i] === '}' && (depth -= 1) === 0) return css.slice(open + 1, i);
  }
  return null;
}

const rulesIn = (block) => [...block.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({ sel: m[1].trim(), body: m[2] }));
const sels = (r) => r.sel.split(',').map((s) => s.trim());

/** The element selectors the blinking cursor is drawn after. */
function cursorTargets() {
  const blink = topRules(effects).filter((r) => /animation\s*:[^;]*rl-cursor-blink/.test(r.body));
  assert.ok(blink.length >= 1, 'a rule draws the blinking cursor');
  return blink.flatMap(sels).map((s) => {
    assert.match(s, /::after$/, s);
    return s.replace(/::after$/, '');
  });
}

function roomHeader() {
  installDom();
  const host = document.createElement('div');
  host.append(header({
    me: { account: { handle: 'josh' } },
    game: { name: 'Autumn 1941' },
    role: 'Campaign',
    identity: { name: 'Cordell Hull', office: 'Secretary of State', principal: 'Roosevelt' },
    onSetting: () => {},
    onIdentity: () => {},
    refresh: async () => {},
    signOut: () => {},
    effects: { effects: true, onChange: () => {} },
  }));
  return host;
}

test('the room header holds exactly one cursor-carrying title, and it is the game name', () => {
  const host = roomHeader();
  const carriers = new Set(cursorTargets().flatMap((s) => host.querySelectorAll(s)));
  assert.equal(carriers.size, 1, 'one element carries the cursor');
  const [el] = carriers;
  assert.equal(words(el), 'Autumn 1941');
  assert.ok(el.classList.contains('title'), 'the cursor sits on a header title');
  const playing = host.querySelector('.identity .title');
  assert.ok(playing, 'the playing-as name is drawn');
  assert.ok(!carriers.has(playing), 'the playing-as name carries no cursor');
});

test('no screen effects setting is left: no data-effects selector, toggle or stored value', () => {
  assert.doesNotMatch(effects, /data-effects/);
  assert.doesNotMatch(portrait, /data-effects/);
  assert.equal(roomHeader().querySelectorAll('.rl-effects').length, 0, 'no Screen effects button');
  const app = read('js/app.js');
  assert.doesNotMatch(app, /dataset\.effects/);
  const js = (dir) => readdirSync(join(WEB, dir)).flatMap((n) => {
    const p = join(dir, n);
    return statSync(join(WEB, p)).isDirectory() ? js(p) : n.endsWith('.js') ? [p] : [];
  });
  for (const f of js('js')) assert.doesNotMatch(read(f), /rv\.effects|data-effects|dataset\.effects/, f);
  for (const f of ['css/c-header.css']) assert.doesNotMatch(read(f), /rl-effects/, f);
});

test('scanlines, vignette, glow and cursor are unconditional', () => {
  const top = topRules(effects);
  const screen = top.filter((r) => sels(r).includes('body::after')).map((r) => r.body).join(';');
  assert.match(screen, /repeating-linear-gradient/, 'page scanlines');
  assert.match(screen, /radial-gradient/, 'the vignette');
  const glow = top.filter((r) => /text-shadow/.test(r.body)).flatMap(sels);
  for (const s of ['h1', 'h2', 'h3', '.title']) assert.ok(glow.includes(s), `glow on ${s}`);
  const scan = topRules(portrait).filter((r) => sels(r).includes('.portrait-frame::before'));
  assert.ok(scan.some((r) => /repeating-linear-gradient/.test(r.body)), 'portrait scanlines');
});

test('reduced motion stops the blink; high contrast drops both scanline layers', () => {
  const reduced = media(effects, '(prefers-reduced-motion: reduce)');
  assert.ok(reduced, 'a reduced-motion block');
  const still = rulesIn(reduced).filter((r) => /animation\s*:\s*none/.test(r.body)).flatMap(sels);
  for (const s of cursorTargets()) assert.ok(still.includes(`${s}::after`), `${s}::after stops blinking`);
  const off = (css, sel) => {
    const block = media(css, '(prefers-contrast: more)');
    assert.ok(block, 'a prefers-contrast: more block');
    return rulesIn(block).some((r) => sels(r).includes(sel) && /content\s*:\s*none/.test(r.body));
  };
  assert.ok(off(effects, 'body::after'), 'the page scanlines go under high contrast');
  assert.ok(off(portrait, '.portrait-frame::before'), 'the portrait scanlines go under high contrast');
});
