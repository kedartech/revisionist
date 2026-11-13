// Spec for 15a unit U3 (papers), written with the console contract: the unit makes it pass and
// never edits it. The tray sits under a kit panel head with its unread badge, its filters are a
// seg, each paper row carries the unread mark and a kind tag in words, and the acknowledgement
// list is headed by a kit label.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { installDom, words } from './dom-fake.js';

installDom();
const { trayView } = await import('../js/views/realism-tray.js');
const { ackThread } = await import('../js/views/realism-acks.js');
const { TONES } = await import('../js/views/ui-kit.js');

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const uncomment = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));
const OWNS = ['js/views/realism-tray.js', 'css/p4-tray.css', 'css/p4-acks.css', 'js/views/realism-acks.js'];
const tray = () => trayView(fixture.listing, () => {}, { filter: 'all', sort: 'newest' });

test('a kit panel head names the in-tray and badges the unread count', () => {
  const head = tray().querySelector('.panel-head');
  assert.ok(head, 'a .panel-head');
  assert.equal(words(head.querySelector('h2')), 'In-tray');
  assert.equal(words(head.querySelector('.badge')), String(fixture.listing.unread));
});

test('the filters are a seg and keep their tab semantics', () => {
  const list = tray().querySelector('[role="tablist"]');
  assert.ok(list, 'the filter tablist');
  assert.ok(list.classList.contains('seg'), 'the tablist is a .seg');
  assert.ok(list.querySelectorAll('[role="tab"]').length >= 4);
});

test('every paper row carries a kind tag in words, with a tone', () => {
  const rows = tray().querySelectorAll('.rl-row-paper');
  assert.ok(rows.length >= 5);
  for (const row of rows) {
    const tags = row.querySelectorAll('.tag');
    assert.equal(tags.length, 1, words(row));
    const word = words(tags[0]);
    assert.ok(word.length > 0, 'a kind word');
    assert.doesNotMatch(word, /_/, 'plain English, never a key');
    assert.ok(TONES.some((t) => tags[0].classList.contains(`tone-${t}`)), 'a kit tone');
  }
});

test('an unread paper row is marked unread, a read one is not', () => {
  const rows = tray().querySelectorAll('.rl-row-paper');
  let seen = 0;
  for (const doc of fixture.listing.documents) {
    const row = rows.find((r) => words(r).includes(doc.title));
    if (!row) continue;
    seen += 1;
    assert.equal(row.classList.contains('unread'), Boolean(doc.unread), doc.title);
  }
  assert.ok(seen >= 5);
  const css = uncomment(read('css/p4-tray.css'));
  assert.match(css, /\.rl-row-paper\.unread/, 'the unread mark is styled');
  assert.match(css, /\.rl-row-date\s*\{[^}]*var\(--font-chrome\)/, 'the date in mono');
});

test('the acknowledgements are headed by a kit label', () => {
  const author = fixture.listing.documents.find((d) => d.ack === true)?.author;
  const listing = author ? fixture.listing : { ...fixture.listing, documents: [{ ...fixture.listing.documents[0], ack: true, author: 'Harry Hopkins' }] };
  const acks = ackThread(listing, author ?? 'Harry Hopkins', () => {});
  assert.ok(acks, 'an acknowledgement list');
  assert.ok(acks.querySelector('h3').classList.contains('lbl'), 'the heading is a .lbl');
});

test('owned files: no HTML parsing, no inline style, no colour literal', () => {
  for (const f of OWNS) {
    const src = uncomment(read(f));
    assert.doesNotMatch(src, /innerHTML|style=|\.style\./, f);
    if (f.endsWith('.css')) assert.doesNotMatch(src, /#[0-9a-fA-F]{3,8}\b|rgba?\(/, f);
  }
});
