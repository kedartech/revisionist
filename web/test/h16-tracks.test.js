// Paths and sent orders as tracks, one test or more per rule: 1. Court draws each path as a
// track: a stop for each decision step, a small mark for each clerical step, the gap after each
// in proportion to its days, and the days written under it; 2. each of the seat's orders in
// flight is a marker on its path at the step that holds it; 3. a stop opens that person's figure
// card with the two moves it has today; 4. the Sent part of the Orders sheet draws each order as
// four steps: filed; who holds it, or that it is held and who can allow it; when it lands; the
// result, and a tap opens the order; 5. a step with no time stated draws a fixed short gap and
// says so. Accept: a path of one step and a path of six both fit 390 px with every stop a 44 px
// target. Mutants: gaps drawn equal whatever the days; a clerical step opening a card; a held
// order drawn as on its way.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, installDom, words } from './dom-fake.js';

const proto = Object.getPrototypeOf(installDom().createElement('div'));
// the fake has no CSSOM: each element gets a style that keeps what is set on it
Object.defineProperty(proto, 'style', {
  configurable: true,
  get() {
    this._style ??= { props: {}, setProperty(k, v) { this.props[k] = String(v); }, getPropertyValue(k) { return this.props[k] ?? ''; } };
    return this._style;
  },
});
Object.defineProperty(proto, 'hidden', {
  configurable: true,
  get() { return this.hasAttribute('hidden'); },
  set(on) { this.toggleAttribute('hidden', Boolean(on)); },
});
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { courtBoard } = await import('../js/views/realism-court.js');
const tracks = await import('../js/views/realism-tracks.js');
const { realismRoom } = await import('../js/views/realism-room.js');
const { forgetShapes } = await import('../js/views/realism-theatre.js');
const { setRoomLayout } = await import('../js/views/realism-sheets.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const css = readFileSync(new URL('../css/c-court.css', import.meta.url), 'utf8');
const settle = () => new Promise((r) => setTimeout(r, 0));

const RAYBURN = 'ABAZ0TGFM42G2BDHEC49BPG0B7';
const view = () => structuredClone(fixture);
const board = (rv = view(), more = {}) => courtBoard(rv, more.ui ?? {}, { pick: () => {}, ...more });
const pathRows = (el) => el.querySelectorAll('.rl-court-path');
const segs = (row) => row.querySelectorAll('.rl-trk-seg');
const grow = (seg) => seg.style.getPropertyValue('--rl-trk-grow');
const segOf = (el, name) => el.querySelectorAll('.rl-trk-seg').find((s) => s.getAttribute('data-name') === name);

// rule 1: a stop per decision step, a mark per clerical step, gaps in proportion to the days

test('a path is a track: a stop per decision step, a small mark per clerical step, in order', () => {
  const [bill] = pathRows(board());
  const track = bill.querySelector('ol.rl-trk');
  assert.ok(track, 'the path is drawn as a track');
  assert.equal(track.getAttribute('aria-label'), 'A bill through Congress: its steps');
  assert.deepEqual(segs(bill).map((s) => [s.getAttribute('data-name'), s.getAttribute('data-kind')]), [
    ['Sam Rayburn', 'stop'], ['House committee clerk', 'mark'], ['Alben W. Barkley', 'stop'], ['You', 'stop'],
  ]);
  assert.equal(segOf(bill, 'Sam Rayburn').querySelector('button.rl-court-sq') !== null, true, 'a stop is a button');
  assert.equal(segOf(bill, 'You').querySelector('div.rl-court-sq.you') !== null, true, 'the seat\'s own stop is not a button');
  const clerk = segOf(bill, 'House committee clerk');
  assert.equal(clerk.querySelector('.rl-court-sq'), null, 'a clerical step is not a stop');
  assert.equal(clerk.querySelector('.rl-court-clerk').tagName, 'SPAN');
});

test('the gap after each step is in proportion to its days, and its days are written under it', () => {
  const [bill, naval] = pathRows(board());
  assert.deepEqual(segs(bill).map(grow), ['8', '1', '20', '10']);
  assert.deepEqual(segs(bill).map((s) => s.getAttribute('data-days')), ['8', '1', '20', '10']);
  assert.deepEqual(segs(naval).map(grow), ['2', '2']);
  assert.deepEqual(segs(bill).map((s) => words(s.querySelector('.rl-trk-days'))), ['8 days', '1 day', '20 days', '10 days']);
  const days = segs(bill).map((s) => s.querySelector('.rl-trk-days'));
  assert.ok(days.every((d, i) => d.parentNode === segs(bill)[i]), 'the days sit in the step\'s own place on the track');
  const rv = view();
  rv.court.paths[0].steps[2].days = 4;
  assert.deepEqual(segs(pathRows(board(rv))[0]).map(grow), ['8', '1', '4', '10'], 'the gap follows the days');
});

// rule 5: no time stated, a fixed short gap that says so

test('a step with no time stated draws a fixed short gap and says so', () => {
  const rv = view();
  rv.court.paths[1].steps[1].days = null;
  const naval = pathRows(board(rv))[1];
  const king = segOf(naval, 'Ernest J. King');
  assert.ok(king.classList.contains('unstated'));
  assert.equal(grow(king), '', 'it takes no share of the days');
  assert.equal(king.getAttribute('data-days'), null);
  assert.equal(words(king.querySelector('.rl-trk-days')), 'no time stated');
  assert.match(css, /\.rl-trk-seg\.unstated \{[^}]*flex: 0 0 [^;}]+/, 'a fixed width in the stylesheet');
  assert.ok(!segOf(naval, 'Harold R. Stark').classList.contains('unstated'));
});

