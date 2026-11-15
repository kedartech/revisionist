// The cost strip on an order: while a form is open, a strip under it names who carries the
// order first, the days its path states and how many of the seat's orders that person already
// holds; past the load limit it says the order is likely to go slow (as the engine counts load:
// other orders at an AI holder's decision step); a form whose path is not in the court data
// shows no strip.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { realismRoom } = await import('../js/views/realism-room.js');
const { costStrip, goesSlow, heldBy, pathDays } = await import('../js/views/realism-estimate.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');

/** The court, and the seat's levers each pointing at the court path that lists its label. */
function linked() {
  const court = structuredClone(fixture.court);
  const levers = structuredClone(fixture.desk.levers).map((l) => {
    const path = court.paths.find((p) => p.forms.includes(l.label));
    return path ? { ...l, pipeline: path.id } : l;
  });
  return { court, levers };
}
const lever = (levers, name) => levers.find((l) => l.name === name);
const naval = (court) => court.paths.find((p) => p.name === 'A naval order');
const line = (strip, cls) => {
  const el = strip.querySelector(`.${cls}`);
  return el ? words(el) : null;
};

/** The whole room for a fresh game, in the page, with no model or server behind it. */
function room(over = {}) {
  const doc = installDom();
  api.realism = async () => ({});
  const rv = { ...fixture, documents: fixture.listing, wake_tick: 1, ...over };
  const me = { account: { handle: 'josh' }, game: { id: `g-${Math.random()}`, name: 'Autumn 1941', view: { realism: rv, seat: { name: 'Franklin D. Roosevelt' } } } };
  const root = realismRoom({ me, refresh: async () => {}, go: () => {} });
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  return root;
}

test('the fixture links each form to a court path by its label, and holds orders on two first steps', () => {
  const { court, levers } = linked();
  for (const name of ['send_bill', 'lend_lease_finding', 'move_fleet']) {
    assert.ok(court.paths.some((p) => p.id === lever(levers, name).pipeline), name);
  }
  assert.equal(naval(court).steps[0].orders.length, 1);
  assert.equal(court.load_limit, 2);
});

test('the strip names who carries the order first, with their office', () => {
  const { court, levers } = linked();
  const strip = costStrip(lever(levers, 'move_fleet'), court);
  assert.equal(line(strip, 'rl-cost-who'), 'Carried first by Harold R. Stark, Chief of Naval Operations');
  assert.equal(line(costStrip(lever(levers, 'send_bill'), court), 'rl-cost-who'),
    'Carried first by Sam Rayburn, Speaker of the House of Representatives');
});

test('a first step that is the seat itself reads "you"', () => {
  const { court, levers } = linked();
  const path = naval(court);
  path.steps[0] = { ...path.steps[0], you: true, name: 'Franklin D. Roosevelt' };
  assert.equal(line(costStrip(lever(levers, 'move_fleet'), court), 'rl-cost-who'), 'Carried first by you');
});

test('the days are the sum its path states, and say when a step states none', () => {
  const { court, levers } = linked();
  assert.deepEqual(pathDays(naval(court).steps), { days: 4, open: 0 });
  assert.equal(line(costStrip(lever(levers, 'move_fleet'), court), 'rl-cost-days'), 'Its path takes 4 days');
  assert.equal(line(costStrip(lever(levers, 'send_bill'), court), 'rl-cost-days'), 'Its path takes 39 days');
  naval(court).steps[1].days = null;
  assert.deepEqual(pathDays(naval(court).steps), { days: 2, open: 1 });
  assert.equal(line(costStrip(lever(levers, 'move_fleet'), court), 'rl-cost-days'),
    'Its path takes at least 2 days; one step states no time');
  naval(court).steps[0].days = 1;
  naval(court).steps[1].days = 0;
  assert.equal(line(costStrip(lever(levers, 'move_fleet'), court), 'rl-cost-days'), 'Its path takes 1 day');
});

test('the load is how many of the seat\'s orders the first carrier holds, on every path', () => {
  const { court, levers } = linked();
  const stark = naval(court).steps[0].person;
  assert.equal(heldBy(stark, court), 1);
  assert.equal(line(costStrip(lever(levers, 'move_fleet'), court), 'rl-cost-load'), 'Harold R. Stark already holds 1 of your orders');
  assert.equal(line(costStrip(lever(levers, 'lend_lease_finding'), court), 'rl-cost-load'), 'Harry L. Hopkins holds none of your orders');
  // Stark on a second path, holding another order there; the same order listed twice counts once
  court.paths.push({ id: 'p-x', name: 'Another path', forms: [], steps: [
    { ...naval(court).steps[0], orders: [{ id: 'o-x', label: 'X', since: '1941-10-01', held_days: 3 }] },
    { ...naval(court).steps[1], person: stark, orders: [{ id: 'o-x', label: 'X', since: '1941-10-01', held_days: 3 }] },
  ] });
  assert.equal(heldBy(stark, court), 2);
});

