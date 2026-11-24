// The app shell: the manifest names the app in the theme's own colours with its three icons, and
// `js/shell.js` runs on its own when the page loads it and knows whether the app runs installed.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

const read = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');
const MANIFEST = JSON.parse(read('../manifest.webmanifest'));
const TOKENS = read('../css/tokens.css');
const token = (name) => TOKENS.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{3,8})\\s*;`))?.[1];

const { isInstalled, startShell } = await import('../js/shell.js');

const fakeWin = ({ standalone = false, modes = [], nav = {}, referrer = '' } = {}) => {
  const listeners = [];
  const root = { attrs: {}, setAttribute(k, v) { this.attrs[k] = v; } };
  return {
    listeners,
    root,
    matchMedia: (q) => ({
      matches: modes.some((m) => q.includes(m)) || (standalone && q.includes('standalone')),
      addEventListener: (type, fn) => listeners.push([q, type, fn]),
    }),
    navigator: nav,
    document: { referrer, documentElement: root },
  };
};

test('the manifest names the app and starts at the root, standalone', () => {
  assert.ok(MANIFEST.name && MANIFEST.short_name);
  assert.equal(MANIFEST.start_url, '/');
  assert.equal(MANIFEST.display, 'standalone');
});

test('the manifest colours equal the theme tokens', () => {
  assert.equal(MANIFEST.theme_color.toLowerCase(), token('bg').toLowerCase());
  assert.equal(MANIFEST.background_color.toLowerCase(), token('bg').toLowerCase());
});

test('the manifest names nothing personal', () => {
  const text = JSON.stringify(MANIFEST).toLowerCase();
  for (const word of ['josh', 'thejoshbq', 'kedar', '@', 'http']) assert.ok(!text.includes(word), word);
});

test('the manifest lists three icons that exist, with 192, 512 and a maskable 512', () => {
  const got = MANIFEST.icons.map((i) => `${i.sizes} ${i.purpose}`).sort();
  assert.deepEqual(got, ['192x192 any', '512x512 any', '512x512 maskable']);
  for (const icon of MANIFEST.icons) {
    assert.ok(existsSync(new URL(`..${icon.src}`, import.meta.url)), icon.src);
  }
});

test('shell.js can be imported with no window', () => {
  assert.equal(typeof isInstalled, 'function');
  assert.equal(typeof startShell, 'function');
});

test('a plain tab is not installed', () => {
  assert.equal(isInstalled(fakeWin()), false);
});

test('each way an installed app shows itself is read', () => {
  assert.equal(isInstalled(fakeWin({ standalone: true })), true);
  assert.equal(isInstalled(fakeWin({ modes: ['fullscreen'] })), true);
  assert.equal(isInstalled(fakeWin({ nav: { standalone: true } })), true);
  assert.equal(isInstalled(fakeWin({ referrer: 'android-app://com.example' })), true);
});

test('starting marks the page installed or in a tab', () => {
  const tab = fakeWin();
  startShell(tab);
  assert.equal(tab.root.attrs['data-shell'], 'tab');
  const app = fakeWin({ standalone: true });
  startShell(app);
  assert.equal(app.root.attrs['data-shell'], 'app');
});

test('the mark follows a change of display mode', () => {
  const win = fakeWin();
  startShell(win);
  assert.ok(win.listeners.length > 0);
  const [, type, fn] = win.listeners[0];
  assert.equal(type, 'change');
  win.matchMedia = () => ({ matches: true, addEventListener() {} });
  fn();
  assert.equal(win.root.attrs['data-shell'], 'app');
});

test('starting with no window does nothing and does not throw', () => {
  assert.equal(startShell(undefined), false);
});
