// The map-first room gives the map the screen (RMT), one test or more per rule, on a seat built
// here with 21 nations: 1. everything above the map is one bar (the date, the wake's clock with
// the players done, the three aim marks, one Nations control, the sheet tabs, Done and the game
// menu); 2. the nations' figures and bands, the come-back line and the first-day card are not
// above the map: the Nations control opens the chips in a sheet, the come-back line heads "What
// needs you" and the first-day card is its first row; 3. the status line sits over the map's
// lower edge and takes no row; 4. the map keeps a floor of 320 px and the room scrolls under it;
// 5. what the room puts over the map is measured by the browser smoke; 6. the room hands the map
// `overlay` and `onFull`; 7. an aim mark shows its status by shape and opens the aims; 8. a line
// of the list is one row that opens in place. Keeps: the Classic layout is drawn as today.
// Mutants: the chips left above the map; the map squeezed under its floor instead of the room
// scrolling; the first-day card unreachable after the move.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { realismRoom } = await import('../js/views/realism-room.js');
const { setRoomLayout } = await import('../js/views/realism-sheets.js');
const { hooksFor } = await import('../js/views/realism-theatre.js');
const { FIRST_WAKE } = await import('../js/views/realism-firstwake.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');

const NATIONS = 21;
const nation = (i) => ({ key: `N${i}`, name: `Nation ${i}`, relation: i === 0 ? 'own' : i % 3 === 0 ? 'enemy' : 'neutral' });

/** The seat's view on the toy board with 21 nations in its economy and at home; `change` edits it. */
function seat(change = () => {}) {
  const rv = structuredClone(fixture);
  rv.map = structuredClone(fixture.territory_map);
  rv.documents = structuredClone(fixture.listing);
  rv.wake_tick = 1;
  rv.style = 'free';
  rv.wake = { ...rv.wake, deadline: '2999-01-01T00:00:00+00:00', you_committed: false, humans: 3, committed: 1 };
  rv.economy = { ...rv.economy, figures: Array.from({ length: NATIONS }, (_, i) => ({ nation: nation(i), figure: 100 - i })) };
  rv.home = { ...rv.home, chambers: [], standings: Array.from({ length: NATIONS }, (_, i) => ({ nation: nation(i), band: 'steady' })) };
  change(rv);
  return rv;
}

/** The whole room for view `rv` in `layout`, as the page draws it. */
function room(rv, layout = 'map', id = `h10-${Math.random()}`) {
  const doc = installDom();
  setRoomLayout(layout);
  api.realism = async () => ({});
  api.catchup = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  const game = { id, name: 'Autumn 1941', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'Franklin D. Roosevelt' } } };
  const ctx = { me: { account: { handle: 'josh' }, game }, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {}, signOut: () => {} };
  const root = realismRoom(ctx);
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  return { root, now: () => doc.body.firstElementChild };
}

const key = (el, k) => el.dispatchEvent({
  type: 'keydown', key: k, target: el, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() {},
});
/** The room's own children above the map (dialogs aside, which are not drawn until opened). */
const aboveMap = (root) => {
  const out = [];
  for (const c of root.children) {
    if (c.matches('main.rl-mapfirst')) return out;
    if (c.tagName !== 'DIALOG') out.push(c);
  }
  return out;
};
const openSheets = (root) => root.querySelectorAll('.rl-over').map((s) => s.getAttribute('data-sheet'));
const wake0 = { wake: 0, deadline: '2999-01-01T00:00:00+00:00', committed: 0, humans: 1, you_committed: false, is_host: true, can_close: true };

// rule 1: one bar above the map

test('everything above the map in the map-first room is one bar', () => {
  const { root } = room(seat());
  const above = aboveMap(root);
  assert.equal(above.length, 1, `one element above the map, not ${above.map((e) => e.className).join(' | ')}`);
  assert.ok(above[0].classList.contains('rl-roombar'));
  assert.equal(root.querySelector('.frame-head'), null, 'the page header is not drawn in the map-first room');
  assert.equal(root.querySelector('.rl-strip'), null, 'nor the status strip');
});

