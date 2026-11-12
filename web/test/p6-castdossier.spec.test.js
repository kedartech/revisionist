// Spec for Train 3 unit P3 (contract K3), revised for unit Q6 (contract KQ): a pick asks
// first. The unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import * as dossierView from '../js/views/realism-castdossier.js';
import { DRAW_NOTE, castDossier, castDossierModel } from '../js/views/realism-castdossier.js';
import { buttons, installDom, words } from './dom-fake.js';

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
  assert.deepEqual(get(m, 'Side'), ['United States']);
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

test('playStep: read, confirm, back, go', () => {
  const { playStep } = dossierView;
  assert.equal(typeof playStep, 'function');
  assert.equal(playStep('read', 'play'), 'confirm');
  assert.equal(playStep('confirm', 'back'), 'read');
  assert.equal(playStep('confirm', 'yes'), 'go');
  assert.equal(playStep('read', 'yes'), 'read');
  assert.equal(playStep('read', 'back'), 'read');
  assert.equal(playStep('confirm', 'play'), 'confirm');
  assert.equal(playStep('go', 'back'), 'go');
});

const open = (person, confirmNote) => {
  const doc = installDom();
  const played = [];
  const closed = [];
  const dialog = castDossier({
    person, dossier: person.dossier ?? null, canPlay: true, confirmNote,
    onPlay: (p) => played.push(p), onClose: () => closed.push(1),
  });
  doc.body.append(dialog);
  dialog.showModal();
  return { doc, dialog, played, closed, foot: () => dialog.querySelector('.rl-cd-foot') };
};

test('Play asks first: the question, the note, Yes and Not yet; Yes plays once', () => {
  const { doc, dialog, played, foot } = open(fdr, 'You keep this seat for the whole game.');
  buttons(foot(), 'Play Franklin D. Roosevelt')[0].click();
  assert.equal(played.length, 0, 'Play alone does not pick');
  assert.ok(words(foot()).includes('Play Franklin D. Roosevelt?'), words(foot()));
  assert.ok(words(foot()).includes('You keep this seat for the whole game.'));
  const yes = buttons(foot(), 'Yes, play Franklin D. Roosevelt')[0];
  assert.ok(yes, 'a Yes button');
  assert.equal(buttons(foot(), 'Not yet').length, 1);
  assert.equal(doc.activeElement, yes, 'focus moves to Yes');
  yes.click();
  yes.click();
  assert.deepEqual(played, [fdr]);
  assert.ok(dialog);
});

test('Not yet goes back to the foot with Play focused; Esc still closes', () => {
  const { doc, dialog, played, closed, foot } = open(fdr, null);
  buttons(foot(), 'Play Franklin D. Roosevelt')[0].click();
  assert.ok(!words(foot()).includes('null'), 'no note shows as null');
  const notYet = buttons(foot(), 'Not yet')[0];
  assert.ok(notYet, 'a Not yet button');
  notYet.click();
  const play = buttons(foot(), 'Play Franklin D. Roosevelt')[0];
  assert.ok(play, 'Play is back');
  assert.equal(buttons(foot(), 'Not yet').length, 0);
  assert.equal(doc.activeElement, play);
  dialog.close();
  assert.equal(closed.length, 1);
  assert.equal(played.length, 0);
});

test('a listed figure: the confirm step carries the drawing-up note', () => {
  const pound = { name: 'Sir Dudley Pound', title: 'First Sea Lord', side: 'United Kingdom', power: 'Navy' };
  const { foot } = open(pound, 'You keep this seat for the whole game.');
  buttons(foot(), 'Play Sir Dudley Pound')[0].click();
  assert.ok(words(foot()).includes(DRAW_NOTE));
  assert.equal(buttons(foot(), 'Yes, play Sir Dudley Pound').length, 1);
});
