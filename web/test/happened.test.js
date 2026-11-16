// What you missed: one page for every wake the seat missed, and the owner's note of what the
// aide filed. The room asks the server for `catchup` on load; nothing comes from browser storage.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api, ApiError } = await import('../js/api.js');
const { realismRoom, uiFor } = await import('../js/views/realism-room.js');
const { MISSED_TITLE, aideNote, missedLines, missedPages, missedSheet } = await import('../js/views/realism-happened.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

const ORDERS = fixture.record.orders;
const idOf = (asked) => ORDERS.find((o) => o.asked === asked).id;
const WHEELER = idOf('Ask Senator Wheeler to drop his filibuster');
const LEND = idOf('Allocate Lend-Lease aid: Britain, 40');

const page = (number, extra = {}) => ({
  number, opened: `${number + 14} October 1941`, days_passed: 6, papers: 0, filed: [], settled: [], ...extra,
});
const THREE = [
  page(2, { settled: [WHEELER], papers: 2 }),
  page(3, { aide_filed: ['Escort the convoys to Iceland', 'Base a destroyer squadron at Reykjavik'] }),
  page(4, { settled: [LEND], papers: 1, days_passed: 1 }),
];

test('the client asks the server for catchup, with the range it names or none', async () => {
  const seen = [];
  api.realism = async (action, body) => { seen.push([action, body]); return { first: 0, last: 0, pages: [] }; };
  await api.catchup();
  await api.catchup({ first: 2, last: 4 });
  assert.deepEqual(seen, [['catchup', {}], ['catchup', { first: 2, last: 4 }]]);
});

test('missedPages reads the reply into pages, oldest first, and tolerates an empty or odd reply', () => {
  assert.deepEqual(missedPages({ pages: [page(4), page(2), page(3)] }).map((p) => p.number), [2, 3, 4]);
  assert.deepEqual(missedPages({}), []);
  assert.deepEqual(missedPages(null), []);
  assert.deepEqual(missedPages({ pages: 'x' }), []);
  assert.deepEqual(missedPages({ pages: [null, page(1), { opened: 'x' }] }).map((p) => p.number), [1]);
});

test('the aide\'s note names the wake and the orders it filed, in the order\'s words', () => {
  assert.equal(aideNote(THREE[1]), 'Your aide played wake 3 for you: Escort the convoys to Iceland; Base a destroyer squadron at Reykjavik.');
  assert.equal(aideNote(page(5, { aide_filed: ['Allocate Lend-Lease aid: Britain, 40'] })), 'Your aide played wake 5 for you: Allocate Lend-Lease aid: Britain, 40.');
  assert.equal(aideNote(page(5, { aide_filed: [] })), 'Your aide played wake 5 for you and filed nothing.');
});

test('a page with no aide_filed key carries no note; the note comes only from the server\'s key', () => {
  assert.equal(aideNote(page(3)), null);
  assert.equal(aideNote(page(3, { by_aide: true })), null);
});

test('settled orders are told as sentences from the record; an id the record does not hold is left out', () => {
  assert.deepEqual(missedLines(THREE[0], fixture.record), ['“Ask Senator Wheeler to drop his filibuster” has been rebuffed. “Wheeler would not be moved while the America First rallies go on.”']);
  assert.deepEqual(missedLines(page(2, { settled: ['ffffffffffff'] }), fixture.record), []);
  assert.deepEqual(missedLines(page(2), fixture.record), []);
  assert.deepEqual(missedLines(page(2, { settled: [LEND] }), null), []);
});

test('the sheet is a dialog headed What you missed with one section for every wake, oldest first', () => {
  const sheet = missedSheet({ pages: THREE, record: fixture.record, onClose: () => {} });
  assert.equal(sheet.tagName, 'DIALOG');
  assert.ok(sheet.classList.contains('rl-hap'));
  assert.ok(sheet.classList.contains('rl-missed'));
  assert.equal(sheet.getAttribute('aria-labelledby'), 'rl-missed-title');
  assert.equal(words(sheet.querySelector('h2')), MISSED_TITLE);
  assert.equal(MISSED_TITLE, 'What you missed');
  const sections = sheet.querySelectorAll('section.rl-missed-page');
  assert.equal(sections.length, 3);
  assert.deepEqual(sections.map((s) => words(s.querySelector('h3'))), [
    'Wake 2: 16 October 1941', 'Wake 3: 17 October 1941', 'Wake 4: 18 October 1941',
  ]);
});

test('each page tells the days that passed, its settled orders and the papers that came', () => {
  const [one, , three] = missedSheet({ pages: THREE, record: fixture.record, onClose: () => {} }).querySelectorAll('section.rl-missed-page');
  assert.match(words(one), /6 days have passed\./);
  assert.match(words(one), /Ask Senator Wheeler to drop his filibuster” has been rebuffed/);
  assert.match(words(one), /2 new papers reached your tray\./);
  assert.match(words(three), /1 day has passed\./);
  assert.match(words(three), /Allocate Lend-Lease aid: Britain, 40” has been enacted\./);
  assert.match(words(three), /1 new paper reached your tray\./);
});

test('a wake with nothing to tell still has its page, and says so', () => {
  const sheet = missedSheet({ pages: [page(7, { days_passed: 0 })], record: fixture.record, onClose: () => {} });
  const [only] = sheet.querySelectorAll('section.rl-missed-page');
  assert.match(words(only), /Nothing reached you in this wake\./);
});

test('the aide\'s note shows on the wake the aide played, and on no other', () => {
  const sheet = missedSheet({ pages: THREE, record: fixture.record, onClose: () => {} });
  const [one, two, three] = sheet.querySelectorAll('section.rl-missed-page');
  assert.equal(one.querySelector('.rl-missed-aide'), null);
  assert.equal(three.querySelector('.rl-missed-aide'), null);
  assert.equal(words(two.querySelector('.rl-missed-aide')), aideNote(THREE[1]));
  assert.equal(sheet.querySelectorAll('.rl-missed-aide').length, 1);
});

test('orders held after commit that did not go through are listed on their wake, as the server words them', () => {
  const dropped = page(3, { held_dropped: ['Send the fleet was not filed: the seat had left.'] });
  const sheet = missedSheet({ pages: [dropped], record: fixture.record, onClose: () => {} });
  assert.match(words(sheet), /Send the fleet was not filed: the seat had left\./);
});

test('To the desk closes the sheet through onClose', () => {
  let n = 0;
  const sheet = missedSheet({ pages: THREE, record: fixture.record, onClose: () => { n += 1; } });
  const [done] = buttons(sheet, 'To the desk');
  assert.ok(done);
  assert.equal(done.getAttribute('type'), 'button');
  done.click();
  assert.equal(n, 1);
});

test('the sheet builds text with h(), never from markup, and keeps no browser storage', () => {
  const src = read('js/views/realism-happened.js');
  const head = src.slice(src.indexOf('MISSED_TITLE'));
  assert.doesNotMatch(head, /localStorage|sessionStorage|getItem|setItem|storage\(/);
  assert.doesNotMatch(src, /innerHTML|insertAdjacentHTML/);
  const hostile = missedSheet({ pages: [page(2, { aide_filed: ['<img src=x onerror=alert(1)>'] })], record: fixture.record, onClose: () => {} });
  assert.equal(hostile.querySelectorAll('img').length, 0);
  assert.match(words(hostile), /<img src=x onerror=alert\(1\)>/);
});

/** The whole room for a fresh game; `catchup` answers the catchup call; `touched` lists storage calls. */
function room(catchup, id = `g-${Math.random()}`) {
  const doc = installDom();
  const touched = [];
  const asked = [];
  globalThis.localStorage = {
    getItem: (k) => { touched.push(k); return null; },
    setItem: (k) => { touched.push(k); },
    removeItem: (k) => { touched.push(k); },
  };
  globalThis.sessionStorage = globalThis.localStorage;
  api.realism = async (action, body) => {
    if (action !== 'catchup') return {};
    asked.push(body);
    return catchup();
  };
  const rv = { ...fixture, documents: fixture.listing, wake_tick: 1 };
  const me = { account: { handle: 'josh' }, game: { id, name: 'Autumn 1941', view: { realism: rv, seat: { name: 'Franklin D. Roosevelt' } } } };
  const root = realismRoom({ me, refresh: async () => {}, go: () => {} });
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  return { root, id, touched, asked, me };
}

test('on load the room asks for catchup with no range and opens one page per wake missed', async () => {
  const { root, asked } = room(async () => ({ first: 2, last: 4, pages: THREE }));
  await flush();
  assert.deepEqual(asked, [{}]);
  const sheet = root.querySelector('dialog.rl-missed');
  assert.ok(sheet, 'the sheet is in the room');
  assert.equal(sheet.open, true);
  assert.equal(sheet.querySelectorAll('section.rl-missed-page').length, 3);
  assert.match(words(sheet), /Your aide played wake 3 for you: Escort the convoys to Iceland; Base a destroyer squadron at Reykjavik\./);
});

test('with no wake missed there is no sheet', async () => {
  const { root, asked } = room(async () => ({ first: 4, last: 3, pages: [] }));
  await flush();
  assert.equal(asked.length, 1);
  assert.equal(root.querySelector('dialog.rl-missed'), null);
});

test('closing the sheet shows it no more in this room, and the room asks once', async () => {
  const { root, asked, me } = room(async () => ({ first: 2, last: 4, pages: THREE }));
  await flush();
  const sheet = root.querySelector('dialog.rl-missed');
  buttons(sheet, 'To the desk')[0].click();
  assert.equal(sheet.open, false);
  const again = realismRoom({ me, refresh: async () => {}, go: () => {} });
  await flush();
  assert.equal(again.querySelector('dialog.rl-missed'), null);
  assert.equal(asked.length, 1, 'the second room draw did not ask again');
});

test('a sheet left open stays when the room is redrawn', async () => {
  const { root } = room(async () => ({ first: 2, last: 4, pages: THREE }));
  await flush();
  const sheet = root.querySelector('dialog.rl-missed');
  assert.ok(sheet.open);
  const press = root.querySelector('.rl-viewswitch button');
  press?.click();
  const after = root.querySelector('dialog.rl-missed');
  assert.ok(after, 'still in the room');
  assert.equal(after.open, true);
});

test('a room drawn again while the sheet is open keeps it open, over the wake sheet', async () => {
  const { root, me, asked } = room(async () => ({ first: 2, last: 4, pages: THREE }), 'g-again');
  await flush();
  assert.ok(root.querySelector('dialog.rl-missed').open);
  const again = realismRoom({ me, refresh: async () => {}, go: () => {} });
  globalThis.document.body.append(again);
  await flush();
  const sheet = again.querySelector('dialog.rl-missed');
  assert.ok(sheet, 'the second drawing has the sheet');
  assert.equal(sheet.open, true);
  assert.equal(sheet.querySelectorAll('section.rl-missed-page').length, 3);
  assert.equal(asked.length, 1, 'and did not ask again');
});

test('what the room reads and writes in browser storage is the same with pages or without', async () => {
  const withPages = room(async () => ({ first: 2, last: 4, pages: THREE }), 'g-same');
  await flush();
  buttons(withPages.root.querySelector('dialog.rl-missed'), 'To the desk')[0].click();
  const keysWith = [...new Set(withPages.touched)].sort();
  uiFor('other');
  const without = room(async () => ({ first: 4, last: 3, pages: [] }), 'g-same');
  await flush();
  assert.deepEqual([...new Set(without.touched)].sort(), keysWith);
  assert.ok(keysWith.every((k) => !/missed|catchup/i.test(k)), keysWith.join(','));
});

test('a refusal from the server for the range leaves the room as it was', async () => {
  const { root } = room(async () => { throw new ApiError(400, 'Name wakes from 0 to 3, the first no later than the last.'); });
  await flush();
  assert.equal(root.querySelector('dialog.rl-missed'), null);
  assert.equal(root.querySelector('.rl-status.error'), null);
});

test('a server that did not answer is said in the room\'s status line, and the room still works', async () => {
  const { root } = room(async () => { throw new ApiError(0, 'The game server didn\'t respond. Your text is still here.'); });
  await flush();
  assert.equal(root.querySelector('dialog.rl-missed'), null);
  assert.match(words(root.querySelector('.rl-status')), /What you missed could not be loaded/);
});
