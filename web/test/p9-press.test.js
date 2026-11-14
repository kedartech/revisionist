// The press desk: a newspaper icon beside Messages with an unread badge, a modal with one tab per
// paper, newest first in each, and the press gone from the In-Tray.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { buttons, installDom, words } from './dom-fake.js';
import {
  PRESS_SEEN_PREFIX, pressCounts, pressDock, pressFocus, pressMarks, pressPapers, pressSeen, pressTab, pressUnread,
} from '../js/views/realism-press.js';
import { trayView } from '../js/views/realism-tray.js';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const uncomment = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));

const LEDGER = 'The Washington Ledger';
const TIMES = 'New York Times';

const doc = (id, extra = {}) => ({ id, kind: 'memo', title: id, author: 'A', issued: '1941-10-01', arrives: '1941-10-02',
  channel: 'letter', classification: 'secret', unread: false, flagged: false, group: null, ack: false, answer: false, ...extra });
const press = (id, author, arrives, extra = {}) => doc(id, { kind: 'press', author, arrives, issued: arrives, title: `${author}: ${id}`, ...extra });

const ITEMS = [
  press('l1', LEDGER, '1941-10-02'),
  doc('m1'),
  press('t1', TIMES, '1941-10-05', { unread: true }),
  press('l3', LEDGER, '1941-10-09', { unread: true }),
  doc('c1', { kind: 'cable' }),
  press('l2', LEDGER, '1941-10-04'),
];

/** A storage stand-in with getItem and setItem. */
function memory(init = {}) {
  const data = new Map(Object.entries(init));
  return { getItem: (k) => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)), data };
}

test('one tab per paper, by name, and each paper\'s pages newest first', () => {
  const papers = pressPapers(ITEMS);
  assert.deepEqual(papers.map((p) => p.outlet), [TIMES, LEDGER].sort());
  const ledger = papers.find((p) => p.outlet === LEDGER);
  assert.deepEqual(ledger.pages.map((d) => d.id), ['l3', 'l2', 'l1'], 'newest first');
  assert.deepEqual(papers.find((p) => p.outlet === TIMES).pages.map((d) => d.id), ['t1']);
  assert.ok(papers.every((p) => p.pages.every((d) => d.kind === 'press')), 'nothing but press pages');
  assert.deepEqual(pressCounts(papers), { [LEDGER]: 3, [TIMES]: 1 });
  assert.deepEqual(pressPapers([doc('m1')]), [], 'no press, no tabs');
  assert.deepEqual(pressPapers(fixture.listing.documents).map((p) => p.outlet), [TIMES], 'the fixture\'s one paper');
});

test('the tab shown is the one picked while that paper is there, else the first', () => {
  const papers = pressPapers(ITEMS);
  assert.equal(pressTab(papers, TIMES), TIMES);
  assert.equal(pressTab(papers, 'Der Reichsbote'), papers[0].outlet);
  assert.equal(pressTab(papers, null), papers[0].outlet);
  assert.equal(pressTab([], null), null);
});

test('the badge counts the pages newer than the marks, never the ones already seen', () => {
  const papers = pressPapers(ITEMS);
  assert.equal(pressUnread(papers, {}), 4, 'nothing seen: every page');
  assert.equal(pressUnread(papers, { [LEDGER]: 3, [TIMES]: 1 }), 0, 'all seen: none');
  assert.equal(pressUnread(papers, { [LEDGER]: 2 }), 2, 'one new Ledger page and the Times page');
  installDom();
  const on = pressDock({ state: { open: false, tab: null }, onState() {}, papers, marks: { [LEDGER]: 1 } });
  const btn = on.querySelector('.rl-press-btn');
  assert.equal(words(btn.querySelector('.rl-press-count')), '3 unread');
  assert.equal(btn.getAttribute('aria-expanded'), 'false');
  const none = pressDock({ state: { open: false, tab: null }, onState() {}, papers, marks: { [LEDGER]: 3, [TIMES]: 1 } });
  assert.equal(none.querySelector('.rl-press-count'), null, 'no badge with nothing new');
});

test('the marks follow the messenger: the paper on show is seen, and a mark above its count settles', () => {
  const papers = pressPapers(ITEMS);
  const counts = pressCounts(papers);
  assert.deepEqual(pressMarks(counts, {}, { open: true, tab: TIMES }), { [TIMES]: 1 });
  assert.deepEqual(pressMarks(counts, { [LEDGER]: 1 }, { open: false, tab: TIMES }), { [LEDGER]: 1 }, 'closed: nothing is seen');
  assert.deepEqual(pressMarks(counts, { [LEDGER]: 9 }, { open: false, tab: null }), { [LEDGER]: 3 }, 'settled to the count');
  const store = memory();
  const seen = pressSeen(store, 'c-1');
  assert.deepEqual(seen.read(), {});
  seen.write({ [LEDGER]: 2 });
  assert.deepEqual(seen.read(), { [LEDGER]: 2 });
  assert.ok(store.data.has(`${PRESS_SEEN_PREFIX}c-1`));
  assert.deepEqual(pressSeen(memory({ [`${PRESS_SEEN_PREFIX}c-1`]: '[1' }), 'c-1').read(), {}, 'a broken value reads as nothing seen');
  assert.deepEqual(pressSeen(null, 'c-1').read(), {});
});

