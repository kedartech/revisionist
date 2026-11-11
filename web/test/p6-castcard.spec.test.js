// Spec for Train 3 unit P1, written with contract K3: the unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { cardModel } from '../js/views/realism-castcard.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-cast.json'));
const ISO = /\b\d{4}-\d{2}-\d{2}\b/;

const [fdr, churchill, wheeler] = fixture.roster;

test('a card reads the name, the sides in words and the pitch', () => {
  const m = cardModel(fdr, null);
  assert.equal(m.name, 'Franklin D. Roosevelt');
  assert.equal(m.side, 'Interventionists and United States');
  assert.equal(m.pitch, fdr.pitch);
  assert.equal(m.monogram, 'FR');
  assert.equal(m.tag, null);
  assert.equal(m.label, 'Franklin D. Roosevelt: open the dossier');
});

test('the viewer’s own person reads You, anyone else taken reads Taken', () => {
  assert.equal(cardModel({ ...fdr, taken: true }, 'Franklin D. Roosevelt').tag, 'You');
  assert.equal(cardModel(churchill, 'Franklin D. Roosevelt').tag, 'Taken');
  assert.equal(cardModel(churchill, null).tag, 'Taken');
});

test('missing sides and pitch hide their lines, a repeated side is said once', () => {
  const m = cardModel({ ...wheeler, pitch: '  ' }, null);
  assert.equal(m.side, null);
  assert.equal(m.pitch, null);
  const twice = cardModel({ ...fdr, sides: [{ contest: 'a', side: 'Allies' }, { contest: 'b', side: 'Allies' }] }, null);
  assert.equal(twice.side, 'Allies');
});

test('no raw key or ISO date in the model', () => {
  for (const p of fixture.roster) {
    const text = JSON.stringify(cardModel(p, null));
    assert.doesNotMatch(text, ISO);
    assert.doesNotMatch(text, /_/);
  }
});

test('the card is one button that opens the dossier; it has no Play button', () => {
  const src = read('js/views/realism-castcard.js');
  assert.match(src, /'button'/);
  assert.match(src, /onOpen\(person\)/);
  assert.match(src, /portraitNode\(/);
  assert.doesNotMatch(src, /Play \$\{/);
});

test('no HTML parsing, no inline style, no stub left, linked and scoped', () => {
  const src = read('js/views/realism-castcard.js');
  assert.doesNotMatch(src, /innerHTML|outerHTML|insertAdjacentHTML|style=|\.style\.|contract stub/);
  const css = read('css/p5-castcard.css').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.doesNotMatch(read('css/p5-castcard.css'), /contract stub/);
  assert.ok(css.trim().length > 0, 'the stylesheet has rules');
  assert.ok(read('index.html').includes('href="/css/p5-castcard.css"'), 'linked from the page');
  const outer = css.replace(/@(media|container|supports)[^{]+\{/g, '').replace(/@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, '');
  const sels = [...outer.matchAll(/([^{}]+)\{/g)].flatMap((m) => m[1].split(',')).map((s) => s.trim()).filter(Boolean);
  for (const sel of sels) assert.match(sel, /\.rl-cc/, sel);
});