test('the bar holds the date, the clock with the players done, the aims, the group tabs, the chat button, Done and the menu', () => {
  const { root } = room(seat());
  const bar = root.querySelector('.rl-roombar');
  assert.ok(words(bar.querySelector('.rl-bar-date')).includes('1941'), 'the date');
  const clock = bar.querySelector('.rl-bar-clock');
  assert.ok(clock, 'the clock for the wake\'s close');
  assert.ok(clock.querySelector('.rl-countdown'), 'how long is left');
  assert.equal(clock.querySelector('.rl-done-bar').getAttribute('aria-label'), '1 of 3 players done');
  assert.equal(bar.querySelectorAll('.rl-aimmark').length, 3, 'three aim marks');
  assert.equal(bar.querySelectorAll('.rl-nations-btn').length, 0, 'no Nations control once the four groups are in: Nations is a part of World');
  assert.ok(bar.querySelector('.rl-sheettabs'), 'the sheet tabs');
  assert.ok(bar.querySelector('.rl-chat-btn'), 'the chat button');
  assert.equal(buttons(bar, 'Done for today').length, 1, 'Done for today');
  assert.ok(bar.querySelector('.rl-menu-btn'), 'the game menu');
});

test('a single player sees the clock and no players-done bar; a seat that is done sees that it is', () => {
  const { root } = room(seat((rv) => { rv.wake = { ...rv.wake, humans: 1, committed: 0, you_committed: true }; }));
  const bar = root.querySelector('.rl-roombar');
  assert.equal(bar.querySelector('.rl-done-bar'), null);
  assert.equal(buttons(bar, 'Done for today').length, 0);
  assert.ok(bar.querySelector('.rl-committed'), 'the seat is told it is done');
});

test('what the page header held is reachable from the game menu', () => {
  const { root } = room(seat());
  const menu = root.querySelector('dialog.rl-menu');
  const names = menu.querySelectorAll('button').map(words);
  assert.ok(names.includes('Autumn 1941'), 'the campaign\'s name opens the setting');
  assert.ok(names.includes('Franklin D. Roosevelt'), 'the seat\'s name opens the dossier');
  assert.ok(names.includes('Report a bug'));
  assert.ok(names.includes('Sign out'));
  assert.ok(words(menu).includes('Signed in as josh'));
  assert.ok(menu.querySelector('.rl-wake'), 'the wake\'s own line, with Run the day now for the host');
});

// rule 2: nothing of the nations, the come-back line or the first-day card above the map

test('the nations\' chips and bands are not above the map: World opens them in its Nations part', () => {
  const { root, now } = room(seat());
  for (const el of aboveMap(root)) {
    assert.equal(el.querySelectorAll('.rl-eco-chip').length, 0, 'no war-economy chip above the map');
    assert.equal(el.querySelectorAll('.rl-home-chip').length, 0, 'no band above the map');
    assert.equal(el.querySelectorAll('.rl-comeback').length, 0, 'no come-back line above the map');
    assert.equal(el.querySelectorAll('.rl-firstwake').length, 0, 'no first-day card above the map');
  }
  const world = (el) => el.querySelectorAll('.rl-sheettabs button').find((b) => b.getAttribute('data-group') === 'world');
  world(root).click();
  const sheet = now().querySelector('.rl-over');
  assert.equal(sheet.getAttribute('data-sheet'), 'nations');
  assert.equal(sheet.querySelectorAll('.rl-eco-chip').length, NATIONS, 'every nation\'s chip');
  assert.ok(sheet.querySelector('.rl-home-own'), 'the seat\'s band, which opens its home sheet');
  assert.equal(world(now()).getAttribute('aria-expanded'), 'true');
});

test('with neither an economy nor a reading at home World has no Nations part', () => {
  const { root, now } = room(seat((rv) => { rv.economy = null; rv.home = null; }));
  root.querySelectorAll('.rl-sheettabs button').find((b) => b.getAttribute('data-group') === 'world').click();
  assert.deepEqual(now().querySelectorAll('.rl-over .rl-parts button').map((b) => b.getAttribute('data-sheet')), ['diplomacy']);
});

test('the come-back line heads What needs you', () => {
  const { root } = room(seat());
  const list = root.querySelector('.rl-needs');
  const line = list.querySelector('.rl-comeback');
  assert.ok(line, 'the come-back line is in the list');
  assert.ok(words(line).startsWith('When you come back'));
  const kids = list.children;
  assert.ok(kids[0].classList.contains('rl-needs-head') && kids[1] === line, 'right under the list\'s heading');
});

