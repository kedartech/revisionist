// The capital opens the nation's live questions: the Capital board's list is the server's list
// for the seat's own capital; picking the seat's own capital on the map opens the Capital board,
// and picking another nation's opens that nation's public lines as a sheet over the map.
//
//   1. the seat's own capital stands on the map's Diplomatic layer where the server places it
//   2. picking it opens the Capital board
//   3. picking another nation's capital opens a sheet of that nation's public lines and nothing more
//   4. the board's list is the server's: a question the server did not send is not drawn, and each
//      kind the server sends is a row with its day and who decides it

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
const { loadShapes, theatreBoard } = await import('../js/views/realism-theatre.js');
const cap = await import('../js/views/realism-capital.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
// the territory board draws once its shapes are in hand
await loadShapes(fixture.territory_map.file, async () => ({ refused: false, file: fixture.territory_map.file, map: SHAPES }));
const OWN = fixture.capitals.find((c) => c.nation.relation === 'own');
const FOREIGN = fixture.capitals.find((c) => c.nation.relation !== 'own');

/** The seat's view on the 1941 map with the fixture's capital lines; `change` edits it. */
function seat(change = () => {}) {
  const rv = structuredClone(fixture);
  rv.documents = structuredClone(fixture.listing);
  rv.clock = { ...rv.clock, world_date: '1900-04-10' };
  rv.wake_tick = 1;
  rv.style = 'free';
  rv.battles = [];
  rv.wake = { ...rv.wake, deadline: '2999-01-01T00:00:00+00:00', you_committed: false, humans: 1, committed: 0 };
  change(rv);
  return rv;
}

/**
 * The seat's view on the territory board, the map-first room's: Tomas Brand at Sudby, which the
 * server gives as Sudland's capital, and Norrhavn as the seat's own.
 */
function territorySeat() {
  return seat((x) => {
    x.map = structuredClone(fixture.territory_map);
    const [norrhavn, sudby] = x.map.places;
    x.map.capitals = [{ place: sudby, name: 'Tomas Brand', stance: { word: 'Hostile', step: 1 }, at_war: true }];
    x.capitals[0].place = norrhavn;
    x.capitals[1].place = sudby;
  });
}

function room(rv) {
  const doc = installDom();
  setRoomLayout('map');
  api.realism = async () => ({});
  api.catchup = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  const game = { id: `h26-${Math.random()}`, name: 'Autumn 1941', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'Franklin D. Roosevelt' } } };
  const ctx = { me: { account: { handle: 'josh' }, game }, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {}, signOut: () => {} };
  const root = realismRoom(ctx);
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  return { root, now: () => doc.body.firstElementChild, doc };
}

const layer = (root, name) => {
  const group = root.querySelectorAll('[role="group"]').find((g) => g.getAttribute('aria-label') === 'Layer');
  buttons(group, name)[0].click();
};
const pin = (root, name) => root.querySelectorAll('g.rl-cap').find((g) => g.getAttribute('data-leader') === name);

// rule 1: the seat's own capital on the map

test('the seat\'s own capital stands on the Diplomatic layer at the place the server gives', () => {
  const view = theatreBoard(seat(), { piece: null, theatre: { mode: 'map', scope: 'world', layer: 'diplomatic' } }, { pick: () => {}, act: () => {}, onCapital: () => {} });
  const own = view.querySelectorAll('.rl-map-svg .rl-cap').find((g) => g.getAttribute('data-leader') === OWN.nation.name);
  assert.ok(own, 'the own capital is drawn');
  assert.match(own.getAttribute('aria-label'), new RegExp(OWN.place.name));
  assert.match(words(own), /Your capital/);
});

test('with no place from the server the seat\'s own capital is not drawn', () => {
  const rv = seat((x) => { x.capitals[0].place = null; });
  const view = theatreBoard(rv, { piece: null, theatre: { mode: 'map', scope: 'world', layer: 'diplomatic' } }, { pick: () => {}, act: () => {}, onCapital: () => {} });
  assert.deepEqual(view.querySelectorAll('.rl-map-svg .rl-cap').map((g) => g.getAttribute('data-leader')), fixture.map.capitals.map((c) => c.name));
});

test('a map with nothing to open the Capital draws no own capital', () => {
  const view = theatreBoard(seat(), { piece: null, theatre: { mode: 'map', scope: 'world', layer: 'diplomatic' } }, { pick: () => {}, act: () => {} });
  assert.deepEqual(view.querySelectorAll('.rl-map-svg .rl-cap').map((g) => g.getAttribute('data-leader')), fixture.map.capitals.map((c) => c.name));
});

// rules 2 and 3: what picking a capital opens

test('picking a capital hands the server\'s line for the nation at that place to the room', () => {
  const opened = [];
  const doc = installDom();
  const view = theatreBoard(seat(), { piece: null, theatre: { mode: 'map', scope: 'world', layer: 'diplomatic' } }, { pick: () => {}, act: () => {}, onCapital: (line) => opened.push(line) });
  doc.body.append(view);
  view.querySelectorAll('.rl-cap').find((g) => g.getAttribute('data-leader') === OWN.nation.name).click();
  view.querySelectorAll('.rl-cap').find((g) => g.getAttribute('data-leader') === 'Adolf Hitler').click();
  assert.deepEqual(opened.map((l) => l.nation.name), [OWN.nation.name, FOREIGN.nation.name]);
  assert.equal(doc.body.querySelector('dialog.rl-fc'), null, 'no leader card in place of the nation');
  view.querySelectorAll('.rl-cap').find((g) => g.getAttribute('data-leader') === 'Joseph Stalin').click();
  assert.equal(opened.length, 2, 'a capital the server names no nation for does not open one');
  assert.ok(doc.body.querySelector('dialog.rl-fc'), 'it opens its leader\'s card');
});