// rule 2: each order in flight is a marker on its path at the step that holds it

test('each order in flight is a marker on its path at the step that holds it', () => {
  const el = board();
  const [bill, naval] = pathRows(el);
  const markers = el.querySelectorAll('.rl-trk-marker');
  assert.equal(markers.length, 2, 'two orders in flight');
  const rayburn = segOf(bill, 'Sam Rayburn');
  assert.equal(rayburn.querySelectorAll('.rl-trk-marker').length, 1);
  assert.equal(rayburn.querySelector('.rl-trk-marker').getAttribute('data-order'), 'o-neutrality');
  assert.equal(segOf(naval, 'Harold R. Stark').querySelector('.rl-trk-marker').getAttribute('data-order'), 'o-convoy');
  assert.equal(segOf(bill, 'Alben W. Barkley').querySelector('.rl-trk-marker'), null);
  assert.deepEqual(bill.querySelectorAll('.rl-court-tok').map(words), ['Send a bill to Congress, with Sam Rayburn: day 9 of about 8']);
  assert.deepEqual(naval.querySelectorAll('.rl-court-tok').map(words), ['Give a naval order, with Harold R. Stark: day 2 of about 2']);
});

test('a marker stands as far along its step as the days it has been held, and no further than its end', () => {
  const el = board();
  const at = (name) => segOf(el, name).querySelector('.rl-trk-marker').style.getPropertyValue('--rl-trk-at');
  assert.equal(at('Harold R. Stark'), '50%', 'one day held of about two');
  assert.equal(at('Sam Rayburn'), '100%', 'eight of about eight');
  const rv = view();
  rv.court.paths[0].steps[0].orders[0].held_days = 30;
  assert.equal(segOf(board(rv), 'Sam Rayburn').querySelector('.rl-trk-marker').style.getPropertyValue('--rl-trk-at'), '100%');
  rv.court.paths[0].steps[0].days = null;
  const unstated = segOf(board(rv), 'Sam Rayburn');
  assert.equal(unstated.querySelector('.rl-trk-marker').style.getPropertyValue('--rl-trk-at'), '0%');
  assert.equal(words(board(rv).querySelector('.rl-court-tok')), 'Send a bill to Congress, with Sam Rayburn: day 31; no time stated');
});

