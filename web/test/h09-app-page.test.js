// The page opens as the app (APL), one test or more per rule: 1. the page links the manifest, sets the
// theme colour to the value web/css/tokens.css holds for the page background, and links the 192 px
// icon as the touch icon; 2. the page loads web/js/shell.js as a second module after web/js/app.js;
// 3. installed, the app fills the screen: the safe areas of a notched phone are used, and the room
// scrolls inside the page instead of the page itself (the map keeps its floor, RMT rule 4).
// Keeps: the page still works in a plain browser tab. Mutant: the manifest link dropped.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

const read = (p) => readFileSync(new URL(`../${p}`, import.meta.url), 'utf8');
const head = read('index.html').split('</head>')[0];
const tokens = read('css/tokens.css');
const shell = read('css/c-shell.css').replace(/\/\*[\s\S]*?\*\//g, '');
const tag = (re) => re.exec(head)?.[0] ?? '';

test('the page links the manifest, and the file is there', () => {
  const link = tag(/<link rel="manifest"[^>]*>/);
  assert.ok(link, 'a manifest link');
  const href = /href="([^"]+)"/.exec(link)[1];
  assert.equal(href, '/manifest.webmanifest');
  assert.ok(existsSync(new URL(`..${href}`, import.meta.url)), 'the manifest file exists');
});

test('the theme colour is the page background of tokens.css', () => {
  const bg = /--bg:\s*(#[0-9a-fA-F]{3,8})\s*;/.exec(tokens)?.[1];
  assert.ok(bg, 'tokens.css holds --bg');
  const theme = /<meta name="theme-color" content="([^"]+)"/.exec(head)?.[1];
  assert.equal(theme?.toLowerCase(), bg.toLowerCase());
});

test('the touch icon is the 192 px icon, and the file is 192 px', () => {
  const href = /<link rel="apple-touch-icon"[^>]*href="([^"]+)"/.exec(head)?.[1];
  assert.equal(href, '/icons/icon-192.png');
  const png = readFileSync(new URL(`..${href}`, import.meta.url));
  assert.equal(png.readUInt32BE(16), 192);
  assert.equal(png.readUInt32BE(20), 192);
});

test('the viewport reaches under the notch so the safe areas can be used', () => {
  assert.match(tag(/<meta name="viewport"[^>]*>/), /viewport-fit=cover/);
});

test('shell.js is a second module, after app.js', () => {
  const mods = [...head.matchAll(/<script type="module" src="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(mods, ['/js/app.js', '/js/shell.js']);
});

const block = (sel) => {
  const at = shell.indexOf(`${sel} {`);
  assert.ok(at >= 0, `${sel} has a rule`);
  return shell.slice(at, shell.indexOf('}', at));
};

test('installed, the page itself does not scroll or bounce; the room does', () => {
  const page = block('html[data-shell="app"], html[data-shell="app"] body');
  assert.match(page, /overflow:\s*hidden/);
  assert.match(page, /overscroll-behavior:\s*none/);
  const app = block('html[data-shell="app"] #app');
  assert.match(app, /height:\s*100dvh/);
  assert.match(app, /overflow-y:\s*auto/, 'the room scrolls when the viewport is under the map floor');
  assert.match(app, /overscroll-behavior:\s*contain/);
});

test('installed, the room keeps clear of the notch and the sides', () => {
  const app = block('html[data-shell="app"] #app');
  for (const side of ['top', 'left', 'right']) {
    assert.match(app, new RegExp(`padding-${side}:\\s*env\\(safe-area-inset-${side}`));
  }
});

test('the tab bar and the room clear the home indicator', () => {
  assert.match(shell, /\.rl-tabbar \{[^}]*padding-bottom:\s*env\(safe-area-inset-bottom/);
  assert.match(shell, /\.rl-room, \.rl-room\.wide \{[^}]*padding-bottom:\s*calc\(.*env\(safe-area-inset-bottom/);
});

test('a plain tab is left as it was: every installed rule is under the shell mark', () => {
  assert.doesNotMatch(block('.screen'), /100dvh|safe-area/);
  assert.doesNotMatch(block('.screen.war-screen'), /dvh|safe-area/);
});
