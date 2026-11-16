// Spec for Train 2 unit T, written with contract K2: the unit makes it pass and never edits it.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { TRAY_FILTERS, filterInTray, trayCounts, unreadCount } from '../js/realism-rules.js';
import { installDom, words } from './dom-fake.js';
import { traySections, trayListing, trayRows, trayView } from '../js/views/realism-tray.js';

installDom();

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

const receipt = (id, extra = {}) => doc(id, { ack: true, unread: true, ...extra });

test('there is no acknowledgements filter', () => {
  assert.deepEqual(TRAY_FILTERS.map(([key]) => key), ['all', 'unread', 'read', 'flagged', 'news']);
  assert.ok(!('acks' in trayCounts([receipt('k1')])));
  assert.throws(() => filterInTray([receipt('k1')], 'acks'));
});

test('a receipt is in no filter, read or unread', () => {
  const items = [doc('r1', { unread: true }), receipt('k1'), receipt('k2', { unread: false, flagged: true })];
  for (const [key] of TRAY_FILTERS) assert.ok(filterInTray(items, key).every((d) => !d.ack), key);
  assert.deepEqual(trayCounts(items), { all: 1, unread: 1, read: 0, flagged: 0, news: 1 });
});

test('an unread receipt adds nothing to the unread counts', () => {
  const items = [doc('r1', { unread: true }), receipt('k1'), receipt('k2')];
  assert.equal(unreadCount(items), 1);
  assert.equal(trayListing({ documents: items, unread: 3 }).unread, 1);
});

test('the filter bar draws no acknowledgements tab', () => {
  const tabs = [...trayView(fixture.listing, () => {}, { filter: 'all', sort: 'newest' }).querySelectorAll('[role="tab"]')];
  assert.equal(tabs.length, 5);
  assert.ok(tabs.every((t) => !/Acknowledgements/.test(words(t))));
});