test('past the load limit the strip says the order is likely to go slow', () => {
  const { court, levers } = linked();
  const more = (n) => Array.from({ length: n }, (_, i) => ({ id: `o-more-${i}`, label: 'Move a fleet', since: '1941-10-02', held_days: 1 }));
  const strip = costStrip(lever(levers, 'move_fleet'), court);
  assert.equal(strip.querySelector('.rl-cost-slow'), null, 'one held, limit two: not slow');
  assert.equal(strip.getAttribute('data-slow'), null);
  naval(court).steps[0].orders.push(...more(1));
  assert.equal(costStrip(lever(levers, 'move_fleet'), court).querySelector('.rl-cost-slow'), null,
    'two held, limit two: the engine counts nothing against the next yet');
  naval(court).steps[0].orders.push({ id: 'o-third', label: 'Move a fleet', since: '1941-10-03', held_days: 0 });
  const past = costStrip(lever(levers, 'move_fleet'), court);
  assert.equal(line(past, 'rl-cost-slow'), 'Likely to go slow: past 2 orders, each more that Harold R. Stark holds counts against this one.');
  assert.equal(past.getAttribute('data-slow'), 'true');
  court.load_limit = 0;
  assert.ok(costStrip(lever(levers, 'send_bill'), court).querySelector('.rl-cost-slow'), 'one held, limit none: slow');
  assert.equal(costStrip(lever(levers, 'lend_lease_finding'), court).querySelector('.rl-cost-slow'), null, 'none held: never slow');
});

test('load never slows a clerical first step or the seat\'s own', () => {
  assert.equal(goesSlow({ kind: 'decision', you: false }, 3, 2), true);
  assert.equal(goesSlow({ kind: 'clerical', you: false }, 9, 2), false);
  assert.equal(goesSlow({ kind: 'decision', you: true }, 9, 2), false);
  const { court, levers } = linked();
  const first = naval(court).steps[0];
  first.orders.push(...['a', 'b'].map((id) => ({ id, label: 'Move a fleet', since: '1941-10-02', held_days: 1 })));
  assert.ok(costStrip(lever(levers, 'move_fleet'), court).querySelector('.rl-cost-slow'));
  first.kind = 'clerical';
  assert.equal(costStrip(lever(levers, 'move_fleet'), court).querySelector('.rl-cost-slow'), null);
  Object.assign(first, { kind: 'decision', you: true });
  assert.equal(costStrip(lever(levers, 'move_fleet'), court).querySelector('.rl-cost-slow'), null);
});

test('a form whose path is not in the court data shows no strip', () => {
  const { court, levers } = linked();
  assert.equal(costStrip({ ...lever(levers, 'move_fleet'), pipeline: 'no-such-path' }, court), null);
  assert.equal(costStrip(lever(levers, 'move_fleet'), undefined), null);
  assert.equal(costStrip(lever(levers, 'move_fleet'), { paths: [], ring: [], chambers: [], load_limit: 2 }), null);
  naval(court).steps = [];
  assert.equal(costStrip(lever(levers, 'move_fleet'), court), null, 'a path with no steps');
});

test('in the room the strip sits under the form, inside the panel the form\'s Draft button opens', () => {
  const { court, levers } = linked();
  const root = room({ court, desk: { ...fixture.desk, levers } });
  for (const l of levers) {
    const item = root.querySelector(`.rl-instrument[data-lever="${l.name}"]`);
    const toggle = item.querySelector('[aria-expanded]');
    const panel = item.querySelector(`[id="${toggle.getAttribute('aria-controls')}"]`);
    const strips = item.querySelectorAll('.rl-cost');
    assert.equal(strips.length, 1, l.name);
    assert.equal(strips[0].parentNode, panel, `${l.name}: in the panel`);
    const kids = panel.children;
    assert.ok(kids.indexOf(strips[0]) > kids.indexOf(panel.querySelector('form')), `${l.name}: under the form`);
  }
});

test('in the room a form with no court path, or a room with no court, has no strip', () => {
  const { court, levers } = linked();
  const off = levers.map((l) => (l.name === 'move_fleet' ? { ...l, pipeline: 'no-such-path' } : l));
  const root = room({ court, desk: { ...fixture.desk, levers: off } });
  assert.equal(root.querySelector('.rl-instrument[data-lever="move_fleet"]').querySelectorAll('.rl-cost').length, 0);
  assert.equal(root.querySelector('.rl-instrument[data-lever="send_bill"]').querySelectorAll('.rl-cost').length, 1);
  assert.equal(room({ court: undefined, desk: { ...fixture.desk, levers } }).querySelectorAll('.rl-cost').length, 0);
});

test('the strip\'s file builds text nodes only, and its stylesheet is linked and uses tokens only', () => {
  const js = read('js/views/realism-estimate.js');
  assert.doesNotMatch(js, /innerHTML|outerHTML|insertAdjacentHTML|style=/);
  assert.ok(read('index.html').includes('href="/css/c-estimate.css"'), 'linked from the page');
  const css = read('css/c-estimate.css').replace(/\/\*[\s\S]*?\*\//g, '');
  for (const sel of ['.rl-cost', '.rl-cost-slow']) assert.ok(css.includes(sel), sel);
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(/, 'tokens only');
});