test('the first-day card is the first row of What needs you, opens in place and can be dismissed', () => {
  const { root, now } = room(seat((rv) => { rv.wake = wake0; rv.agenda = { ...rv.agenda, items: [{ id: 'A1', kind: 'Order', text: 'A matter.', issuer: 'The President', issued: '1941-10-01', deadline: '1941-10-20', options: [] }] }; }));
  const rows = root.querySelectorAll('.rl-needs .rl-need');
  assert.ok(rows.length >= 2);
  const first = rows[0];
  assert.equal(first.getAttribute('data-kind'), 'first');
  assert.equal(words(first.querySelector('.rl-need-what')), FIRST_WAKE.heading);
  first.querySelector('.rl-need-row').click();
  const open = now().querySelectorAll('.rl-needs .rl-need')[0];
  assert.equal(open.querySelector('.rl-need-row').getAttribute('aria-expanded'), 'true');
  const detail = open.querySelector('.rl-need-detail');
  assert.equal(detail.hasAttribute('hidden'), false, 'the steps are shown');
  assert.equal(detail.querySelectorAll('li').length, 3, 'the three steps');
  buttons(detail, FIRST_WAKE.dismiss)[0].click();
  assert.equal(now().querySelectorAll('.rl-needs .rl-need').filter((r) => r.getAttribute('data-kind') === 'first').length, 0, 'dismissed');
});

// rule 3: the status line takes no row

test('the status line is drawn over the map, not as a row above it', () => {
  const { root } = room(seat());
  assert.ok(root.querySelector('.rl-mapfirst-map .rl-status'), 'inside the map');
  const css = read('css/c-sheets.css');
  assert.match(css, /\.rl-mapfirst-map > \.rl-status\s*\{[^}]*position:\s*absolute/, 'over the map, in no row of its own');
  assert.match(css, /\.rl-mapfirst-map\s*\{[^}]*position:\s*relative/);
});

// rule 4: the map's floor

test('the map never has less than 320 px; a room too short for that scrolls as a page', () => {
  const css = read('css/c-sheets.css');
  const rule = (sel) => {
    const at = css.indexOf(`${sel} {`);
    assert.ok(at >= 0, `${sel} has a rule`);
    return css.slice(at, css.indexOf('}', at));
  };
  const screen = rule('.screen.war-screen.realism-screen.rl-layout-map');
  assert.match(screen, /height:\s*auto/, 'the room is as tall as it needs to be');
  assert.match(screen, /min-height:\s*100(d)?vh/, 'and at least the viewport');
  assert.match(screen, /grid-template-rows:\s*auto minmax\(320px, 1fr\)/, 'the bar, then the map with its floor');
  assert.doesNotMatch(screen, /overflow:\s*hidden/, 'the page is not cut');
  const map = rule('.rl-layout-map .rl-mapfirst');
  assert.match(map, /min-height:\s*320px/);
});

// rule 6: the room's hooks for the map

test('the map-first room hands the map overlay and onFull; the classic room does not', () => {
  const { root } = room(seat());
  const hooks = hooksFor(root.querySelector('.rl-mapfirst .rl-theatre'));
  assert.equal(hooks?.overlay, true);
  assert.equal(typeof hooks?.onFull, 'function');
  const classic = room(seat(), 'room');
  const map = classic.root.querySelector('.rl-theatre');
  assert.ok(!hooksFor(map)?.overlay, 'the classic room\'s map keeps its rows');
});

test('full screen hides the bar and keeps What needs you, an open sheet and Done; Escape with no sheet leaves it', () => {
  const { root, now } = room(seat());
  hooksFor(root.querySelector('.rl-mapfirst .rl-theatre')).onFull(true);
  assert.ok(now().classList.contains('rl-full'));
  const css = read('css/c-sheets.css');
  assert.match(css, /\.rl-full \.rl-roombar\s*\{[^}]*display:\s*none/, 'the bar is hidden');
  assert.ok(now().querySelector('.rl-needs'), 'What needs you stays');
  assert.ok(now().querySelector('.rl-needs-commit'), 'and Done');
  // a sheet opened in full screen: Escape closes the sheet first, and full screen stays
  now().querySelector('.rl-sheettabs button').click();
  assert.equal(openSheets(now()).length, 1);
  assert.ok(now().classList.contains('rl-full'), 'a sheet keeps full screen');
  key(now().querySelector('.rl-over'), 'Escape');
  assert.equal(openSheets(now()).length, 0);
  assert.ok(now().classList.contains('rl-full'), 'Escape closed the sheet only');
  key(now(), 'Escape');
  assert.ok(!now().classList.contains('rl-full'), 'Escape with no sheet open leaves full screen');
});

