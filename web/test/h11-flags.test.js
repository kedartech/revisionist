// A flag for every nation (FLG), one test or more per rule: 1. `flagFor(world, nationKey)` answers
// the address of that nation's file from the index, or null; 2. a nation with no file gets a plain
// block in its relation's tone from the theme's tokens (no hue added, no flag invented); 3 and 4 are
// checked on the files by tests/test_web_flags.py; 5. a flag is drawn 3 by 2 in a fixed box, never
// under 16 px high. Keeps: the name is always in the accessible name; a flag is an image, never
// inlined. Mutants: a missing file answered with an address; a block with a colour value in it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom } from './dom-fake.js';

installDom();
const { flagFor, flagBadge, setFlagIndex, loadFlagIndex, MIN_FLAG_HEIGHT } = await import('../js/flags.js');

const real = JSON.parse(readFileSync(new URL('../assets/flags/index.json', import.meta.url), 'utf8'));
const INDEX = { w1: { aaa: 'aaa.svg', bbb: null }, 'autumn-1941': real['autumn-1941'] };

test('rule 1: the address of a nation\'s file, from the world key and the nation key', () => {
  setFlagIndex(INDEX);
  assert.equal(flagFor('w1', 'aaa'), '/assets/flags/aaa.svg');
  assert.equal(flagFor('autumn-1941', 'usa'), '/assets/flags/usa.svg');
});

test('rule 1: a nation with a null row, no row, another world or no index answers null', () => {
  setFlagIndex(INDEX);
  assert.equal(flagFor('w1', 'bbb'), null);
  assert.equal(flagFor('w1', 'zzz'), null);
  assert.equal(flagFor('nowhere', 'aaa'), null);
  assert.equal(flagFor(undefined, 'aaa'), null);
  assert.equal(flagFor('w1', undefined), null);
  assert.equal(flagFor('w1', 'constructor'), null);
  assert.equal(flagFor('__proto__', 'aaa'), null);
  setFlagIndex(null);
  assert.equal(flagFor('w1', 'aaa'), null);
});

test('rule 1: a file name that is not a plain lowercase svg name is never answered', () => {
  setFlagIndex({ w: { a: '../../x.svg', b: 'x.png', c: 'http://e/x.svg', d: 'A.svg' } });
  for (const k of ['a', 'b', 'c', 'd']) assert.equal(flagFor('w', k), null, k);
});

test('every nation of the 1941 world with a file answers an address, and one with none answers null', () => {
  setFlagIndex(INDEX);
  const rows = Object.entries(real['autumn-1941']);
  assert.ok(rows.filter(([, name]) => name).length >= 21);
  for (const [key, name] of rows) {
    if (name) assert.match(flagFor('autumn-1941', key), /^\/assets\/flags\/[a-z_-]+\.svg$/, key);
    else assert.equal(flagFor('autumn-1941', key), null, key);
  }
});

test('rule 5: a flag is an image in a fixed 3 by 2 box, never under 16 px high', () => {
  setFlagIndex(INDEX);
  for (const [asked, high] of [[undefined, 16], [8, 16], [16, 16], [24, 24], [40, 40]]) {
    const box = flagBadge({ world: 'w1', key: 'aaa', name: 'Aland', relation: 'neutral' }, { height: asked });
    const img = box.querySelector('img');
    assert.ok(img);
    assert.equal(img.getAttribute('src'), '/assets/flags/aaa.svg');
    assert.equal(box.getAttribute('data-h'), String(high));
    assert.equal(box.getAttribute('data-w'), String(high * 1.5));
    assert.ok(MIN_FLAG_HEIGHT >= 16);
  }
});

test('rule 5: the box is sized by a class the stylesheet sets, from the height, not by an inline style', () => {
  setFlagIndex(INDEX);
  const box = flagBadge({ world: 'w1', key: 'aaa', name: 'Aland' }, { height: 24 });
  assert.equal(box.hasAttribute('style'), false);
  assert.ok(box.classList.contains('flag'));
  assert.ok(box.classList.contains('flag-h24'));
});

test('rule 2: a nation with no file gets a plain block in its relation\'s tone, with no image', () => {
  setFlagIndex(INDEX);
  for (const relation of ['own', 'enemy', 'neutral', 'ally', undefined]) {
    const box = flagBadge({ world: 'w1', key: 'bbb', name: 'Bland', relation });
    assert.equal(box.querySelector('img'), null);
    assert.ok(box.classList.contains('flag-plain'));
    assert.ok(box.classList.contains(`flag-${['own', 'enemy'].includes(relation) ? relation : 'neutral'}`), String(relation));
    assert.equal(box.getAttribute('data-h'), '16');
  }
});

test('rule 2: the plain block\'s colours are the theme\'s tokens, with no hex, rgb or hsl value', () => {
  const css = readFileSync(new URL('../css/c-flags.css', import.meta.url), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/);
  assert.match(css, /\.flag-plain\.flag-enemy[^}]*var\(--danger-soft\)/);
  assert.match(css, /\.flag-plain\.flag-neutral[^}]*var\(--surface-3\)/);
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  assert.match(html, /href="\/css\/c-flags\.css"/);
});

test('the name is in the accessible name: a flag beside the name is hidden from it, a flag alone carries it', () => {
  setFlagIndex(INDEX);
  const nation = { world: 'w1', key: 'aaa', name: 'Aland' };
  const beside = flagBadge(nation);
  assert.equal(beside.getAttribute('aria-hidden'), 'true');
  assert.equal(beside.querySelector('img').getAttribute('alt'), '');
  const alone = flagBadge(nation, { alone: true });
  assert.equal(alone.getAttribute('role'), 'img');
  assert.equal(alone.getAttribute('aria-label'), 'Aland');
  assert.equal(alone.getAttribute('aria-hidden'), null);
  const plain = flagBadge({ ...nation, key: 'bbb' }, { alone: true });
  assert.equal(plain.getAttribute('aria-label'), 'Aland');
});

test('a flag is drawn as an image and never inlined: no svg element, no innerHTML', () => {
  setFlagIndex(INDEX);
  const box = flagBadge({ world: 'w1', key: 'aaa', name: 'Aland' });
  assert.equal(box.querySelector('svg'), null);
  assert.doesNotMatch(readFileSync(new URL('../js/flags.js', import.meta.url), 'utf8'), /innerHTML|insertAdjacentHTML|<svg/);
});

test('the index is fetched from the assets and a failed fetch leaves every nation on the plain block', async () => {
  setFlagIndex(null);
  const seen = [];
  await loadFlagIndex(async (url) => { seen.push(url); return { ok: true, json: async () => INDEX }; });
  assert.deepEqual(seen, ['/assets/flags/index.json']);
  assert.equal(flagFor('w1', 'aaa'), '/assets/flags/aaa.svg');
  setFlagIndex(null);
  await loadFlagIndex(async () => { throw new Error('offline'); });
  assert.equal(flagFor('w1', 'aaa'), null);
  await loadFlagIndex(async () => ({ ok: false, json: async () => INDEX }));
  assert.equal(flagFor('w1', 'aaa'), null);
});
