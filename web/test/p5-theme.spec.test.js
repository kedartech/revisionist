// Spec for Train 2 unit TH1 (contract K2), revised for unit Q1 (contract KQ): paper is the
// default. The unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { nextTheme, themeControl, themeStore } from '../js/theme-setting.js';
import { EFFECTS_KEY, THEME_KEY } from '../js/theme.js';
import { buttons, installDom } from './dom-fake.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

const memory = () => {
  const data = new Map();
  return { data, getItem: (k) => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)) };
};

test('the store reads the defaults and saves both settings', () => {
  const s = memory();
  const store = themeStore(s);
  assert.equal(store.theme(), 'paper');
  assert.equal(store.effects(), false);
  store.save('paper', true);
  assert.equal(s.data.get(THEME_KEY), 'paper');
  assert.equal(s.data.get(EFFECTS_KEY), 'on');
  assert.equal(themeStore(s).theme(), 'paper');
  assert.equal(themeStore(s).effects(), true);
  store.save('terminal', false);
  assert.equal(s.data.get(EFFECTS_KEY), 'off');
});

test('an unknown theme is not saved, and no or blocked storage is safe', () => {
  const s = memory();
  themeStore(s).save('neon', false);
  assert.equal(themeStore(s).theme(), 'paper');
  assert.notEqual(s.data.get(THEME_KEY), 'neon');
  const none = themeStore(undefined);
  assert.equal(none.theme(), 'paper');
  assert.doesNotThrow(() => none.save('paper', true));
  const blocked = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } };
  assert.equal(themeStore(blocked).effects(), false);
  assert.doesNotThrow(() => themeStore(blocked).save('paper', true));
});

// An unknown theme reads as paper, so the next one is terminal.
test('the next theme', () => {
  assert.equal(nextTheme('terminal'), 'paper');
  assert.equal(nextTheme('paper'), 'terminal');
  assert.equal(nextTheme('anything'), 'terminal');
  assert.equal(nextTheme(undefined), 'terminal');
});

test('the control reads an unknown theme as paper', () => {
  installDom();
  const calls = [];
  const control = themeControl({ theme: 'neon', effects: false, onChange: (t, e) => calls.push([t, e]) });
  assert.equal(buttons(control, 'Paper').length, 1);
  buttons(control, 'Paper')[0].click();
  assert.deepEqual(calls, [['terminal', false]]);
  const known = themeControl({ theme: 'terminal', effects: true, onChange: (t, e) => calls.push([t, e]) });
  buttons(known, 'Terminal')[0].click();
  assert.deepEqual(calls.at(-1), ['paper', true]);
});

test('the page paints paper before any script runs', () => {
  assert.match(read('index.html'), /<html lang="en" data-theme="paper">/);
});

test('the control words', () => {
  const src = read('js/theme-setting.js');
  for (const words of ['Terminal', 'Paper', 'Effects']) assert.ok(src.includes(`'${words}'`), words);
  assert.match(src, /'aria-pressed'/);
  assert.match(src, /onChange\(/);
  assert.match(read('css/p5-theme.css'), /\.rl-theme/);
});