// rule 7: the aim marks

test('each aim mark shows its status by shape and in its name, and the marks open the aims', () => {
  const { root, now } = room(seat());
  const marks = root.querySelectorAll('.rl-aimmark');
  const statuses = marks.map((m) => m.getAttribute('data-status'));
  assert.deepEqual(statuses, fixture.stakes.aims.slice(0, 3).map((a) => a.status));
  const shape = (status) => marks.find((m) => m.getAttribute('data-status') === status)?.querySelector('svg')?.getAttribute('data-shape');
  const shapes = [...new Set(statuses)].map(shape);
  assert.equal(new Set(shapes).size, shapes.length, 'a different shape for each status');
  for (const m of marks) assert.match(m.getAttribute('aria-label'), /^Aim \d: (Met|At risk|Failed)\. /);
  marks[1].click();
  assert.deepEqual(openSheets(now()), ['aims']);
  const sheet = now().querySelector('.rl-over');
  assert.equal(sheet.querySelectorAll('.rl-aim-toggle').length, fixture.stakes.aims.length, 'the drill-down as today');
  assert.ok(sheet.querySelector('.rl-stakes-list'), 'and what is at stake');
});

test('every shape the marks draw is set apart: met, at risk and failed', () => {
  const rv = seat((r) => { r.stakes.aims = ['met', 'at_risk', 'failed'].map((status, i) => ({ ...r.stakes.aims[0], aim: i + 1, status })); });
  const { root } = room(rv);
  const shapes = root.querySelectorAll('.rl-aimmark svg').map((s) => s.getAttribute('data-shape'));
  assert.deepEqual(shapes, ['met', 'at_risk', 'failed']);
  const paths = root.querySelectorAll('.rl-aimmark svg').map((s) => s.querySelectorAll('path').map((p) => p.getAttribute('d')).join('|'));
  assert.equal(new Set(paths).size, 3, 'three drawings, not one drawing in three colours');
});

// rule 8: a line is one row that opens in place

test('a line of What needs you is one row: its kind\'s mark, its title and its due day; it opens to the detail and its action', () => {
  const rv = seat((r) => { r.agenda = { ...r.agenda, items: [{ id: 'A1', kind: 'Order', text: 'A matter.', issuer: 'The President', issued: '1941-10-01', deadline: '1941-10-20', options: [] }] }; });
  const { root, now } = room(rv);
  const row = root.querySelectorAll('.rl-needs .rl-need').find((r) => r.getAttribute('data-need') === 'A1');
  const head = row.querySelector('button.rl-need-row');
  assert.equal(head.getAttribute('aria-expanded'), 'false');
  assert.ok(head.querySelector('.rl-need-mark svg'), 'a mark for its kind');
  assert.equal(words(head.querySelector('.rl-need-what')), 'A matter.');
  assert.ok(words(head.querySelector('.rl-need-due')).startsWith('Due'));
  assert.ok(row.querySelector('.rl-need-detail').hasAttribute('hidden'), 'the detail is folded');
  head.click();
  const open = now().querySelectorAll('.rl-needs .rl-need').find((r) => r.getAttribute('data-need') === 'A1');
  assert.equal(open.querySelector('.rl-need-row').getAttribute('aria-expanded'), 'true', 'kept over the redraw');
  const detail = open.querySelector('.rl-need-detail');
  assert.equal(detail.hasAttribute('hidden'), false);
  assert.ok(words(detail).includes('From The President'));
  assert.ok(detail.querySelector('.rl-need-act'), 'its action');
});

// keeps: the Classic layout as today

test('the Classic layout keeps its header, its strip with the chips and the come-back line, and its card', () => {
  const { root } = room(seat((rv) => { rv.wake = wake0; }), 'room');
  assert.ok(root.querySelector('.frame-head'));
  const strip = root.querySelector('.rl-strip');
  assert.equal(strip.querySelectorAll('.rl-eco-chip').length, NATIONS);
  assert.ok(strip.querySelector('.rl-comeback'));
  assert.ok(root.querySelector('.rl-firstwake'));
  assert.equal(root.querySelector('.rl-roombar'), null);
});
