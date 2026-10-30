// Unit tests for the reveal helpers, against the fixture. Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { finishedList, revealHeading, revealLinkLabel, revealParts, revealSeats } from '../js/views/realism-reveal.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const fixture = JSON.parse(readFileSync(join(WEB, 'test', 'fixtures', 'realism-seat.json'), 'utf8'));
const reveal = fixture.reveal;

test('a seat reads in order: goals, secrets, style history, rulings', () => {
  const parts = revealParts(reveal.seats[0]);
  assert.deepEqual(parts.map((p) => p.title), [
    'Their secret goals', 'What they did in secret', 'How they played', "The estimator's rulings",
  ]);
  assert.equal(parts[3].items[0].on, 'Harold R. Stark');
});

test('empty parts are dropped', () => {
  const parts = revealParts({ person: 'X', goals: ['a'], covert: [], styles: [], rulings: [] });
  assert.deepEqual(parts.map((p) => p.key), ['goals']);
  assert.deepEqual(revealParts({}), []);
});

test('revealSeats keeps the server order', () => {
  assert.equal(revealSeats(reveal)[0].person, 'Franklin D. Roosevelt');
  assert.deepEqual(revealSeats(null), []);
});

test('wording has no underscore and no ISO date', () => {
  const out = JSON.stringify([
    revealParts(reveal.seats[0]), revealHeading(reveal.name), revealLinkLabel(reveal.name),
  ]);
  assert.doesNotMatch(out, /_/);
  assert.doesNotMatch(out, /\d{4}-\d{2}-\d{2}/);
  assert.equal(revealHeading('Autumn 1941'), 'Autumn 1941: what was hidden');
  assert.equal(revealLinkLabel('Autumn 1941'), 'See the reveal of Autumn 1941');
});

test('finishedList is an empty fragment without ended games', () => {
  const frag = { children: [] };
  globalThis.document = { createDocumentFragment: () => frag };
  try {
    assert.equal(finishedList({ me: { finished: [] }, go() {} }), frag);
    assert.equal(frag.children.length, 0);
  } finally {
    delete globalThis.document;
  }
});