test('the desk shows the paper on show newest first, and a page opens as the paper view does', () => {
  installDom();
  const papers = pressPapers(ITEMS);
  const opened = [];
  const picked = [];
  const dock = pressDock({
    state: { open: true, tab: LEDGER }, onState: (s) => picked.push(s), papers, marks: {},
    onOpen: (d) => opened.push(d.id),
  });
  const desk = dock.querySelector('dialog.rl-pd');
  assert.ok(desk, 'the desk is a dialog');
  const tabs = desk.querySelectorAll('[role="tab"]');
  assert.deepEqual(tabs.map((t) => t.getAttribute('aria-selected')), papers.map((p) => String(p.outlet === LEDGER)));
  const rows = desk.querySelectorAll('.rl-pd-list .rl-row');
  assert.deepEqual(rows.map((r) => words(r.querySelector('.rl-row-title'))), ['l3', 'l2', 'l1'].map((id) => `${LEDGER}: ${id}`));
  assert.ok(rows[0].classList.contains('unread'));
  rows[1].click();
  assert.deepEqual(opened, ['l2']);
  tabs.find((t) => t.getAttribute('aria-selected') === 'false').click();
  assert.deepEqual(picked, [{ open: true, tab: TIMES }]);

  const page = { ...fixture.page, item: { ...ITEMS[0], flagged: false } };
  const reading = pressDock({ state: { open: true, tab: LEDGER }, onState() {}, papers, marks: {}, page, onClosePage() {} });
  assert.equal(buttons(reading, 'Close folder').length, 1, 'the paper view\'s own folder');
  const empty = pressDock({ state: { open: true, tab: null }, onState() {}, papers: [], marks: {} });
  assert.match(words(empty.querySelector('dialog')), /No paper has reached you yet/);
});

test('Esc and the close button shut the desk, and focus goes back to the icon', () => {
  installDom();
  const papers = pressPapers(ITEMS);
  const states = [];
  const root = document.createElement('div');
  document.body.append(root);
  const draw = (state) => root.replaceChildren(pressDock({ state, onState: (s) => states.push(s), papers, marks: {} }));
  draw({ open: true, tab: LEDGER });
  const desk = root.querySelector('dialog.rl-pd');
  desk.showModal();
  const esc = { type: 'keydown', key: 'Escape', defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() {} };
  desk.dispatchEvent(esc);
  assert.equal(desk.open, false, 'Esc closes it');
  assert.deepEqual(states, [{ open: false, tab: LEDGER }]);
  draw({ open: false, tab: LEDGER });
  pressFocus(root);
  assert.equal(document.activeElement, root.querySelector('.rl-press-btn'), 'focus is back on the icon');

  draw({ open: true, tab: LEDGER });
  const again = root.querySelector('dialog.rl-pd');
  again.showModal();
  buttons(again, 'Close')[0].click();
  assert.equal(again.open, false);
  assert.deepEqual(states.at(-1), { open: false, tab: LEDGER });
  assert.equal(states.length, 2, 'one close, one state');
});

test('the tray has no press, in any filter and in its counts', () => {
  installDom();
  const listing = { unread: 2, flagged: 0, documents: ITEMS };
  for (const filter of ['all', 'unread', 'read', 'news']) {
    const tray = trayView(listing, () => {}, { filter });
    assert.doesNotMatch(words(tray), /Washington Ledger|New York Times/, filter);
  }
  const all = trayView(listing, () => {}, { filter: 'all' });
  assert.deepEqual(all.querySelectorAll('.rl-tray-head').map(words), ['Reports'], 'no Press section');
  assert.equal(words(all.querySelector('[id="rl-filter-all"] .rl-count')), '2', 'the press is not counted');
  assert.equal(words(all.querySelector('[id="rl-filter-unread"] .rl-count')), '0');
  assert.equal(words(all.querySelector('.panel-head .badge')), '0', 'the unread badge leaves the press out');
  const fixtureTray = trayView(fixture.listing, () => {}, { filter: 'all' });
  assert.doesNotMatch(words(fixtureTray), /New York Times/);
  assert.equal(words(fixtureTray.querySelector('.panel-head .badge')),
    String(fixture.listing.documents.filter((d) => d.unread && !d.ack && d.kind !== 'press').length));
});

test('the room wires the desk beside Messages, and What changed opens it', () => {
  const room = read('js/views/realism-room.js');
  assert.ok(room.includes("from './realism-press.js'"));
  assert.ok(room.includes('pressDock('));
  assert.match(room, /newsBlock\(whatChanged\(rv\.documents\), \(id\) => readPress\(/);
});

test('phone: the desk fills the screen; the files write no inline style and no HTML', () => {
  const css = uncomment(read('css/p5-press.css'));
  const phone = css.slice(css.indexOf('@media (max-width: 767px)'));
  assert.ok(css.includes('@media (max-width: 767px)'));
  assert.match(phone, /dialog\.rl-pd\s*\{[^}]*inset:\s*0/);
  assert.match(phone, /dialog\.rl-pd\s*\{[^}]*max-width:\s*none/);
  assert.match(phone, /dialog\.rl-pd\s*\{[^}]*max-height:\s*none/);
  const src = uncomment(read('js/views/realism-press.js'));
  assert.doesNotMatch(src, /innerHTML|style=|\.style\./);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(/);
});
