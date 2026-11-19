// One "what needs you" list (WNY): in the map-first room one list holds every matter that waits
// on the seat, sorted by due day then by arrival, with Done at its foot; it replaces the agenda
// panel and the count tiles there, one badge shows its count, each line has one action, a
// routine receipt is never a line, and later items add kinds through its registry.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, installDom, words } from './dom-fake.js';

// the fake DOM has no `hidden` property; the forms' Draft toggle reads and writes it
Object.defineProperty(Object.getPrototypeOf(installDom().createElement('div')), 'hidden', {
  configurable: true,
  get() { return this.hasAttribute('hidden'); },
  set(on) { this.toggleAttribute('hidden', Boolean(on)); },
});
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { realismRoom } = await import('../js/views/realism-room.js');
const { setRoomLayout } = await import('../js/views/realism-sheets.js');
const { forgetShapes } = await import('../js/views/realism-theatre.js');
const needs = await import('../js/views/realism-needs.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');

const NORRA = { key: 'N', name: 'Norra', relation: 'own' };
const SUDLAND = { key: 'S', name: 'Sudland', relation: 'enemy' };
const TODAY = '1941-10-20';

const REQUEST = {
  id: 'd-ask-1', kind: 'Request', issuer: 'Winston Churchill', text: 'Send forty destroyers to the Western Approaches',
  issued: '19 October 1941', deadline: '22 October 1941', cause: null, options: [], plan: [], actions: [],
};
const DECISION = {
  id: 'd-held-1', kind: 'Decision', issuer: 'Joseph Stalin', text: 'The Murmansk convoy order',
  issued: '18 October 1941', deadline: '22 October 1941', cause: null, options: [], plan: [], actions: ['pass', 'refuse'],
};
const FALLING_PAPER = {
  id: 'd-fall-1', kind: 'report', title: 'The Norra Plain will fall at the next close', author: 'Norra',
  issued: TODAY, arrives: TODAY, channel: 'cable', classification: 'confidential',
  unread: true, flagged: false, group: null, ack: false, answer: false,
};

/** The toy board: Norra holds the plain (marked to fall today) and the hills; Sudland the coast. */
function board() {
  const map = structuredClone(fixture.territory_map);
  const by = { norra_plain: NORRA, norra_hills: NORRA, sudland_coast: SUDLAND };
  map.areas = map.areas.map((a) => ({
    ...a, holder: by[a.key] ?? null, held_since: null, taken_from: null, falling: a.key === 'norra_plain' ? TODAY : null,
  }));
  return map;
}

/**
 * The seat's view with five kinds of matter: the fixture's agenda item (due 26 October), a
 * request and a held decision (both due 22 October), its own order waiting on its decision (no
 * set day) and a falling territory's paper (due at this wake's close). `committed` is how many
 * of the two players have pressed Done; the other seat's presence changes nothing else.
 */
function seat({ committed = 1, you = false } = {}) {
  const rv = structuredClone(fixture);
  rv.agenda = { ...rv.agenda, items: [...rv.agenda.items, structuredClone(REQUEST), structuredClone(DECISION)] };
  rv.map = board();
  rv.clock = { ...rv.clock, world_date: TODAY };
  rv.wake = { ...rv.wake, committed, humans: 2, you_committed: you };
  rv.documents = { ...rv.listing, documents: [structuredClone(FALLING_PAPER), ...rv.listing.documents] };
  rv.wake_tick = 1;
  return rv;
}

/** No matter waits: no agenda item, no order waiting on a decision, nothing falling. */
function quiet() {
  const rv = seat();
  rv.agenda = { ...rv.agenda, items: [] };
  rv.orders = { orders: rv.orders.orders.map((o) => ({ ...o, decision_needed: false })) };
  rv.map = { ...rv.map, areas: rv.map.areas.map((a) => ({ ...a, falling: null })) };
  return rv;
}

