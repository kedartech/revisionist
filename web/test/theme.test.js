// The theme contract: one console theme in one token block, semantic tokens only, every var()
// defined, colour literals in tokens.css alone, and text pairs that pass AA on every ground.
// The screen effects are built in, with no setting and no toggle (14 Nov).
import assert from 'node:assert/strict';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import * as theme from '../js/theme.js';
import { browserStorage } from '../js/theme.js';

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
  assert.equal(t['--field-border'].toLowerCase(), '#6b7077');
  assert.equal(t['--duo-dark'].toLowerCase(), '#141414');
  assert.equal(t['--duo-light'].toLowerCase(), '#e8e8e8');
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

/** Every file under a directory of web/, its subdirectories included. */
function filesUnder(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? filesUnder(p) : [p];
  });
}

// A colour a stylesheet or script may write outside tokens.css: a flag's own colours or a colour
// carried in map data, each with its reason. Path relative to web/ -> reason.
const LITERAL_ALLOW = new Map();

const HEX = /(^|[\s'"`:(,=])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])/m;
const FUNC = /\b(?:rgba?|hsla?)\(/;

test('no file under web/css but tokens.css, and no file under web/js, writes a hex, rgb( or hsl( colour', () => {
  const files = [...filesUnder(CSS), ...filesUnder(join(WEB, 'js'))].filter((p) => /\.(css|js)$/.test(p));
  const found = [];
  for (const p of files) {
    const rel = p.slice(WEB.length).replace(/^\//, '');
    if (rel === 'css/tokens.css' || LITERAL_ALLOW.has(rel)) continue;
    const text = p.endsWith('.css') ? uncomment(readFileSync(p, 'utf8')) : readFileSync(p, 'utf8');
    if (HEX.test(text) || FUNC.test(text)) found.push(rel);
  }
  assert.ok(files.length > 50, `walked ${files.length} files`);
  assert.deepEqual(found, []);
  for (const [rel, why] of LITERAL_ALLOW) assert.ok(why.length > 20 && existsSync(join(WEB, rel)), rel);
});

// The Graphite palette: charcoal grounds with no blue tint, white and light grey for the seat's
// own things and the primary action, amber for what is due or live, red for what is hostile,
// failing or lost. A token the Graphite block does not name holds the neutral of its earlier
// lightness; --danger-soft is 12% of --danger over --surface.
const GRAPHITE = {
  '--bg': '#0b0c0e', '--surface': '#131517', '--surface-2': '#181a1d', '--surface-3': '#202326',
  '--field': '#0f0f0f', '--cover': '#1b1b1b', '--cover-open': '#232323', '--cover-edge': '#454545',
  '--fg': '#c6cacf', '--fg-strong': '#f2f4f6', '--fg-read': '#d8dbdf', '--fg-muted': '#90969d',
  '--rule': '#26292d', '--rule-strong': '#3a3e43', '--field-border': '#6b7077', '--focus': '#f2f4f6',
  '--accent': '#eceef0', '--accent-bg': '#e6e8eb', '--accent-hover': '#ffffff', '--on-accent': '#0b0c0e',
  '--ok': '#c2c2c2', '--info': '#b4bac2', '--warn': '#ffb224', '--danger': '#f07363', '--intel': '#c9ced4',
  '--accent-soft': '#1d1f22', '--ok-soft': '#2a2a2a', '--info-soft': '#1b1d20', '--warn-soft': '#2a2418',
  '--danger-soft': '#2e2020', '--intel-soft': '#282828',
  '--chrome-bg': '#151515', '--chrome-fg': '#dddddd', '--chrome-fg-muted': '#999999', '--chrome-accent': '#c2c2c2',
  '--chrome-accent-strong': '#cfcfcf', '--chrome-field-border': '#747474', '--chrome-rule': '#2f2f2f',
  '--chart-sea': '#0f1012', '--chart-land': '#202326', '--chart-line': '#6b7077',
  '--duo-dark': '#141414', '--duo-light': '#e8e8e8',
};
const WARM = new Set(['--warn', '--warn-soft', '--danger', '--danger-soft']);

test('the tokens hold the Graphite palette, and no token but amber and red carries a hue', () => {
  const t = tokens();
  const off = Object.entries(GRAPHITE).filter(([name, hex]) => (t[name] ?? '').toLowerCase() !== hex).map(([name]) => name);
  assert.deepEqual(off, []);
  const hues = [];
  for (const [name, value] of Object.entries(t)) {
    if (!/^#[0-9a-fA-F]{6}$/.test(value) || WARM.has(name)) continue;
    const n = parseInt(value.slice(1), 16);
    const ch = [n >> 16, (n >> 8) & 255, n & 255];
    if (Math.max(...ch) - Math.min(...ch) > 14) hues.push(`${name} ${value}`);
  }
  assert.deepEqual(hues, []);
  assert.match(t['--backdrop'], /^rgb\(0 0 0 \/ \.\d+\)$/);
});

/** The declarations of the first rule whose selector list is exactly `selector`. */
function rule(sheet, selector) {
  const css = uncomment(read(sheet));
  const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const m = css.match(new RegExp(`(?:^|})\\s*${esc}\\s*\\{([^}]*)\\}`));
  assert.ok(m, `${sheet}: ${selector}`);
  return m[1];
}

test('a difference hue carried is carried by line or fill, and a lone toggle that is on is outlined', () => {
  // the seat's own nation and an ally in the economy strip: solid against dashed
  assert.match(rule('c-economy.css', '.rl-eco-own'), /border-left:\s*4px solid/);
  assert.match(rule('c-economy.css', '.rl-eco-ally'), /border-left:\s*4px dashed/);
  // an order under way on the map is a solid line; one still planned is dashed
  assert.match(rule('c-map.css', '.rl-mk-arrow'), /stroke-dasharray:\s*5 4/);
  assert.match(rule('c-map.css', '.rl-o-under_way .rl-mk-arrow, .rl-o-under_way .rl-mk-goal'), /stroke-dasharray:\s*none/);
  // a pressed toggle keeps the ground and takes a strong outline; the solid fill is the primary action's
  for (const [sheet, sel] of [['c-map.css', '.rl-filter[aria-pressed="true"]'], ['c-shell.css', '.rl-btn[aria-pressed="true"]']]) {
    const body = rule(sheet, sel);
    assert.doesNotMatch(body, /--accent-bg|--on-accent/, `${sheet}: ${sel}`);
    assert.match(body, /border-color:\s*var\(--fg-strong\)/, `${sheet}: ${sel}`);
  }
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

test('the screen effects setting is gone: no toggle, no stored value, no root attribute', () => {
  for (const name of ['EFFECTS_KEY', 'effectsOn', 'saveEffects', 'applyEffects', 'effectsControl']) assert.ok(!(name in theme), name);
  const frame = readFileSync(join(WEB, 'js/views/frame.js'), 'utf8');
  assert.doesNotMatch(frame, /effectsControl|themeControl|theme-setting/);
  const app = readFileSync(join(WEB, 'js/app.js'), 'utf8');
  assert.doesNotMatch(app, /saveEffects|applyEffects|dataset\.effects/);
  assert.doesNotMatch(app, /theme-setting|themeName|applyTheme/);
});

test('browserStorage gives the page storage, or undefined where reading it throws', () => {
  const store = { getItem: () => null };
  assert.equal(browserStorage({ localStorage: store }), store);
  const blocked = Object.defineProperty({}, 'localStorage', { get() { throw new Error('SecurityError'); } });
  assert.equal(browserStorage(blocked), undefined);
  assert.equal(browserStorage(undefined), undefined);
});