test('an order held at a clerical step is a marker on the clerk\'s mark', () => {
  const rv = view();
  rv.court.paths[0].steps[1].orders = [{ id: 'o-x', label: 'Send a bill to Congress', since: '1941-10-19', held_days: 0 }];
  const clerk = segOf(board(rv), 'House committee clerk');
  assert.equal(clerk.querySelector('.rl-trk-marker').getAttribute('data-order'), 'o-x');
});

// rule 3: a stop opens the person's figure card with the two moves; a clerical step opens nothing

test('a stop picks its person, whose card shows the two moves', () => {
  const picked = [];
  const el = board(view(), { pick: (p) => picked.push(p) });
  segOf(el, 'Sam Rayburn').querySelector('button.rl-court-sq').click();
  assert.deepEqual(picked, [{ piece: { kind: 'person', person: RAYBURN, name: 'Sam Rayburn' } }]);
  const open = board(view(), { ui: { piece: { kind: 'person', person: RAYBURN, name: 'Sam Rayburn' } } });
  assert.deepEqual(open.querySelectorAll('.rl-court-moves button').map(words), ['Ask them a question', 'Write them an order']);
});

test('a clerical step is never a person: it has no button and a click on it picks nobody', () => {
  const picked = [];
  const el = board(view(), { pick: (p) => picked.push(p) });
  const marks = el.querySelectorAll('.rl-trk-seg').filter((s) => s.getAttribute('data-kind') === 'mark');
  assert.equal(marks.length, 4);
  for (const m of marks) {
    assert.equal(m.querySelectorAll('button').length, 0);
    m.click();
    m.querySelector('.rl-court-clerk').click();
  }
  assert.deepEqual(picked, []);
});

// accept: a path of one step and of six both fit 390 px, every stop a 44 px target

const step = (i, kind = 'decision', days = 3) => ({ person: `P${i}`, name: `Person ${i}`, office: null, kind, days, you: false, orders: [] });

test('a path of one step and a path of six both fit a 390 px screen, every stop 44 px', () => {
  assert.equal(tracks.STOP_PX, 44);
  const inner = 390 - 2 * tracks.SHEET_PAD_PX;
  assert.ok(tracks.trackMinWidth([step(1)]) <= inner);
  const six = Array.from({ length: 6 }, (_, i) => step(i, 'decision', i % 2 ? null : 20));
  assert.ok(tracks.trackMinWidth(six) <= inner, `${tracks.trackMinWidth(six)} px within ${inner}`);
  const mixed = Array.from({ length: 6 }, (_, i) => step(i, i % 2 ? 'clerical' : 'decision', null));
  assert.ok(tracks.trackMinWidth(mixed) <= inner);
  assert.ok(tracks.trackMinWidth(six) >= 6 * 44, 'the width counts every stop at full size');
  const rule = (sel) => css.match(new RegExp(`${sel.replace(/[.[\]()]/g, '\\$&')} \\{([^}]*)\\}`))?.[1] ?? '';
  assert.match(rule('.rl-trk .rl-court-sq'), /min-width: 44px/);
  assert.match(rule('.rl-trk .rl-court-sq'), /min-height: 44px/);
  assert.match(rule('.rl-trk .rl-court-sq'), /max-width: none/, 'the phone board\'s wide square does not apply on a track');
  assert.match(rule('.rl-trk-seg'), /min-width: 0/);
  assert.match(rule('.rl-trk'), /flex-wrap: nowrap/);
  const rv = view();
  rv.court.paths = [{ id: 'p6', name: 'Six', forms: [], steps: Array.from({ length: 6 }, (_, i) => step(i)) }];
  assert.equal(board(rv).querySelectorAll('button.rl-court-sq').length, 6);
});

// rule 4: the Sent part draws each order as four steps; a tap opens the order

const sent = (rv = view(), more = {}) => tracks.sentTracks(rv.record, rv.orders, rv.locks?.held ?? [], { stepForm: () => null, ...more });
const orderOf = (el, id) => el.querySelectorAll('.rl-sent-order').find((o) => o.getAttribute('data-order') === id);
const steps = (o) => o.querySelectorAll('.rl-sent-step').map((s) => [s.getAttribute('data-state'), words(s)]);

