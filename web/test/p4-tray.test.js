// Unit tests for the in-tray message list (In-Tray follow-up, unit T1). Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { rowLabel, trayRows } from '../js/views/realism-tray.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const { listing } = JSON.parse(readFileSync(join(WEB, 'test', 'fixtures', 'realism-seat.json'), 'utf8'));
const docs = listing.documents;

test('the module imports under node with no document', () => {
  assert.equal(typeof document, 'undefined');
  assert.equal(typeof trayRows, 'function');
});

test('grouped papers fold into one row, in order of the newest', () => {
  const rows = trayRows(docs);
  const groups = rows.filter((r) => r.type === 'group');
  const names = new Set(docs.filter((d) => d.group).map((d) => d.group));
  assert.equal(groups.length, names.size);
  const total = rows.reduce((n, r) => n + (r.type === 'group' ? r.count : 1), 0);
  assert.equal(total, docs.length);
  for (const g of groups) {
    const mine = docs.filter((d) => d.group === g.group);
    assert.equal(g.count, mine.length);
    assert.equal(g.unread, mine.filter((d) => d.unread).length);
    assert.equal(g.latest.arrives, mine.map((d) => d.arrives).sort().at(-1));
    assert.equal(rows.indexOf(g), rows.findIndex((r) => r.type === 'group' && r.group === g.group));
  }
});

test('a group sits where its newest paper sits', () => {
  const mk = (id, arrives, group) => ({ id, arrives, group, unread: id === 'b' });
  const items = [mk('a', '1941-10-20', null), mk('b', '1941-10-19', 'G'), mk('c', '1941-10-18', null), mk('d', '1941-10-17', 'G')];
  const rows = trayRows(items);
  assert.deepEqual(rows.map((r) => r.type), ['paper', 'group', 'paper']);
  assert.equal(rows[1].latest.id, 'b');
  assert.equal(rows[1].unread, 1);
  const oldest = trayRows([...items].reverse());
  assert.deepEqual(oldest.map((r) => r.type), ['paper', 'group', 'paper']);
  assert.equal(oldest[1].latest.id, 'b');
});

test('trayRows does not mutate its input', () => {
  const before = JSON.stringify(docs);
  trayRows(docs).forEach((r) => r.items?.push({}));
  assert.equal(JSON.stringify(docs), before);
});

test('row labels read for both kinds, singular and plural', () => {
  assert.equal(rowLabel({ type: 'paper', item: { author: 'Hull', title: 'Note' } }), 'Hull — Note');
  assert.equal(rowLabel({ type: 'group', group: 'MAGIC intercepts', count: 3 }), 'MAGIC intercepts (3 papers)');
  assert.equal(rowLabel({ type: 'group', group: 'MAGIC intercepts', count: 1 }), 'MAGIC intercepts (1 paper)');
});
