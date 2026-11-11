// Spec for Train 3 unit P3, written with contract K3: the unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { DRAW_NOTE, castDossierModel } from '../js/views/realism-castdossier.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-cast.json'));
const ISO = /\b\d{4}-\d{2}-\d{2}\b/;

const [fdr, churchill, wheeler] = fixture.roster;
const pound = { name: 'Sir Dudley Pound', title: 'First Sea Lord', side: 'United Kingdom', power: 'Navy' };
const heads = (m) => m.sections.map((s) => s.heading);
const get = (m, k) => m.sections.find((s) => s.heading === k)?.lines;

test('a roster person with sidecar text gets the full dossier, in order', () => {
  const m = castDossierModel(fdr, fdr.dossier);
  assert.equal(m.full, true);
  assert.equal(m.listed, false);
  assert.deepEqual(heads(m), ['Side', 'Who they are', 'Their reach', 'Your arena', 'Biography', 'As history had it', 'In their words', 'A fact']);
  assert.deepEqual(get(m, 'Side'), ['Interventionists and United States']);
  assert.deepEqual(get(m, 'Your arena'), [fdr.dossier.arena]);
  assert.deepEqual(get(m, 'As history had it'), [...fdr.dossier.history, 'Not binding: you may do otherwise.']);
  assert.deepEqual(get(m, 'In their words'), [`“${fdr.dossier.quote}”`, `— ${fdr.dossier.source}`]);
});

test('a roster person with no sidecar text gets the short form from the roster', () => {
  const m = castDossierModel(wheeler, wheeler.dossier);
  assert.equal(m.full, false);
  assert.deepEqual(heads(m), ['Who they are', 'Their reach']);
});

test('a listed figure gets the short form: side, title, kind of power', () => {
  const m = castDossierModel(pound, null);
  assert.equal(m.listed, true);
  assert.equal(m.full, false);
  assert.deepEqual(heads(m), ['Side', 'Title', 'Kind of power']);
  assert.deepEqual(get(m, 'Kind of power'), ['Navy']);
});

test('a quote with no source is never shown; empty history drops its note', () => {
  const m = castDossierModel(churchill, { ...churchill.dossier, source: null, history: [] });
  assert.ok(!heads(m).includes('In their words'));
  assert.ok(!heads(m).includes('As history had it'));
});

test('no raw key, ISO date or filler in any model', () => {
  for (const p of [...fixture.roster, pound]) {
    const text = JSON.stringify(castDossierModel(p, p.dossier ?? null));
    assert.doesNotMatch(text, ISO);
    assert.doesNotMatch(text, /Not stated|None|undefined|null/);
  }
});

test('the dialog: Play, the note for a listed figure, Close, Esc', () => {
  assert.equal(DRAW_NOTE, 'Drawing up their papers takes about a minute.');
  const src = read('js/views/realism-castdossier.js');
  for (const s of [/'dialog'/, /Play \$\{/, /'Close'/, /onPlay\(person\)/, /onClose/, /'close'|onclose/, /DRAW_NOTE/, /portraitNode\(/]) assert.match(src, s);
});

test('no HTML parsing, no inline style, no stub left, linked and scoped', () => {
  const src = read('js/views/realism-castdossier.js');
  assert.doesNotMatch(src, /innerHTML|outerHTML|insertAdjacentHTML|style=|\.style\.|contract stub/);
  const css = read('css/p5-castdossier.css').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.doesNotMatch(read('css/p5-castdossier.css'), /contract stub/);
  assert.ok(css.trim().length > 0, 'the stylesheet has rules');
  assert.ok(read('index.html').includes('href="/css/p5-castdossier.css"'), 'linked from the page');
  const outer = css.replace(/@(media|container|supports)[^{]+\{/g, '').replace(/@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, '');
  const sels = [...outer.matchAll(/([^{}]+)\{/g)].flatMap((m) => m[1].split(',')).map((s) => s.trim()).filter(Boolean);
  for (const sel of sels) assert.match(sel, /\.rl-cd/, sel);
});