test('in the room, picking the seat\'s own capital opens the Capital board with the server\'s list', () => {
  const { root, now } = room(territorySeat());
  layer(root, 'Diplomatic');
  pin(now(), OWN.nation.name).click();
  const board = now().querySelector('section.rl-cap');
  assert.ok(board, 'the Capital board');
  const keys = board.querySelectorAll('button.rl-cap-q').map((b) => b.getAttribute('data-key'));
  assert.ok(keys.length > 0);
  for (const q of OWN.questions.filter((s) => s.at !== 'home.chambers')) assert.ok(keys.includes(`${q.kind}:${q.ref}`), `${q.kind} is a row`);
  assert.equal(now().querySelector('.rl-over .rl-cap-sheet'), null);
});

test('in the room, picking another nation\'s capital opens its public lines as a sheet over the map', () => {
  const { root, now } = room(territorySeat());
  layer(root, 'Diplomatic');
  pin(now(), 'Tomas Brand').click();
  const sheet = now().querySelector('.rl-cap-sheet');
  assert.ok(sheet, 'the sheet');
  assert.equal(sheet.getAttribute('data-nation'), FOREIGN.nation.name);
  assert.ok(now().querySelector('.rl-mapfirst-map .rl-tmap'), 'the map stays under it');
  assert.equal(words(now().querySelector('.rl-over-title')), FOREIGN.nation.name);
  assert.equal(now().querySelector('section.rl-cap'), null, 'not the Capital board');
  assert.deepEqual(sheet.querySelectorAll('li.rl-cap-pub').map((li) => li.getAttribute('data-key')), FOREIGN.questions.map((q) => `${q.kind}:${q.ref}`));
});

test('the sheet draws only the nation\'s own public line: nothing of the seat\'s own capital', () => {
  const el = cap.capitalSheet(FOREIGN);
  const text = words(el);
  assert.match(text, /Marshal of Sudland/);
  assert.match(text, /Tomas Brand/);
  assert.match(text, /Berlin/);
  for (const q of OWN.questions) assert.doesNotMatch(text, new RegExp(q.title.replace(/[()]/g, '\\$&')), `${q.kind} of the seat's own is not drawn`);
  const bare = cap.capitalSheet({ ...FOREIGN, questions: [] });
  assert.match(words(bare), /Nothing of Sudland's is public yet/);
  assert.equal(bare.querySelectorAll('li').length, 0);
});

// rule 4: the list is the server's

test('the Capital board\'s list is the server\'s: a question the server did not send is not drawn', () => {
  const rv = seat();
  const held = rv.locks.held[0];
  assert.ok(cap.capitalQuestions(rv).some((q) => q.key === `held:${held.id}`));
  rv.capitals[0].questions = rv.capitals[0].questions.filter((q) => q.ref !== held.id);
  assert.equal(cap.capitalQuestions(rv).some((q) => q.key === `held:${held.id}`), false, 'the held order is in the view but not in the list');
  const none = seat((x) => { x.capitals = []; });
  assert.equal(cap.capitalQuestions(none).filter((q) => ['vote', 'held', 'ask', 'peace', 'election'].includes(q.kind)).length, 0);
});

test('a line the server sends whose block the view does not hold is not drawn', () => {
  const rv = seat((x) => { x.locks.asks = []; });
  assert.equal(cap.capitalQuestions(rv).some((q) => q.kind === 'ask'), false);
});

test('each kind the server lists is a row with its words, its day and who decides it', () => {
  const rv = seat();
  const rows = cap.capitalQuestions(rv);
  const peace = rows.find((q) => q.kind === 'peace');
  assert.ok(peace);
  assert.equal(peace.kindWords, 'A peace to answer');
  assert.equal(peace.title, 'Peace offered by Sudland');
  assert.equal(peace.decides, 'Ilse Varg');
  const election = rows.find((q) => q.kind === 'election');
  assert.equal(election.days, 21, 'from 10 April to 1 May');
  const ask = rows.find((q) => q.kind === 'ask');
  assert.equal(ask.decides, 'You');
  assert.equal(ask.decider.shape, 'council');
});

test('a council the server names draws its table and each member', () => {
  const rv = seat();
  const ask = rv.capitals[0].questions.find((q) => q.kind === 'peace');
  ask.decider = { shape: 'council', who: 'the war council', members: ['Ilse Varg', 'Kara Lind'] };
  installDom();
  const el = cap.capitalBoard(rv, { q: `peace:${ask.ref}` }, Object.fromEntries(['board', 'person', 'map', 'ask', 'openAsk', 'conference', 'speak', 'full'].map((k) => [k, () => {}])));
  const council = el.querySelector('.rl-cap-council');
  assert.ok(council);
  assert.match(words(council), /A council decides.*the war council/);
  assert.deepEqual(council.querySelectorAll('tr[data-member]').map((r) => r.getAttribute('data-member')), ['Ilse Varg', 'Kara Lind']);
});
