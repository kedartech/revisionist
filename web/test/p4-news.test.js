// Unit tests for the "What changed" block (Phase 4 unit H1). h() needs a DOM, so only the pure
// whatChanged is run; newsBlock's markup is checked against its source. Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { whatChanged } from '../js/views/realism-news.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));

function doc(id, over = {}) {
  return {
    id, kind: 'press', title: `Title ${id}`, author: 'New York Times', issued: '1941-10-14',
    arrives: '1941-10-14', channel: 'press', classification: 'open', unread: true, flagged: false,
    ...over,
  };
}

test('whatChanged keeps only unread press pages', () => {
  const listing = { documents: [
    doc('a'),
    doc('b', { unread: false }),
    doc('c', { kind: 'cable' }),
    doc('d', { kind: 'intercept' }),
  ] };
  assert.deepEqual(whatChanged(listing).map((x) => x.id), ['a']);
});

test('whatChanged sorts newest first, ties by id, and names the paper as the author', () => {
  const listing = { documents: [
    doc('m', { issued: '1941-10-14', author: 'Chicago Tribune' }),
    doc('z', { issued: '1941-10-16', author: 'Washington Post' }),
    doc('b', { issued: '1941-10-14' }),
  ] };
  assert.deepEqual(whatChanged(listing), [
    { id: 'z', title: 'Title z', paper: 'Washington Post', issued: '1941-10-16' },
    { id: 'b', title: 'Title b', paper: 'New York Times', issued: '1941-10-14' },
    { id: 'm', title: 'Title m', paper: 'Chicago Tribune', issued: '1941-10-14' },
  ]);
});

test('whatChanged returns at most five by default and honours a limit', () => {
  const documents = Array.from({ length: 8 }, (_, i) =>
    doc(`p${i}`, { issued: `1941-10-0${i + 1}` }));
  assert.equal(whatChanged({ documents }).length, 5);
  assert.deepEqual(whatChanged({ documents }, 1).map((x) => x.id), ['p7']);
});

test('whatChanged copes with an empty or press-free listing', () => {
  assert.deepEqual(whatChanged({ documents: [] }), []);
  assert.deepEqual(whatChanged({ documents: [doc('a', { kind: 'cable' })] }), []);
});

test('whatChanged does not mutate the listing', () => {
  const documents = [doc('a', { issued: '1941-10-01' }), doc('b', { issued: '1941-10-02' })];
  whatChanged({ documents });
  assert.deepEqual(documents.map((x) => x.id), ['a', 'b']);
});

test('the block is built with h, never with markup strings', () => {
  const source = readFileSync(join(WEB, 'js', 'views', 'realism-news.js'), 'utf8');
  assert.match(source, /from '\.\.\/dom\.js'/);
  assert.match(source, /'aria-labelledby': 'rl-news-h'/);
});