const gameOf = (id, rv) => ({ id, name: 'Autumn 1941', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'Franklin D. Roosevelt' } } });
const settle = () => new Promise((r) => setTimeout(r, 0));
const key = (el, k) => el.dispatchEvent({
  type: 'keydown', key: k, target: null, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() {},
});

/** The whole room for a fresh game in `layout`, over `rv`, with the toy map's shapes served and every call recorded. */
async function room(rv = seat(), layout = 'map') {
  const doc = installDom();
  setRoomLayout(layout);
  forgetShapes();
  const calls = [];
  api.realism = async (action, body) => {
    calls.push([action, body]);
    if (action === 'map') return { reply: '', refused: false, file: rv.map.file, map: SHAPES };
    return { reply: '', refused: false };
  };
  api.catchup = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  const id = `g-${Math.random()}`;
  const me = { account: { handle: 'josh' }, game: gameOf(id, rv) };
  const ctx = { me, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {} };
  const root = realismRoom(ctx);
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  await settle();
  await settle();
  return { root: () => doc.body.firstElementChild ?? root, calls, first: root };
}

const list = (root) => root.querySelector('.rl-needs');
const lines = (root) => list(root).querySelectorAll('.rl-need');
const lineOf = (root, kind) => lines(root).find((l) => l.getAttribute('data-kind') === kind);
const kindsOf = (ls) => ls.map((l) => l.kind);

// --- rule 1: one list holds every matter that waits, sorted by due day, then by arrival; Done at its foot

test('the list holds every kind of matter that waits on the seat, sorted by due day, then by arrival', () => {
  const got = needs.needLines(seat());
  assert.deepEqual(kindsOf(got), ['paper', 'decision', 'request', 'agenda', 'order']);
  assert.deepEqual(got.map((l) => l.due), [TODAY, '22 October 1941', '22 October 1941', '26 October 1941', null]);
  assert.equal(got.find((l) => l.kind === 'request').what, REQUEST.text);
  assert.equal(got.find((l) => l.kind === 'agenda').what, fixture.agenda.items[0].text);
});

test('two matters due the same day are listed by arrival, whichever the agenda gave first', () => {
  const rv = seat();
  rv.agenda.items.reverse();
  assert.deepEqual(kindsOf(needs.needLines(rv)).slice(1, 3), ['decision', 'request'], 'the decision arrived on the 18th, the request on the 19th');
  rv.agenda.items.find((i) => i.id === REQUEST.id).issued = '17 October 1941';
  assert.deepEqual(kindsOf(needs.needLines(rv)).slice(1, 3), ['request', 'decision']);
});

test('in the map-first room the list is headed "What needs you", and Done for today is at its foot', async () => {
  const { root } = await room();
  const el = list(root());
  assert.ok(el, 'the list');
  assert.equal(words(el.querySelector('h2')).replace(/\s*\d+$/, ''), 'What needs you');
  assert.deepEqual(lines(root()).map((l) => l.getAttribute('data-kind')), ['paper', 'decision', 'request', 'agenda', 'order']);
  const foot = el.querySelector('.rl-needs-done');
  assert.ok(foot, 'the Done line');
  assert.deepEqual(foot.querySelectorAll('button').map(words), ['Done for today']);
  assert.equal(el.children.at(-1), foot, 'Done is the last thing in the list');
});

test('with nothing waiting the list says so, and Done is still there', async () => {
  const { root } = await room(quiet());
  const el = list(root());
  assert.equal(lines(root()).length, 0);
  assert.equal(words(el.querySelector('.rl-needs-none')), 'Nothing waits on you. Press Done when you are.');
  assert.deepEqual(el.querySelector('.rl-needs-done').querySelectorAll('button').map(words), ['Done for today']);
  assert.equal(el.querySelector('.rl-needs-count'), null, 'no badge for an empty list');
});

// --- rule 2: in that room it replaces the in-tray, the agenda panel and the count tiles; one badge

