// Spec for Train 2 unit T, written with contract K2: the unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { traySections, trayRows } from '../js/views/realism-tray.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

const doc = (id, extra = {}) => ({ id, kind: 'memo', title: id, author: 'A', issued: '1941-10-01', arrives: '1941-10-02',
  channel: 'letter', classification: 'secret', unread: false, flagged: false, group: null, ack: false, answer: false, ...extra });

test('answers, then press, then reports, empty sections dropped', () => {
  const items = [doc('r1'), doc('p1', { kind: 'press' }), doc('a1', { answer: true }), doc('k1', { ack: true })];
  const out = traySections(items);
  assert.deepEqual(out.map((s) => s.key), ['answers', 'press', 'reports']);
  assert.deepEqual(out.map((s) => s.heading), ['Answers to your orders', 'Press', 'Reports']);
  assert.deepEqual(out[0].rows.map((r) => r.item.id), ['a1']);
  assert.deepEqual(out[1].rows.map((r) => r.item.id), ['p1']);
  assert.deepEqual(out[2].rows.map((r) => r.item.id), ['r1']);
  assert.deepEqual(traySections([doc('r2')]).map((s) => s.key), ['reports']);
  assert.deepEqual(traySections([]), []);
});

test('an acknowledgement is in no section, even when it answers an order', () => {
  const out = traySections([doc('k1', { ack: true, answer: true }), doc('k2', { ack: true })]);
  assert.deepEqual(out, []);
});

test('inside a section rows fold by group as trayRows does', () => {
  const items = [doc('g1', { group: 'MAGIC intercepts', arrives: '1941-10-03' }), doc('g2', { group: 'MAGIC intercepts' }), doc('r1')];
  const [reports] = traySections(items);
  assert.deepEqual(reports.rows, trayRows(items));
});

test('the fixture splits into its answers, press and reports', () => {
  const out = traySections(fixture.listing.documents);
  const ids = (key) => out.find((s) => s.key === key).rows.flatMap((r) => (r.type === 'group' ? r.items ?? [r.latest] : [r.item])).map((d) => d.id);
  assert.deepEqual(ids('answers'), ['d-report-1010']);
  assert.ok(ids('press').includes('d-press-1014'));
});

test('the tray view draws the sections', () => {
  const src = read('js/views/realism-tray.js');
  const view = src.slice(src.indexOf('export function trayView'));
  assert.match(view, /traySections\(/);
});
