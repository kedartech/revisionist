// The theme contract: one console theme in one token block, semantic tokens only, every var()
// defined, colour literals in tokens.css alone, and text pairs that pass AA on every ground.
// The screen effects are on unless turned off, with one header toggle.
import assert from 'node:assert/strict';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import * as theme from '../js/theme.js';
import { EFFECTS_KEY, applyEffects, browserStorage, effectsControl, effectsOn, saveEffects } from '../js/theme.js';
import { buttons, installDom } from './dom-fake.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const CSS = join(WEB, 'css');
const read = (name) => readFileSync(join(CSS, name), 'utf8');
const sheets = readdirSync(CSS).filter((n) => n.endsWith('.css'));
const uncomment = (text) => text.replace(/\/\*[\s\S]*?\*\//g, '');

/** Custom properties declared in a block of tokens.css. */
function declared(block) {
  return Object.fromEntries([...block.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
}

function tokens() {
  const src = uncomment(read('tokens.css'));
  const blocks = [...src.matchAll(/([^{}]+)\{([^{}]*)\}/g)];
  assert.equal(blocks.length, 1, 'tokens.css holds one block');
  assert.equal(blocks[0][1].trim(), ':root', 'the one block is :root');
  return declared(blocks[0][2]);
}

/** Every file under web/ but the tests, installed packages, images and fonts. */
function webFiles(dir = WEB) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    if (['test', 'node_modules', 'assets', 'fonts'].includes(n)) return [];
    return statSync(p).isDirectory() ? webFiles(p) : [p];
  });
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

const SURFACES = ['--bg', '--surface', '--surface-2', '--surface-3'];
const ACCENTS = ['--accent', '--ok', '--info', '--warn', '--danger', '--intel'];
const SOFT = ACCENTS.map((a) => `${a}-soft`);
const TEXT = [
  ['--fg', [...SURFACES, '--field']],
  ['--fg-strong', [...SURFACES, '--field', '--cover', '--cover-open', ...SOFT]],
  ['--fg-read', [...SURFACES, ...SOFT]],
  ['--fg-muted', SURFACES],
  ...ACCENTS.map((a) => [a, [...SURFACES, `${a}-soft`]]),
  ['--on-accent', ['--accent-bg', '--accent-hover', '--danger']],
  ['--bg', ACCENTS],
  ['--chrome-fg', ['--chrome-bg']],
  ['--chrome-fg-muted', ['--chrome-bg']],
  ['--chrome-bg', ['--chrome-accent', '--chrome-accent-strong']],
];
const NON_TEXT = [
  ['--field-border', [...SURFACES, '--field']],
  ['--focus', [...SURFACES, '--field']],
  ['--chrome-field-border', ['--chrome-bg']],
];

test('one theme: tokens.css holds a single :root block with the console names', () => {
  const t = tokens();
  for (const name of ['--surface-3', '--rule-strong', '--intel', '--duo-dark', '--duo-light', ...SOFT]) {
    assert.ok(name in t, name);
  }
  assert.equal(t['--field-border'].toLowerCase(), '#60768e');
  assert.equal(t['--duo-dark'].toLowerCase(), '#06180d');
  assert.equal(t['--duo-light'].toLowerCase(), '#8dffb4');
  assert.match(t['--font-head'], /^'IBM Plex Sans'/);
  assert.match(t['--font-chrome'], /^'IBM Plex Mono'/);
});

test('every var() in the stylesheets resolves to a defined token', () => {
  const defined = tokens();
  const local = new Set(['--side', '--c']);
  const missing = [];
  for (const name of sheets) {
    const css = uncomment(read(name));
    const own = new Set([...css.matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1]));
    for (const m of css.matchAll(/var\((--[a-z0-9-]+)/g)) {
      if (!(m[1] in defined) && !local.has(m[1]) && !own.has(m[1])) missing.push(`${name}: ${m[1]}`);
    }
  }
  assert.deepEqual(missing, []);
});

test('no old theme token name and no paper-only token is left', () => {
  const old = /--(paper|ink|frame|signal|folder|map|seat|blind|radius-paper|radius-frame|tilt-[a-z]+|shadow-sheet|border-sheet|border-portrait)\b/;
  const found = sheets.filter((name) => old.test(read(name)));
  assert.deepEqual(found, []);
});

test('colour literals live in tokens.css only', () => {
  const lit = /:\s*[^;{}]*(#[0-9a-fA-F]{3,8}\b|rgba?\()/;
  const found = sheets.filter((n) => n !== 'tokens.css' && lit.test(uncomment(read(n))));
  assert.deepEqual(found, []);
});

test('no data-theme selector and no read of rv.theme anywhere in the page', () => {
  const found = webFiles().filter((p) => /data-theme|rv\.theme|THEME_KEY/.test(readFileSync(p, 'utf8')));
  assert.deepEqual(found, []);
});

test('the theme switch, its stylesheet and Courier Prime are gone', () => {
  for (const gone of ['js/theme-setting.js', 'css/p5-theme.css', 'fonts/courier-prime.woff2', 'fonts/courier-prime-bold.woff2', 'fonts/OFL-courierprime.txt']) {
    assert.ok(!existsSync(join(WEB, gone)), gone);
  }
  assert.doesNotMatch(read('fonts.css'), /Courier Prime/);
  const page = readFileSync(join(WEB, 'index.html'), 'utf8');
  assert.match(page, /<html lang="en">/);
  assert.doesNotMatch(page, /p5-theme\.css/);
  for (const name of ['themeName', 'THEMES', 'DEFAULT_THEME', 'applyTheme', 'THEME_KEY']) assert.ok(!(name in theme), name);
});

test('text pairs reach 4.5:1, borders and focus 3:1, each accent on every surface and its own soft ground', () => {
  const t = tokens();
  const low = [];
  const check = (fg, bgs, min) => {
    for (const bg of bgs) {
      assert.match(t[fg] ?? '', /^#[0-9a-fA-F]{6}$/, `${fg} is a hex colour`);
      assert.match(t[bg] ?? '', /^#[0-9a-fA-F]{6}$/, `${bg} is a hex colour`);
      const r = ratio(t[fg], t[bg]);
      if (r < min) low.push(`${fg} on ${bg}: ${r.toFixed(2)} < ${min}`);
    }
  };
  for (const [fg, bgs] of TEXT) check(fg, bgs, 4.5);
  for (const [fg, bgs] of NON_TEXT) check(fg, bgs, 3);
  assert.deepEqual(low, []);
});

test('effects are on unless stored as off, and the root carries the setting', () => {
  const store = (v) => ({ getItem: (k) => (k === EFFECTS_KEY ? v : null) });
  for (const v of [null, 'on', 'yes', '']) assert.equal(effectsOn(store(v)), true, String(v));
  assert.equal(effectsOn(store('off')), false);
  assert.equal(effectsOn({ getItem: () => { throw new Error('blocked'); } }), true);
  assert.equal(effectsOn(undefined), true);
  const root = { dataset: {} };
  applyEffects(root, store('off'));
  assert.deepEqual(root.dataset, { effects: 'off' });
  applyEffects(root, undefined);
  assert.deepEqual(root.dataset, { effects: 'on' });
});

test('saving the effects writes on or off, and blocked storage is safe', () => {
  const data = new Map();
  const s = { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => data.set(k, String(v)) };
  saveEffects(s, false);
  assert.equal(data.get(EFFECTS_KEY), 'off');
  assert.equal(effectsOn(s), false);
  saveEffects(s, true);
  assert.equal(data.get(EFFECTS_KEY), 'on');
  assert.doesNotThrow(() => saveEffects({ setItem: () => { throw new Error('blocked'); } }, true));
  assert.doesNotThrow(() => saveEffects(undefined, true));
});

test('one Screen effects toggle: pressed while on, a click asks for the other state', () => {
  installDom();
  const calls = [];
  const host = document.createElement('div');
  const on = effectsControl({ effects: true, onChange: (v) => calls.push(v) });
  host.append(on);
  assert.equal(buttons(host, 'Screen effects').length, 1, 'one button named Screen effects');
  assert.equal(on.getAttribute('aria-pressed'), 'true');
  on.click();
  const off = effectsControl({ effects: false, onChange: (v) => calls.push(v) });
  assert.equal(off.getAttribute('aria-pressed'), 'false');
  off.click();
  assert.deepEqual(calls, [false, true]);
});

test('the header carries the effects toggle and the shell passes the effects setting', () => {
  const frame = readFileSync(join(WEB, 'js/views/frame.js'), 'utf8');
  assert.match(frame, /effectsControl\(effects\)/);
  assert.doesNotMatch(frame, /themeControl|theme-setting/);
  const app = readFileSync(join(WEB, 'js/app.js'), 'utf8');
  assert.match(app, /saveEffects\(storage, on\)/);
  assert.match(app, /applyEffects\(document\.documentElement, storage\)/);
  assert.doesNotMatch(app, /theme-setting|themeName|applyTheme/);
});

test('browserStorage gives the page storage, or undefined where reading it throws', () => {
  const store = { getItem: () => null };
  assert.equal(browserStorage({ localStorage: store }), store);
  const blocked = Object.defineProperty({}, 'localStorage', { get() { throw new Error('SecurityError'); } });
  assert.equal(browserStorage(blocked), undefined);
  assert.equal(browserStorage(undefined), undefined);
});