test('the map-first room has no count tiles, no agenda panel in any sheet, and one count of what waits', async () => {
  const { root } = await room();
  assert.equal(root().querySelector('.rl-tiles'), null, 'no count tiles');
  for (const tab of root().querySelectorAll('.rl-sheettabs button')) {
    tab.click();
    const sheet = root().querySelector('.rl-over');
    assert.equal(sheet.querySelector('.rl-ans'), null, `no agenda panel in ${words(tab)}`);
  }
  root().querySelector('.rl-over .rl-over-close').click();
  const counts = root().querySelectorAll('.rl-needs-count');
  assert.ok(counts.length >= 1, 'the badge');
  assert.ok(counts.every((c) => words(c) === '5'), 'every badge says the list\'s count');
  const orders = root().querySelectorAll('.rl-sheettabs button').find((b) => b.getAttribute('data-sheet') === 'orders');
  assert.equal(orders.querySelector('.rl-tab-count'), null, 'the order waiting on a decision is counted in the list, not on its tab');
});

test('today\'s room keeps its count tiles and its agenda panel, and has no list', async () => {
  const { root } = await room(seat(), 'room');
  root().querySelectorAll('.rl-viewswitch button').find((b) => words(b) === 'Desk').click();
  assert.ok(root().querySelector('.rl-tiles'), 'the count tiles');
  assert.ok(root().querySelector('.rl-ans'), 'the agenda panel');
  assert.equal(list(root()), null);
  setRoomLayout('room');
});

test('on a phone the list opens from the Needs button with its badge, and closes with Escape back to it', async () => {
  const { root } = await room();
  const btn = root().querySelector('.rl-needsbar .rl-needs-btn');
  assert.ok(btn, 'the Needs button in the bottom bar');
  assert.match(words(btn), /^Needs 5$/);
  assert.ok(root().querySelector('.rl-needsbar').querySelectorAll('button').map(words).includes('Done for today'));
  assert.equal(btn.getAttribute('aria-expanded'), 'false');
  btn.click();
  assert.ok(list(root()).classList.contains('open'), 'opened as the half sheet');
  assert.equal(root().querySelector('.rl-needsbar .rl-needs-btn').getAttribute('aria-expanded'), 'true');
  root().querySelectorAll('.rl-sheettabs button')[0].click();
  assert.ok(!list(root()).classList.contains('open'), 'one sheet at a time: a tab closes it');
  root().querySelector('.rl-over .rl-over-close').click();
  root().querySelector('.rl-needsbar .rl-needs-btn').click();
  key(list(root()), 'Escape');
  assert.ok(!list(root()).classList.contains('open'));
  assert.equal(document.activeElement, root().querySelector('.rl-needsbar .rl-needs-btn'));
});

// --- rule 3: each line says what, from whom and by when, and has one action that opens the right sheet or centres the map