test('the Sent part: each order is four steps, filed, who holds it, when it lands, the result', () => {
  const el = sent();
  assert.ok(el.classList.contains('rl-oc'), 'the part is still the seat\'s orders');
  assert.deepEqual(steps(orderOf(el, 'a90f3e6b1c22')), [
    ['done', 'Filed 17 October 1941'], ['now', 'With Harold R. Stark'], ['next', 'Answer due 21 October 1941'], ['next', 'Result'],
  ]);
  assert.deepEqual(steps(orderOf(el, '0b7d24c9e815')), [
    ['done', 'Filed 10 October 1941'], ['now', 'With Sam Rayburn'], ['next', 'On its way'], ['next', 'Result'],
  ]);
  assert.deepEqual(steps(orderOf(el, 'e43a91d07f6c')), [
    ['done', 'Filed 8 October 1941'], ['done', 'To Burton K. Wheeler'], ['done', 'Settled 14 October 1941'], ['bad', 'Declined'],
  ]);
  assert.deepEqual(steps(orderOf(el, '7c2f8e0a3d91')).at(-1), ['done', 'Carried out']);
  assert.deepEqual(steps(orderOf(el, '5d1c0a77e2b4'))[1], ['due', 'Needs you'], 'the order waiting on the seat');
  assert.equal(el.querySelectorAll('.rl-sent-order').length, 13 + 2, 'every order of the record, and each held order');
});

test('a held order is drawn as held, with who can allow it, and not as on its way', () => {
  const el = sent();
  const held = orderOf(el, '01M7YNVKSY384MG2G9E0YC4RXY');
  assert.deepEqual(steps(held), [
    ['done', 'Filed 2 April 1900'], ['held', 'Held: Ilse Varg can allow it, asked'], ['next', 'Sent when allowed'], ['next', 'Result'],
  ]);
  assert.deepEqual(steps(orderOf(el, '01M7YNVKSZFHJ8A6SZVCZRT5E5'))[1], ['held', 'Held: Ilse Varg can allow it, not asked']);
  assert.ok(steps(held).every(([state, w]) => state !== 'now' && !/On its way|With /.test(w)));
  assert.match(words(held.querySelector('.rl-sent-ask')), /March \(Force Norra levy, To Isle\)/);
});

test('the orders run: what waits on the seat, then the moving, then the held, then the finished, folded', () => {
  const el = sent();
  const open = el.querySelector('.rl-sent-list').children.map((o) => o.getAttribute('data-order'));
  assert.deepEqual(open, ['5d1c0a77e2b4', 'a90f3e6b1c22', '0b7d24c9e815', '01M7YNVKSY384MG2G9E0YC4RXY', '01M7YNVKSZFHJ8A6SZVCZRT5E5']);
  const done = el.querySelector('details.rl-sent-done');
  assert.equal(words(done.querySelector('summary')), 'Finished (10)');
  const none = tracks.sentTracks({ orders: [] }, null, [], {});
  assert.equal(words(none.querySelector('.rl-oc-empty')), 'No orders yet. Pick an idea or write one.');
});

test('a tap on an order\'s track opens it: its lines, its paper, its steps', () => {
  const toggled = [];
  const el = sent(view(), { onToggle: (id) => toggled.push(id) });
  const rayburn = orderOf(el, '0b7d24c9e815');
  const head = rayburn.querySelector('button.rl-sent-head');
  assert.ok(head.querySelector('.rl-sent-track'), 'the track is inside the tap target');
  assert.equal(head.getAttribute('aria-expanded'), 'false');
  assert.equal(rayburn.querySelector('.rl-sent-body'), null, 'closed until tapped');
  head.click();
  assert.deepEqual(toggled, ['0b7d24c9e815']);
  const opened = [];
  const open = orderOf(sent(view(), { opened: '0b7d24c9e815', onOpen: (p) => opened.push(p) }), '0b7d24c9e815');
  assert.equal(open.querySelector('button.rl-sent-head').getAttribute('aria-expanded'), 'true');
  const body = open.querySelector('.rl-sent-body');
  assert.match(words(body), /Under way/);
  assert.ok(body.querySelector('ol.stepper'), 'the tracker\'s steps');
  buttons(body, 'Passed on, 12 October 1941')[0].click();
  assert.deepEqual(opened, [{ id: 'd-reply-1012' }]);
  const held = orderOf(sent(view(), { opened: '01M7YNVKSY384MG2G9E0YC4RXY' }), '01M7YNVKSY384MG2G9E0YC4RXY');
  assert.match(words(held.querySelector('.rl-sent-body')), /Held until Ilse Varg allows it\./);
});

