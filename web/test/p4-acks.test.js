// Unit tests for the acknowledgement helpers, against the fixture. Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { ackLines, ackThread } from '../js/views/realism-acks.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const fixture = JSON.parse(readFileSync(join(WEB, 'test', 'fixtures', 'realism-seat.json'), 'utf8'));
const listing = fixture.listing;

const row = (over) => ({
  id: 'd-x', kind: 'letter', title: 'On your order: Something', author: 'Sam Rayburn',
  issued: '1941-10-01', arrives: '1941-10-02', channel: 'letter', classification: 'open',
  unread: false, flagged: false, group: null, ack: true, ...over,
});

test('ackLines returns the fixture acknowledgement by its author', () => {
  assert.deepEqual(ackLines(listing, 'Sam Rayburn'), [
    { id: 'd-reply-1012', title: 'Send a bill to Congress', day: '12 October 1941', unread: false },
  ]);
});

test('ackLines is empty for a person with no acknowledgements', () => {
  assert.deepEqual(ackLines(listing, 'Harry Hopkins'), []);
  assert.deepEqual(ackLines(listing, 'Admiral Ernest King'), []);
});

test('ackLines ignores papers that are not acknowledgements, even from the same author', () => {
  const docs = { documents: [row({ id: 'a', ack: false }), row({ id: 'b', author: 'Someone Else' })] };
  assert.deepEqual(ackLines(docs, 'Sam Rayburn'), []);
});

test('ackLines sorts newest arrival first, ties by id', () => {
  const docs = { documents: [
    row({ id: 'm', arrives: '1941-10-03' }),
    row({ id: 'z', arrives: '1941-10-05' }),
    row({ id: 'b', arrives: '1941-10-05' }),
    row({ id: 'a', arrives: '1941-10-01' }),
  ] };
  assert.deepEqual(ackLines(docs, 'Sam Rayburn').map((l) => l.id), ['b', 'z', 'm', 'a']);
});

test('ackLines drops the "On your order: " prefix only, and reports unread', () => {
  const docs = { documents: [
    row({ id: 'p', title: 'On your order: Hold the convoy', unread: true }),
    row({ id: 'q', title: 'Not On your order: kept', arrives: '1941-10-01' }),
  ] };
  assert.deepEqual(ackLines(docs, 'Sam Rayburn'), [
    { id: 'p', title: 'Hold the convoy', day: '2 October 1941', unread: true },
    { id: 'q', title: 'Not On your order: kept', day: '1 October 1941', unread: false },
  ]);
});

test('ackLines does not mutate the listing', () => {
  const docs = { documents: [
    row({ id: 'a', arrives: '1941-10-01' }),
    row({ id: 'b', arrives: '1941-10-09' }),
  ] };
  const before = JSON.stringify(docs);
  const order = docs.documents.map((d) => d.id);
  ackLines(docs, 'Sam Rayburn');
  assert.equal(JSON.stringify(docs), before);
  assert.deepEqual(docs.documents.map((d) => d.id), order);
});

test('ackThread is null when there are no acknowledgements', () => {
  assert.equal(ackThread(listing, 'Harry Hopkins', () => {}), null);
  assert.equal(ackThread({ documents: [] }, 'Sam Rayburn', () => {}), null);
});
