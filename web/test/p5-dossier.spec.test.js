// Spec for Train 2 unit D, written with contract K2: the unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { dossierSections, monogram, settingSections } from '../js/views/realism-dossier.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

const { desk, dossier, setting } = fixture;

test('a monogram is the first and last initials', () => {
  assert.equal(monogram('Franklin D. Roosevelt'), 'FR');
  assert.equal(monogram('Sir Dudley Pound'), 'SP');
  assert.equal(monogram('Stalin'), 'S');
  assert.equal(monogram('  harry   hopkins '), 'HH');
  assert.equal(monogram(''), '');
});

test('the character sections in order, only those with content', () => {
  const out = dossierSections(desk, dossier);
  assert.deepEqual(out.map((s) => s.heading), [
    'Office', 'Answers to', 'As history had it', 'Biography', 'Powers', 'Limits', 'Personal', 'Aims', 'How far ahead you see',
    'In their words', 'A fact',
  ]);
  const get = (k) => out.find((s) => s.heading === k).lines;
  assert.deepEqual(get('Office'), [desk.office]);
  assert.deepEqual(get('Answers to'), ['The electorate, Congress']);
  assert.deepEqual(get('As history had it'), dossier.history);
  assert.deepEqual(get('Biography'), [dossier.bio]);
  assert.deepEqual(get('In their words'), [`“${dossier.quote}”`, `— ${dossier.source}`]);
  assert.deepEqual(get('A fact'), [dossier.fact]);
  assert.deepEqual(get('Limits'), desk.constraints);
  assert.deepEqual(get('Aims'), desk.aims);
  assert.ok(get('Powers').length === 1 && get('Powers')[0].endsWith('.'));
  assert.deepEqual(get('How far ahead you see'), ['You plan about a month ahead']);
});

test('an empty dossier leaves only the desk', () => {
  const empty = { bio: null, history: [], quote: null, source: null, fact: null, portrait: null, credit: null };
  const heads = dossierSections({ ...desk, constraints: [], personal: [] }, empty).map((s) => s.heading);
  assert.deepEqual(heads, ['Office', 'Answers to', 'Powers', 'Aims', 'How far ahead you see']);
  const noSource = dossierSections(desk, { ...dossier, source: null }).map((s) => s.heading);
  assert.ok(!noSource.includes('In their words'), 'a quote with no source is never shown');
});

test('the setting sections', () => {
  const out = settingSections(setting, '20 October 1941');
  assert.deepEqual(out.map((s) => s.heading), ['The date', 'The situation', 'The sides', "On history's clock"]);
  assert.deepEqual(out[0].lines, ['20 October 1941']);
  assert.deepEqual(out[2].lines, setting.sides);
  assert.deepEqual(out[3].lines, ['17 October 1941: USS Kearny is torpedoed off Iceland.', '31 October 1941: USS Reuben James is sunk.']);
  const bare = settingSections({ situation: null, sides: [], crawl: [], facts: [], dates: [] }, '20 October 1941');
  assert.deepEqual(bare.map((s) => s.heading), ['The date']);
});

test('the dialogs: portrait path, monogram, credit and close', () => {
  const src = read('js/views/realism-dossier.js');
  assert.match(src, /\/assets\/portraits\//);
  assert.match(src, /'dialog'/);
  assert.match(src, /'Close'/);
  assert.match(src, /monogram\(/);
});