test('an order waiting on the seat is open with its decision form', () => {
  const el = sent(view(), { stepForm: () => document.createElement('form') });
  const convoy = orderOf(el, '5d1c0a77e2b4');
  assert.equal(convoy.querySelector('button.rl-sent-head').getAttribute('aria-expanded'), 'true');
  assert.ok(convoy.querySelector('.rl-sent-body form'), 'the decision form under the track');
});

// in the room: the map-first Orders sheet at Sent draws the tracks; Classic keeps its cards

async function room(layout) {
  const doc = installDom();
  setRoomLayout(layout);
  forgetShapes();
  api.realism = async (action) => (action === 'map' ? { reply: '', refused: false, file: fixture.territory_map.file, map: SHAPES } : {});
  api.catchup = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  const rv = view();
  rv.map = structuredClone(fixture.territory_map);
  rv.documents = structuredClone(fixture.listing);
  rv.wake_tick = 1;
  rv.style = 'free';
  rv.battles = [];
  const game = { id: `h16-${Math.random()}`, name: 'Autumn 1941', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'Franklin D. Roosevelt' } } };
  const ctx = { me: { account: { handle: 'josh' }, game }, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {}, signOut: () => {} };
  const root = realismRoom(ctx);
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  await settle();
  await settle();
  return root;
}

test('in the map-first room, Orders at Sent draws the tracks and a tap opens an order in place', async () => {
  const root = await room('map');
  root.querySelectorAll('.rl-sheettabs button').find((b) => b.getAttribute('data-group') === 'orders').click();
  root.querySelector('.rl-over').querySelectorAll('.rl-parts button').find((b) => b.getAttribute('data-sheet') === 'orders').click();
  const over = () => root.querySelector('.rl-over');
  assert.ok(over().querySelector('.rl-sent'), 'the tracks');
  assert.equal(over().querySelectorAll('.rl-oc-card').length, 15);
  const head = orderOf(over(), 'a90f3e6b1c22').querySelector('button.rl-sent-head');
  head.click();
  const again = orderOf(over(), 'a90f3e6b1c22');
  assert.equal(again.querySelector('button.rl-sent-head').getAttribute('aria-expanded'), 'true');
  assert.match(words(again.querySelector('.rl-sent-body')), /To Harold R\. Stark/);
  assert.equal(document.activeElement, again.querySelector('button.rl-sent-head'), 'focus stays on the order tapped');
  again.querySelector('button.rl-sent-head').click();
  assert.equal(orderOf(over(), 'a90f3e6b1c22').querySelector('.rl-sent-body'), null, 'a second tap closes it');
});

test('the Classic layout keeps its own orders cards', async () => {
  const root = await room('classic');
  buttons(root.querySelector('.rl-viewswitch'), 'Desk')[0].click();
  assert.equal(root.querySelector('.rl-sent'), null);
  assert.ok(root.querySelector('.rl-oc .rl-oc-card'));
});

test('c-court.css uses tokens only, and the tracks are text nodes only', () => {
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/, 'colours come from tokens');
  assert.match(css, /\.rl-sent-step\[data-state="held"\][^{]*\{[^}]*var\(--warn\)/, 'held is amber');
  assert.match(css, /\.rl-sent-step\[data-state="bad"\][^{]*\{[^}]*var\(--danger\)/, 'a failed result is red');
  const src = readFileSync(new URL('../js/views/realism-tracks.js', import.meta.url), 'utf8');
  assert.doesNotMatch(src, /innerHTML|insertAdjacentHTML|outerHTML|setAttribute\('style'|style: /);
});