test('each line says what it is, from whom and by when, and has one action', async () => {
  const { root } = await room();
  const want = {
    paper: [FALLING_PAPER.title, 'Norra', 'Due at this wake\'s close', 'Show on map'],
    decision: [DECISION.text, 'Joseph Stalin', 'Due 22 October 1941', 'Decide'],
    request: [REQUEST.text, 'Winston Churchill', 'Due 22 October 1941', 'Answer'],
    agenda: [fixture.agenda.items[0].text, fixture.agenda.items[0].issuer, 'Due 26 October 1941', 'Answer'],
    order: ['Give a naval order', 'Your own order', 'No set day', 'Decide'],
  };
  for (const [kind, [what, from, due, action]] of Object.entries(want)) {
    const line = lineOf(root(), kind);
    assert.ok(words(line.querySelector('.rl-need-kind')), `${kind} names its kind`);
    assert.match(words(line.querySelector('.rl-need-what')), new RegExp(what.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')), `${kind}: what`);
    assert.match(words(line.querySelector('.rl-need-from')), new RegExp(from), `${kind}: from whom`);
    assert.equal(words(line.querySelector('.rl-need-due')), due, `${kind}: by when`);
    assert.deepEqual(line.querySelectorAll('button').map(words), [action], `${kind}: one action`);
  }
});

test('a request\'s Answer opens its own sheet with Accept and Decline, and Escape returns to the line', async () => {
  const { root, calls } = await room();
  lineOf(root(), 'request').querySelector('button').click();
  const [sheet] = root().querySelectorAll('.rl-over');
  assert.equal(sheet.getAttribute('data-sheet'), 'matter');
  assert.equal(words(sheet.querySelector('.rl-over-title')), 'Request from Winston Churchill');
  assert.match(words(sheet), /Send forty destroyers/);
  assert.deepEqual(buttons(sheet, 'Accept').length, 1);
  buttons(sheet, 'Accept')[0].click();
  await settle();
  assert.deepEqual(calls.at(-1), ['answer', { item: REQUEST.id, accept: true }]);
  const again = root().querySelector('.rl-over');
  assert.equal(again?.getAttribute('data-sheet'), 'matter', 'the sheet stays open over the re-read');
  await settle();
  assert.equal(document.activeElement, again.querySelector('.rl-over-title'), 'the keyboard is put back into the sheet');
  key(again, 'Escape');
  assert.equal(root().querySelectorAll('.rl-over').length, 0);
  assert.equal(document.activeElement, lineOf(root(), 'request').querySelector('button'));
});

test('a held decision\'s Decide opens its sheet with the step\'s own actions', async () => {
  const { root } = await room();
  lineOf(root(), 'decision').querySelector('button').click();
  const sheet = root().querySelector('.rl-over');
  assert.equal(sheet.getAttribute('data-sheet'), 'matter');
  assert.deepEqual(sheet.querySelectorAll('.rl-ans-pair button').map(words), ['Pass it on', 'Refuse']);
});

test('the seat\'s own order waiting on it opens the Orders sheet, which holds its step form', async () => {
  const { root } = await room();
  lineOf(root(), 'order').querySelector('button').click();
  const sheet = root().querySelector('.rl-over');
  assert.equal(sheet.getAttribute('data-sheet'), 'orders');
  assert.ok(sheet.querySelector('.rl-step-form'), 'the step form');
});

test('a falling territory\'s paper centres the map on it and opens its area sheet', async () => {
  const { root } = await room();
  lineOf(root(), 'paper').querySelector('button').click();
  const sheet = root().querySelector('.rl-mapfirst .rl-area-sheet');
  assert.equal(sheet?.getAttribute('data-area'), 'norra_plain');
  const svg = root().querySelector('.rl-mapfirst svg.rl-map-svg');
  const [x, y, w, hh] = svg.getAttribute('viewBox').split(/\s+/).map(Number);
  const [lx, ly] = SHAPES.areas.norra_plain.label;
  const centre = [x + w / 2, y + hh / 2];
  const near = (a, b) => Math.abs(a - b) <= Math.max(w, hh) / 4;
  assert.ok(w < 300, 'zoomed in');
  assert.ok(near(centre[0], lx - 0) && near(centre[1], 200 - ly), `centred near the plain: ${centre} for ${[lx, 200 - ly]}`);
  assert.equal(document.activeElement, sheet.querySelector('button'));
});

test('the Done line commits the wake', async () => {
  const { root, calls } = await room();
  list(root()).querySelector('.rl-needs-done button').click();
  await settle();
  assert.deepEqual(calls.at(-1), ['commit', {}]);
});

// --- rule 4: a routine receipt is never a line

test('a routine receipt is never a line: neither an acknowledgement paper nor an order\'s receipt', () => {
  const rv = seat();
  const got = needs.needLines(rv);
  assert.ok(kindsOf(got).includes('paper'), 'the falling territory\'s paper is a line while it asks');
  const said = JSON.stringify(got);
  for (const d of rv.documents.documents.filter((x) => x.ack)) assert.ok(!said.includes(d.title), `${d.title} is not a line`);
  for (const o of rv.record.orders.filter((x) => x.receipt)) assert.ok(!said.includes(o.receipt.word), 'no receipt word');
  rv.documents.documents[0] = { ...rv.documents.documents[0], ack: true };
  assert.ok(!kindsOf(needs.needLines(rv)).includes('paper'), 'a paper that only acknowledges is not a line, whatever it says');
});

test('a territory marked to fall is a line only by the paper the seat holds, and only when the seat holds the territory', () => {
  assert.ok(kindsOf(needs.needLines(seat())).includes('paper'));
  const rv = seat();
  rv.documents.documents.shift();
  assert.ok(!kindsOf(needs.needLines(rv)).includes('paper'), 'no paper, no line');
  const theirs = seat();
  theirs.map.areas = theirs.map.areas.map((a) => (a.key === 'norra_plain' ? { ...a, holder: SUDLAND } : a));
  assert.ok(!kindsOf(needs.needLines(theirs)).includes('paper'), 'another holder\'s territory is not the seat\'s matter');
});

// --- rule 5: one exported function over the room's data, and a registry of kinds

test('later items add a kind through the registry: its lines are sorted in and drawn with their action', async () => {
  const before = needs.needLines(seat()).length;
  const off = needs.addNeedKind('battle', (rv) => [{
    key: 'b-1', label: 'Battle', what: 'The battle at the coast: today\'s decision', from: 'The Sudland Coast',
    due: rv.clock.world_date, arrived: '1941-10-19', action: { word: 'Decide', to: 'sheet', sheet: 'orders' },
  }]);
  try {
    const got = needs.needLines(seat());
    assert.equal(got.length, before + 1);
    assert.deepEqual(kindsOf(got).slice(0, 2), ['battle', 'paper'], 'due today and arrived first');
    const { root } = await room();
    const line = lineOf(root(), 'battle');
    assert.equal(words(line.querySelector('.rl-need-kind')), 'Battle');
    line.querySelector('button').click();
    assert.equal(root().querySelector('.rl-over').getAttribute('data-sheet'), 'orders');
  } finally { off(); }
  assert.equal(needs.needLines(seat()).length, before, 'removed again');
});

// --- invariant 2: a line reads the same whether the other seat is present or away

test('the same matters give the same lines whether the other seat is present and done, or away', async () => {
  const present = needs.needLines(seat({ committed: 2 }));
  const away = needs.needLines(seat({ committed: 1 }));
  assert.deepEqual(present, away);
  const a = await room(seat({ committed: 2, you: true }));
  const shown = words(list(a.root()));
  const b = await room(seat({ committed: 1, you: true }));
  assert.equal(words(list(b.root())), shown, 'the drawn list, Done line and all');
});

// --- invariant 1: every line that has a due day shows it

test('every line that has a due day shows it', () => {
  const got = needs.needLines(seat());
  assert.equal(got.filter((l) => l.due).length, 4);
  for (const l of got) {
    if (l.due) assert.match(needs.dueWords(l, TODAY), /^Due /, l.kind);
  }
});

// --- the stylesheet

test('c-needs.css: a rail beside the map from 1024 px, a half sheet from the bottom below it; tokens only', () => {
  const css = read('css/c-needs.css').replace(/\/\*[\s\S]*?\*\//g, '');
  const wide = css.indexOf('@media (min-width: 1024px)');
  assert.ok(wide >= 0, 'a 1024 px rule');
  assert.match(css.slice(0, wide), /\.rl-needs\.open \{[^}]*position: fixed[^}]*\}/, 'the half sheet');
  assert.match(css.slice(0, wide), /\.rl-needs\.open \{[^}]*max-height: 50/, 'half the screen');
  assert.match(css.slice(wide), /\.rl-needsbar \{[^}]*display: none/, 'no bottom bar beside the rail');
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(/, 'tokens only');
  assert.match(read('index.html'), /href="\/css\/c-needs\.css"/, 'the page loads it');
});
