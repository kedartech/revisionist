// The theme contract: semantic tokens only, defined for both themes, text pairs that pass AA.
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { EFFECTS_KEY, THEMES, applyTheme, effectsOn, themeName } from '../js/theme.js';

const CSS = fileURLToPath(new URL('../css', import.meta.url));
const read = (name) => readFileSync(join(CSS, name), 'utf8');
const sheets = readdirSync(CSS).filter((n) => n.endsWith('.css'));

/** Custom properties declared in a block of tokens.css. */
function declared(block) {
  return Object.fromEntries([...block.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
}

function themes() {
  const src = read('tokens.css').replace(/\/\*[\s\S]*?\*\//g, '');
  const paper = src.match(/html\[data-theme="paper"\]\s*\{([\s\S]*?)\n\}/);
  const root = src.match(/:root\s*\{([\s\S]*?)\n\}/);
  assert.ok(root, 'tokens.css has a :root block for the terminal theme');
  assert.ok(paper, 'tokens.css has an html[data-theme="paper"] block');
  return { terminal: declared(root[1]), paper: declared(paper[1]) };
}

function luminance(hex) {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [n >> 16, (n >> 8) & 255, n & 255].map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function ratio(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const TEXT = [
  ['--fg', ['--bg', '--surface', '--surface-2', '--field']],
  ['--fg-strong', ['--bg', '--surface', '--surface-2', '--field', '--cover', '--cover-open']],
  ['--fg-read', ['--bg', '--surface', '--surface-2']],
  ['--fg-muted', ['--bg', '--surface', '--surface-2']],
  ['--warn', ['--bg', '--surface']],
  ['--danger', ['--bg', '--surface']],
  ['--ok', ['--bg', '--surface']],
  ['--info', ['--bg', '--surface']],
  ['--on-accent', ['--accent-bg', '--accent-hover', '--danger']],
  ['--chrome-fg', ['--chrome-bg']],
  ['--chrome-fg-muted', ['--chrome-bg']],
  ['--chrome-bg', ['--chrome-accent', '--chrome-accent-strong']],
];
const NON_TEXT = [
  ['--field-border', ['--bg', '--surface', '--field']],
  ['--focus', ['--bg', '--surface', '--field']],
  ['--chrome-field-border', ['--chrome-bg']],
];

test('both themes define the same tokens', () => {
  const { terminal, paper } = themes();
  assert.deepEqual(Object.keys(terminal).sort(), Object.keys(paper).sort());
});

test('every var() in the stylesheets resolves to a defined token', () => {
  const defined = declared(read('tokens.css').replace(/\/\*[\s\S]*?\*\//g, ''));
  const local = new Set(['--side']);
  const missing = [];
  for (const name of sheets) {
    const css = read(name).replace(/\/\*[\s\S]*?\*\//g, '');
    const own = new Set([...css.matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1]));
    for (const m of css.matchAll(/var\((--[a-z0-9-]+)/g)) {
      if (!(m[1] in defined) && !local.has(m[1]) && !own.has(m[1])) missing.push(`${name}: ${m[1]}`);
    }
  }
  assert.deepEqual(missing, []);
});

test('no old theme token name is left', () => {
  const old = /--(paper|ink|frame|signal|folder|map|seat|blind|radius-paper|radius-frame)\b/;
  const found = sheets.filter((name) => old.test(read(name)));
  assert.deepEqual(found, []);
});

test('colour literals live in tokens.css only', () => {
  const lit = /:\s*[^;{}]*(#[0-9a-fA-F]{3,8}\b|rgba?\()/;
  const found = sheets.filter((n) => n !== 'tokens.css' && lit.test(read(n)));
  assert.deepEqual(found, []);
});

for (const theme of ['terminal', 'paper']) {
  test(`${theme}: text pairs reach 4.5:1, borders and focus 3:1`, () => {
    const t = themes()[theme];
    const low = [];
    const check = (fg, bgs, min) => {
      for (const bg of bgs) {
        assert.match(t[fg] ?? '', /^#[0-9a-fA-F]{6}$/, `${theme} ${fg} is a hex colour`);
        assert.match(t[bg] ?? '', /^#[0-9a-fA-F]{6}$/, `${theme} ${bg} is a hex colour`);
        const r = ratio(t[fg], t[bg]);
        if (r < min) low.push(`${fg} on ${bg}: ${r.toFixed(2)} < ${min}`);
      }
    };
    for (const [fg, bgs] of TEXT) check(fg, bgs, 4.5);
    for (const [fg, bgs] of NON_TEXT) check(fg, bgs, 3);
    assert.deepEqual(low, []);
  });
}

test('the terminal theme drops the paper look and the paper theme keeps it', () => {
  const { terminal, paper } = themes();
  assert.equal(terminal['--tilt-stamp'], '0deg');
  assert.equal(terminal['--tilt-folder'], '0deg');
  assert.equal(terminal['--shadow-sheet'], 'none');
  assert.notEqual(paper['--tilt-stamp'], '0deg');
  assert.notEqual(paper['--shadow-sheet'], 'none');
});

test('themeName reads rv.theme and falls back to terminal', () => {
  assert.deepEqual(THEMES, ['terminal', 'paper']);
  assert.equal(themeName({ getItem: () => 'paper' }), 'paper');
  assert.equal(themeName({ getItem: () => 'terminal' }), 'terminal');
  assert.equal(themeName({ getItem: () => 'neon' }), 'terminal');
  assert.equal(themeName({ getItem: () => null }), 'terminal');
  assert.equal(themeName({ getItem: () => { throw new Error('blocked'); } }), 'terminal');
  assert.equal(themeName(undefined), 'terminal');
});

test('effects are off unless stored as on, and the root carries both settings', () => {
  const store = (v) => ({ getItem: (k) => (k === EFFECTS_KEY ? v : null) });
  assert.equal(effectsOn(store('on')), true);
  for (const v of [null, 'off', 'yes', '']) assert.equal(effectsOn(store(v)), false);
  assert.equal(effectsOn({ getItem: () => { throw new Error('blocked'); } }), false);
  assert.equal(effectsOn(undefined), false);
  const root = { dataset: {} };
  applyTheme(root, store('on'));
  assert.deepEqual(root.dataset, { theme: 'terminal', effects: 'on' });
  applyTheme(root, undefined);
  assert.deepEqual(root.dataset, { theme: 'terminal', effects: 'off' });
});
