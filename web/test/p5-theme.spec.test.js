// Spec for Train 2 unit TH1, written with contract K2: the unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { nextTheme, themeStore } from '../js/theme-setting.js';
import { EFFECTS_KEY, THEME_KEY } from '../js/theme.js';

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
  assert.equal(store.theme(), 'terminal');
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
  assert.equal(themeStore(s).theme(), 'terminal');
  assert.notEqual(s.data.get(THEME_KEY), 'neon');
  const none = themeStore(undefined);
  assert.equal(none.theme(), 'terminal');
  assert.doesNotThrow(() => none.save('paper', true));
  const blocked = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } };
  assert.equal(themeStore(blocked).effects(), false);
  assert.doesNotThrow(() => themeStore(blocked).save('paper', true));
});

test('the next theme', () => {
  assert.equal(nextTheme('terminal'), 'paper');
  assert.equal(nextTheme('paper'), 'terminal');
  assert.equal(nextTheme('anything'), 'terminal');
});

test('the control words', () => {
  const src = read('js/theme-setting.js');
  for (const words of ['Terminal', 'Paper', 'Effects']) assert.ok(src.includes(`'${words}'`), words);
  assert.match(src, /'aria-pressed'/);
  assert.match(src, /onChange\(/);
  assert.match(read('css/p5-theme.css'), /\.rl-theme/);
});
