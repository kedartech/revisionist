// The offer on the floor (PRB), on the Capital board, one test or more per rule, on a seat built
// here with an assembly of three blocs and a bill on its way: 1. picking a bloc's piece for a
// measure on its way shows what that bloc would take, each with its sentence, its points and its
// due days; 2. choosing one runs the check and draws the count as it would stand beside the count
// as it is, then the board's confirm chip; 3. a live offer is marked on its bloc's piece, and a
// promise made shows in "what needs you" with its due day, and as kept or broken once judged, and
// in the board's "you hold and owe"; 4. a bloc with a live offer for that measure offers no second.
// Mutants: a count worked out on the client; an offer drawn for another nation's bloc.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const cap = await import('../js/views/realism-capital.js');
const { needLines, dueWords } = await import('../js/views/realism-needs.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));

const ORDER = 'o-neutrality';
const MEASURE = 'neutrality';

const price = (key, sentence, points, days) => ({ key, sentence, points, days, loss: 5 });
const DUES = price('dues', 'Harbour dues lifted within the season', 2, 30);
const GUILD = price('guild', 'A seat for the guild on the board', 3, 45);

/**
 * The seat's view: Norra with an assembly of three blocs (b0, b1, b2), the neutrality bill on its
 * way with one vote there (120 yea, 40 nay, 150 carry it), b1 naming two prices and b2 none, and
 * no offer made. `change` edits it.
 */
function seat(change = () => {}) {
  const rv = structuredClone(fixture);
  rv.map = structuredClone(fixture.territory_map);
  rv.clock = { ...rv.clock, world_date: '1900-04-10' };
  rv.locks = null;
  rv.conferences = { conferences: [] };
  rv.stakes = { ...rv.stakes, contests: [], mandates: [] };
  const assembly = [['b0', 'Bloc Zero', 100], ['b1', 'Bloc One', 60], ['b2', 'Bloc Two', 40]]
    .map(([group, name, seats]) => ({ group, name, seats, support: 50 }));
  rv.home = {
    ...structuredClone(fixture.home),
    groups: assembly.map((b) => ({ key: b.group, name: b.name, kind: 'party', support: 50, last_moved: null, feeds: { votes: 1 } })),
    chambers: [{ key: 'assembly', blocs: assembly, measures: [{ order_id: ORDER, key: MEASURE, title: 'Revising the Neutrality Act', votes: [{
      vote: 'assembly', yeas: 120, nays: 40, carries: 101,
      blocs: [{ group: 'b0', yeas: 90, nays: 0 }, { group: 'b1', yeas: 20, nays: 30 }, { group: 'b2', yeas: 10, nays: 10 }],
    }] }] }],
    themes: [],
    offers: [{ key: MEASURE, title: 'Revising the Neutrality Act', blocs: [
      { group: 'b0', name: 'Bloc Zero', prices: [], live: null },
      { group: 'b1', name: 'Bloc One', prices: [DUES, GUILD], live: null },
      { group: 'b2', name: 'Bloc Two', prices: [], live: null },
    ] }],
    promises: [],
  };
  change(rv);
  return rv;
}

const bloc = (rv, g) => rv.home.offers[0].blocs.find((b) => b.group === g);

/** The board alone, with a record of what its controls asked of the room; `check` answers the board's check. */
function board(rv, state = {}, check = async () => ({ check: 'allowed', who: null, reason: '', stands: [] })) {
  installDom();
  const asked = [];
  const on = Object.fromEntries(['board', 'person', 'map', 'ask', 'openAsk', 'conference', 'speak', 'full', 'offer']
    .map((k) => [k, (...a) => asked.push([k, ...a])]));
  on.offerCheck = (body) => { asked.push(['offerCheck', body]); return check(body); };
  const el = cap.capitalBoard(rv, state, on);
  document.body.append(el);
  return { el, asked, state };
}

const q = `vote:${ORDER}`;
const press = (el, key) => el.querySelector(`button[data-key="${key}"]`).click();
const settle = () => new Promise((r) => { setTimeout(r, 0); });
const prices = (el) => el.querySelectorAll('.rl-cap-side button.rl-cap-price');

// rule 1: picking a bloc shows what it would take

test('picking a bloc for a measure on its way shows each price with its sentence, its points and its due days', () => {
  const { el } = board(seat(), { q });
  assert.equal(prices(el).length, 0, 'nothing until a bloc is picked');
  press(el, 'piece:b1');
  const found = prices(el);
  assert.deepEqual(found.map((b) => b.getAttribute('data-key')), ['price:dues', 'price:guild']);
  assert.match(words(found[0]), /Harbour dues lifted within the season/);
  assert.match(words(found[0]), /2 points/);
  assert.match(words(found[0]), /30 days after it passes/);
  assert.match(words(found[1]), /3 points/);
  assert.match(words(found[1]), /45 days after it passes/);
  // the points are drawn, one pip each
  assert.equal(found[1].querySelectorAll('.rl-cap-pip').length, 3);
});

test('a bloc that names no price says so, and offers nothing', () => {
  const { el } = board(seat(), { q, pick: 'b2' });
  assert.equal(prices(el).length, 0);
  assert.equal(words(el.querySelector('.rl-cap-side .rl-cap-prices')), cap.NO_PRICE);
});

test('no price is drawn for a bloc the server listed that is not one of the seat\'s own chambers', () => {
  const rv = seat((v) => {
    v.home.offers[0].blocs.push({ group: 'x9', name: 'Their Bloc', prices: [DUES], live: null });
  });
  const { el } = board(rv, { q, pick: 'x9' });
  assert.equal(prices(el).length, 0);
  assert.equal(el.querySelector('.rl-cap-piece[data-group="x9"]'), null);
});

test('a home block of another nation draws no price and no mark', () => {
  const rv = seat((v) => {
    v.home.nation = { ...v.home.nation, relation: 'neutral' };
    bloc(v, 'b1').live = { price: 'dues', points: 2, mine: true };
  });
  const { el } = board(rv, { q, pick: 'b1' });
  assert.equal(prices(el).length, 0);
  assert.equal(el.querySelectorAll('.rl-cap-offered').length, 0);
});

// rule 2: the check, the count as it would stand, the confirm chip

const STANDS = [{ chamber: 'assembly', vote: 'assembly', yeas: 133, nays: 27, carries: 101, blocs: [
  { group: 'b0', yeas: 90, nays: 0 }, { group: 'b1', yeas: 33, nays: 17 }, { group: 'b2', yeas: 10, nays: 10 },
] }];

test('choosing a price runs the check with the bloc, the measure and the price', async () => {
  const { el, asked } = board(seat(), { q, pick: 'b1' });
  press(el, 'price:guild');
  await settle();
  assert.deepEqual(asked.filter(([k]) => k === 'offerCheck'), [['offerCheck', { bloc: 'b1', measure: MEASURE, price: 'guild' }]]);
});

test('an allowed check draws the count as it would stand beside the count as it is, with the confirm chip', async () => {
  const { el, asked } = board(seat(), { q, pick: 'b1' }, async () => ({ check: 'allowed', who: null, reason: '', stands: STANDS }));
  press(el, 'price:guild');
  await settle();
  const tracks = el.querySelectorAll('.rl-cap-middle .rl-cap-trackbox');
  assert.equal(tracks.length, 2, 'the track as it is and as it would stand');
  assert.match(words(tracks[0]), /120 yea · 40 nay/);
  assert.match(words(tracks[1]), /As it would stand/);
  assert.match(words(tracks[1]), /133 yea · 27 nay/);
  const b1 = tracks[1].querySelector('rect.rl-cap-yea[data-group="b1"]');
  assert.ok(b1, 'the bloc\'s yeas as they would stand are drawn');
  const chip = el.querySelector('.rl-cap-side button.rl-cap-confirm');
  assert.ok(chip);
  assert.match(words(el.querySelector('.rl-cap-side .rl-cap-would')), /133 yea · 27 nay/);
  chip.click();
  assert.deepEqual(asked.filter(([k]) => k === 'offer'), [['offer', { bloc: 'b1', measure: MEASURE, price: 'guild' }]]);
});

test('the count as it would stand is the one the server sent, never one the client adds up', async () => {
  // the server's count does not equal today's count plus the price's points
  const odd = structuredClone(STANDS);
  odd[0].yeas = 777;
  odd[0].blocs[1].yeas = 21;
  const { el } = board(seat(), { q, pick: 'b1' }, async () => ({ check: 'allowed', who: null, reason: '', stands: odd }));
  press(el, 'price:dues');
  await settle();
  const would = el.querySelectorAll('.rl-cap-middle .rl-cap-trackbox')[1];
  assert.match(words(would), /777 yea · 27 nay/);
  assert.match(words(el.querySelector('.rl-cap-side .rl-cap-would')), /777 yea/);
  assert.doesNotMatch(words(el), /122 yea|123 yea/);
});

test('a refused check says why and draws no chip and no second count', async () => {
  const { el } = board(seat(), { q, pick: 'b1' }, async () => ({ check: 'beyond', who: null, reason: 'That measure has no bill on its way.' }));
  press(el, 'price:dues');
  await settle();
  assert.equal(el.querySelector('.rl-cap-confirm'), null);
  assert.equal(el.querySelectorAll('.rl-cap-middle .rl-cap-trackbox').length, 1);
  assert.match(words(el.querySelector('.rl-cap-side')), /That measure has no bill on its way/);
});

test('a check that fails to come back draws no chip', async () => {
  const { el } = board(seat(), { q, pick: 'b1' }, async () => { throw new Error('down'); });
  press(el, 'price:dues');
  await settle();
  assert.equal(el.querySelector('.rl-cap-confirm'), null);
  assert.match(words(el.querySelector('.rl-cap-side')), new RegExp(cap.CHECK_FAILED));
});

test('picking another bloc or the same price again drops the chosen offer', async () => {
  const { el, state } = board(seat(), { q, pick: 'b1' }, async () => ({ check: 'allowed', who: null, reason: '', stands: STANDS }));
  press(el, 'price:dues');
  await settle();
  assert.ok(el.querySelector('.rl-cap-confirm'));
  press(el, 'price:dues');
  assert.equal(state.offer, null);
  assert.equal(el.querySelector('.rl-cap-confirm'), null);
  press(el, 'price:dues');
  await settle();
  press(el, 'piece:b0');
  assert.equal(el.querySelector('.rl-cap-confirm'), null);
});

// rule 3: a live offer on its piece; promises in the list and in "you hold and owe"

test('a live offer is marked on its bloc\'s piece, and only there', () => {
  const rv = seat((v) => { bloc(v, 'b1').live = { price: 'dues', points: 2, mine: true }; });
  const { el } = board(rv, { q });
  const marked = el.querySelectorAll('.rl-cap-piece.offered');
  assert.deepEqual(marked.map((p) => p.getAttribute('data-group')), ['b1']);
  assert.match(marked[0].getAttribute('aria-label'), /your offer is live/i);
  assert.ok(marked[0].querySelector('.rl-cap-offered'));
});

const promise = (standing, due = null, extra = {}) => ({
  offer_id: `of-${standing}`, group: 'b1', name: 'Bloc One', measure: MEASURE, title: 'Revising the Neutrality Act',
  price: 'dues', sentence: DUES.sentence, standing, filed: '1900-04-01', due, ...extra,
});

test('a promise made shows in what needs you with its due day', () => {
  const rv = seat((v) => { v.home.promises = [promise('due', '1900-05-10')]; });
  const lines = needLines(rv).filter((l) => l.kind === 'promise');
  assert.equal(lines.length, 1);
  assert.match(lines[0].what, /Bloc One/);
  assert.match(lines[0].what, /Harbour dues lifted/);
  assert.equal(lines[0].due, '1900-05-10');
  assert.match(dueWords(lines[0]), /^Due /);
});

test('a promise judged shows as kept or as broken', () => {
  const rv = seat((v) => { v.home.promises = [promise('kept', '1900-04-02'), promise('broken', '1900-04-03')]; });
  const lines = needLines(rv).filter((l) => l.kind === 'promise');
  assert.deepEqual(lines.map((l) => l.what.split(':')[0]), ['Promise kept to Bloc One', 'Promise broken to Bloc One']);
});

test('an offer refused or lapsed is no promise, one taken waits on its measure, and with offers off there is no line', () => {
  const rv = seat((v) => { v.home.promises = [promise('refused'), promise('lapsed'), promise('filed'), promise('taken')]; });
  assert.equal(needLines(rv).filter((l) => l.kind === 'promise').length, 0);
  const off = seat((v) => { delete v.home.promises; });
  assert.equal(needLines(off).filter((l) => l.kind === 'promise').length, 0);
});

test('the board\'s you hold and owe lists each promise with where it stands', () => {
  const rv = seat((v) => {
    v.home.promises = [promise('taken'), promise('due', '1900-05-10'), promise('broken', '1900-04-03')];
  });
  const { el } = board(rv, { q });
  const owed = el.querySelectorAll('.rl-cap-side .rl-cap-promise');
  assert.equal(owed.length, 3);
  assert.match(words(owed[0]), /owed once it passes/i);
  assert.match(words(owed[1]), /Due/);
  assert.ok(owed[2].className.includes('broken'));
  assert.equal(el.querySelector('.rl-cap-side .rl-cap-owed'), null);
});

test('with no promise the board still says nothing is owed', () => {
  const { el } = board(seat(), { q });
  assert.equal(words(el.querySelector('.rl-cap-side .rl-cap-owed')), cap.OWED_NONE);
});

// rule 4: one live offer per bloc and measure

test('a bloc with a live offer for the measure offers no second price', () => {
  for (const mine of [true, false]) {
    const rv = seat((v) => { bloc(v, 'b1').live = { price: 'guild', points: 3, mine }; });
    const { el } = board(rv, { q, pick: 'b1' });
    assert.equal(prices(el).length, 0);
    assert.match(words(el.querySelector('.rl-cap-side .rl-cap-prices')), mine ? /You have offered/ : /An offer is live/);
  }
});

// keeps

test('every control the offer adds is at least 44 px and a button the keyboard reaches', () => {
  const css = readFileSync(new URL('../css/c-capital.css', import.meta.url), 'utf8');
  for (const cls of ['rl-cap-price', 'rl-cap-confirm', 'rl-cap-cancel']) {
    assert.match(css, new RegExp(`\\.${cls}[^{]*\\{[^}]*min-height: 44px`), cls);
  }
  assert.doesNotMatch(css, /#[0-9a-f]{3,8}\b|rgb\(|hsl\(/i);
});
