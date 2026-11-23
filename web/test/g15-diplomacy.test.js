// The diplomacy layer (DPL), one test or more per plan rule: 1. the map's diplomatic layer shows
// each nation's standing to the seat (who is at war with it), the public pacts and the envoys, which
// are picked up and put down like any piece; 2. the agreements sheet lists each agreement with a chip
// per clause (pending, kept, broken or unchecked); 3. the offer builder takes free wording and typed
// clauses added from a list, and its reading shows the aide's interpretation, the unchecked wording
// and the terms for signing as the server rendered them; 4. an offer or a conference aimed at the
// seat is a line in "What needs you" with its due day; 5. the conference sheet calls a conference,
// votes For, Against or Abstain, replaces a vote by voting again in the same wake, and shows the
// result after the tally; 6. an agreement the seat is party to has Publish. Mutants: an unchecked
// clause drawn as checked; another seat's vote drawn before the tally.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, fire, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const dpl = await import('../js/views/realism-diplomacy.js');
const { territoryDrawing, territoryView, offeredLayers, forgetMarks } = await import('../js/views/realism-territory.js');
const { theatreBoard, forgetShapes } = await import('../js/views/realism-theatre.js');
const needs = await import('../js/views/realism-needs.js');
const { requestChoices, ANSWER_AT_CLOSE } = await import('../js/views/realism-requests.js');
const { needsAnswer } = await import('../js/views/realism-answer.js');
const { api } = await import('../js/api.js');
const { realismRoom, uiFor } = await import('../js/views/realism-room.js');
const { setRoomLayout } = await import('../js/views/realism-sheets.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const TMAP = fixture.territory_map;
const PX = { width: 800, height: 600 };
const NORRA = fixture.home.standings[0].nation.key;
const SUDLAND = fixture.home.standings[1].nation.key;
const HERALD = 'The Norra Herald';
const OFFER_ID = '4CB1HQP7RTP4J38MKTKDBK08VF';

/** The toy world's movement form, which lists the Herald with the other pieces. */
const MOVE = {
  name: 'move_piece', label: 'Move a piece', summary: 'Send a piece to another area.', pipeline: 'field_order',
  params: [
    { name: 'force', label: 'Which piece', kind: 'enum', lo: null, hi: null, places: [], choices: [
      { value: 'norra_levy', label: 'The Norra Levy' }, { value: 'norra_herald', label: HERALD }] },
    { name: 'to', label: 'To', kind: 'enum', lo: null, hi: null, places: [], choices: [
      { value: 'isle', label: 'The Isle' }, { value: 'the_gulf', label: 'The Gulf' }, { value: 'open_sea', label: 'The Open Sea' }] },
  ],
};

/** The seat's view on the toy board, on 14 April 1900; nothing on its agenda. */
function seat(change = () => {}) {
  const rv = structuredClone(fixture);
  rv.map = structuredClone(TMAP);
  rv.battles = [];
  rv.agenda = { ...rv.agenda, items: [] };
  rv.orders = { orders: rv.orders.orders.map((o) => ({ ...o, decision_needed: false })) };
  rv.documents = structuredClone(rv.listing);
  rv.clock = { ...rv.clock, world_date: '1900-04-14' };
  rv.wake_tick = 1;
  change(rv);
  return rv;
}

/** Every call `act` was given, as [action, body]; `then` is kept to answer one. */
function recorder() {
  const calls = [];
  const act = (message, action, body, then) => { calls.push({ message, action, body, then }); };
  return { calls, act };
}

const marksOn = (pic) => pic.querySelectorAll('g.rl-tm-mark').map((g) => g.getAttribute('aria-label'));
const chips = (el) => el.querySelectorAll('.rl-dp-chip');
const agreementOf = (el, id) => el.querySelectorAll('.rl-dp-agreement').find((li) => li.getAttribute('data-agreement') === id);
const conferenceOf = (el, key) => el.querySelectorAll('.rl-dp-conference').find((li) => li.getAttribute('data-conference') === key);

// --- Rule 1: the diplomatic layer ------------------------------------------------------------

test('the diplomatic layer is offered on a board that has an envoy and no capital to pin', () => {
  assert.deepEqual(TMAP.capitals, []);
  assert.ok(offeredLayers(TMAP).includes('diplomatic'));
  const map = structuredClone(TMAP);
  map.marks = map.marks.filter((m) => m.piece?.domain !== 'envoy');
  assert.ok(!offeredLayers(map).includes('diplomatic'), 'nothing diplomatic to draw: not offered');
});

test('the diplomatic layer draws the envoys, with an envoy\'s glyph, and no other piece', () => {
  forgetMarks();
  const pic = territoryDrawing(TMAP, SHAPES, { layer: 'diplomatic', px: PX });
  const drawn = marksOn(pic);
  assert.equal(drawn.length, 1, 'one piece: the envoy');
  assert.match(drawn[0], /Norra Herald/);
  const herald = pic.querySelector('g.rl-tm-mark');
  assert.ok(herald.querySelector('path.rl-mk-envoy'), 'the envoy\'s own glyph');
  const military = territoryDrawing(TMAP, SHAPES, { layer: 'military', px: PX });
  assert.ok(military.querySelector('path.rl-mk-envoy'), 'an envoy is drawn as an envoy on the military layer too');
});

/** The theatre board over `rv`, redrawn on each pick as the room does; every `act` recorded. */
async function board(rv, ui) {
  const acts = [];
  const was = globalThis.fetch;
  globalThis.fetch = async (url) => ({ ok: true, status: 200, json: async () => (url === '/api/realism/map' ? { reply: '', refused: false, file: TMAP.file, map: SHAPES } : {}) });
  const r = {
    ui, acts, view: null,
    draw() {
      r.view?.remove();
      r.view = theatreBoard(rv, ui, {
        pick: (p) => { if (p.theatre) ui.theatre = p.theatre; if (p.piece !== undefined) ui.piece = p.piece; r.draw(); },
        act: (message, action, body, then) => { acts.push({ message, action, body, then }); },
      });
      document.body.append(r.view);
      return r.view;
    },
  };
  try {
    forgetShapes();
    forgetMarks();
    r.draw();
    await new Promise((ok) => setTimeout(ok, 0));
    await new Promise((ok) => setTimeout(ok, 0));
  } finally { globalThis.fetch = was; }
  r.draw();
  return r;
}

test('on the diplomatic layer an envoy is picked up and put down like any piece', async () => {
  const rv = seat((x) => { x.desk = { ...x.desk, levers: [MOVE] }; });
  const r = await board(rv, { piece: null, theatre: { mode: 'map', scope: 'reports', layer: 'diplomatic' } });
  const herald = r.view.querySelectorAll('g.rl-tm-mark').find((g) => /Norra Herald/.test(g.getAttribute('aria-label')));
  herald.click();
  assert.deepEqual(r.ui.piece, { kind: 'force', name: HERALD });
  const lit = r.view.querySelectorAll('g.rl-map-target').map((g) => g.getAttribute('data-area')).sort();
  assert.deepEqual(lit, ['open_sea', 'the_gulf'], 'its moves the form can send it to');
  r.view.querySelectorAll('g.rl-map-target').find((g) => g.getAttribute('data-area') === 'the_gulf').click();
  r.view.querySelector('.rl-pup-chip').querySelectorAll('button').find((b) => words(b) === 'Send it').click();
  const filed = r.acts.filter((a) => a.action === 'lever');
  assert.deepEqual(filed.map((a) => a.body), [{ lever: 'move_piece', params: { force: 'norra_herald', to: 'the_gulf' } }]);
});

test('on the diplomatic layer a piece that is not an envoy is not picked up', async () => {
  const rv = seat((x) => { x.desk = { ...x.desk, levers: [MOVE] }; });
  const r = await board(rv, { piece: { kind: 'force', name: 'The Norra Levy' }, theatre: { mode: 'map', scope: 'reports', layer: 'diplomatic' } });
  assert.equal(r.view.querySelectorAll('g.rl-map-target').length, 0);
});

/** `rv` with a public pact between two other nations and the seat's own private agreement. */
function withPact(rv) {
  rv.agreements.agreements.push({
    id: 'pact-1', parties: ['Ostmark', 'Vesta'], wording: 'The pact of the strait.', made: '1900-04-01',
    published: '1900-04-01', party: false, clauses: [],
  });
  return rv;
}

test('the layer\'s key names each nation\'s standing to the seat, the public pacts and the envoys', () => {
  const key = dpl.diplomacyKey(withPact(seat()));
  const lines = (cls) => key.querySelectorAll(`.${cls} li`).map(words);
  assert.deepEqual(lines('rl-dp-nations'), ['Norra: your nation', 'Sudland: at war with you']);
  assert.deepEqual(lines('rl-dp-pacts'), ['Ostmark and Vesta: The pact of the strait. Public since 1 April 1900']);
  assert.deepEqual(lines('rl-dp-envoys'), ['The Norra Herald: in The Norra Plain']);
  assert.ok(!words(key).includes('agr-0') && !words(key).includes('Friendship'), 'a private agreement is not a public pact');
});

test('the key is drawn under the map on the diplomatic layer only', () => {
  const key = () => dpl.diplomacyKey(seat());
  const on = territoryView(TMAP, SHAPES, { layer: 'diplomatic', px: PX, diplomacy: key() });
  assert.ok(on.querySelector('.rl-dp-key'));
  const off = territoryView(TMAP, SHAPES, { layer: 'military', px: PX, diplomacy: key() });
  assert.equal(off.querySelector('.rl-dp-key'), null);
});

// --- Rule 2: the agreements sheet ------------------------------------------------------------

test('each agreement lists its clauses with a chip each: kept, pending, broken, or not checked', () => {
  const rv = seat();
  let el = dpl.agreementsSection(rv.agreements, recorder());
  assert.deepEqual(chips(agreementOf(el, 'agr-0')).map(words), ['Kept', 'Pending', 'Not checked by the rules']);
  assert.deepEqual(chips(el).map((c) => c.getAttribute('data-state')), ['kept', 'pending', 'unchecked']);
  rv.agreements.agreements[0].clauses[1].state = 'broken';
  el = dpl.agreementsSection(rv.agreements, recorder());
  assert.equal(words(chips(el)[1]), 'Broken');
  assert.match(words(agreementOf(el, 'agr-0')), /Norra and Sudland/);
  assert.match(words(agreementOf(el, 'agr-0')), /no piece enters The Isle/);
});

test('an unchecked clause is never drawn as checked, whatever state it carries', () => {
  const rv = seat();
  const forged = rv.agreements.agreements[0].clauses[2];
  forged.state = 'kept';
  const chip = chips(dpl.agreementsSection(rv.agreements, recorder()))[2];
  assert.equal(words(chip), 'Not checked by the rules');
  assert.equal(chip.getAttribute('data-checked'), 'false');
  assert.equal(chip.getAttribute('data-state'), 'unchecked');
});

test('the seat\'s own offers show each nation\'s answer; an offer to the seat says it waits on its answer', () => {
  const el = dpl.agreementsSection(seat().agreements, recorder());
  const offers = el.querySelectorAll('.rl-dp-offer').map(words);
  assert.match(offers[0], /Your offer to Sudland/);
  assert.match(offers[0], /Sudland: no answer yet/);
  assert.match(offers[0], /Due 6 April 1900/);
  assert.match(offers[1], /Ostmark offers/);
  assert.match(offers[1], /Your answer is due 6 April 1900/);
});

// --- Rule 3: the offer builder and its reading -----------------------------------------------

test('the clause list holds the clauses the seat can name from what it is shown', () => {
  assert.deepEqual(dpl.CLAUSE_TYPES.map(([t]) => t), ['no_war', 'no_attack', 'defend', 'aid']);
});

test('the offer builder sends free wording, the nations named and the typed clauses added from the list', () => {
  const rv = seat();
  const draft = dpl.freshOffer();
  const { calls, act } = recorder();
  let el;
  const draw = () => { el = dpl.offerBuilder(rv, draft, { act, redraw: draw }); };
  draw();
  const text = el.querySelector('textarea');
  text.value = 'Peace on the isle.';
  fire(text, 'input');
  const sud = el.querySelectorAll('input[type="checkbox"]').find((i) => i.value === SUDLAND);
  sud.checked = true;
  fire(sud, 'change');
  const type = el.querySelector('select.rl-dp-addtype');
  type.value = 'defend';
  buttons(el, 'Add the clause')[0].click();
  const row = el.querySelector('.rl-dp-clause');
  assert.ok(row, 'the clause is added to the offer');
  const field = (name) => row.querySelectorAll('select, input').find((f) => f.getAttribute('name') === name);
  field('binds').value = NORRA;
  fire(field('binds'), 'change');
  field('nation').value = SUDLAND;
  fire(field('nation'), 'change');
  field('days').value = '10';
  fire(field('days'), 'input');
  assert.match(words(el), /Carried by the usual channel/);
  buttons(el, 'Read the terms')[0].click();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].action, 'agreement-offer');
  assert.deepEqual(calls[0].body, {
    parties: [SUDLAND], wording: 'Peace on the isle.', clauses: [{ type: 'defend', binds: NORRA, nation: SUDLAND, days: 10 }],
  });
});

test('a clause can be taken out again before the terms are read', () => {
  const draft = dpl.freshOffer();
  draft.clauses.push({ type: 'no_war', binds: NORRA, nation: SUDLAND });
  let el;
  const draw = () => { el = dpl.offerBuilder(seat(), draft, { act: () => {}, redraw: draw }); };
  draw();
  buttons(el, 'Take it out')[0].click();
  assert.deepEqual(draft.clauses, []);
  assert.equal(el.querySelector('.rl-dp-clause'), null);
});

/** The fixture's reading of an offer, with one clause the aide read and the wording unchecked. */
function reading() {
  const r = structuredClone(fixture.offer_reading);
  r.terms.clauses = [
    { text: 'Norra: no piece enters The Isle, at all times.', checked: true, interpretation: true },
    { text: 'Norra: Free passage for traders. (not checked by the rules).', checked: false, interpretation: false },
  ];
  return r;
}

test('the reading shows the aide\'s interpretation, what the rules do not check, and the terms to sign; signing files it', () => {
  const { calls, act } = recorder();
  const card = dpl.termsCard(reading(), { act, onBack: () => {} });
  const clauses = card.querySelectorAll('.rl-dp-term').map(words);
  assert.match(clauses[0], /Your aide's reading of your wording/);
  assert.doesNotMatch(clauses[0], /Not checked/);
  assert.match(clauses[1], /Not checked by the rules/);
  assert.match(words(card), /Your wording, which the rules do not check: Peace on the isle\./);
  assert.match(words(card.querySelector('.rl-dp-signed')), /The terms you sign/);
  assert.match(words(card.querySelector('.rl-dp-signed')), /Parties: Norra, Sudland\. Clause 1: Norra: no piece enters The Isle, at all times\./);
  assert.match(words(card), /Carried by the usual channel/);
  buttons(card, 'Sign and send')[0].click();
  assert.deepEqual(calls.map((c) => [c.action, c.body]), [['file', {}]]);
});

test('a reading the rules refuse shows why, with nothing to sign', () => {
  const card = dpl.termsCard({ reply: 'Clause 1 cannot be offered.', refused: true, proposal: null, terms: null }, { act: () => {}, onBack: () => {} });
  assert.match(words(card), /Clause 1 cannot be offered\./);
  assert.equal(buttons(card, 'Sign and send').length, 0);
});

// --- Rule 4: what needs you ------------------------------------------------------------------

const OFFER_ITEM = {
  id: OFFER_ID, kind: 'Offer', issuer: 'Ostmark', text: 'Ostmark offers an agreement. Parties: Ostmark, Norra.',
  issued: '2 April 1900', deadline: '6 April 1900', cause: null, options: [], plan: [], actions: [],
};
const VOTE_ITEM = {
  id: 'commission', kind: 'Vote', issuer: 'Norra', text: 'Norra calls a conference of Norra, Sudland, Ostmark: A standing commission for the strait.',
  issued: '14 April 1900', deadline: '18 April 1900', cause: null, options: [], plan: [], actions: [],
};

test('an offer aimed at the seat is one line in what needs you, with its due day, that opens its answer', () => {
  const rv = seat((x) => { x.agenda.items = [OFFER_ITEM]; });
  const lines = needs.needLines(rv).filter((l) => l.key === OFFER_ID);
  assert.equal(lines.length, 1, 'listed once');
  const [line] = lines;
  assert.equal(line.kind, 'offer');
  assert.equal(line.label, 'Offer of agreement');
  assert.equal(line.due, '6 April 1900');
  assert.deepEqual(line.action, { word: 'Answer', to: 'matter', id: OFFER_ID });
});

test('an offer is answered with Accept or Decline, and the answer goes out on its due day', () => {
  assert.equal(requestChoices('free', OFFER_ITEM).kind, 'request');
  const { calls, act } = recorder();
  const panel = needsAnswer({ style: 'free', items: [OFFER_ITEM] }, { act, today: '1900-04-03' });
  assert.match(words(panel), new RegExp(ANSWER_AT_CLOSE.replace(/[.;]/g, '.')));
  buttons(panel, 'Accept')[0].click();
  assert.deepEqual(calls.map((c) => [c.action, c.body]), [['answer', { item: OFFER_ID, accept: true }]]);
});

test('a conference the seat votes in is a line with its voting day that opens the diplomacy sheet', () => {
  const rv = seat((x) => { x.agenda.items = [VOTE_ITEM]; });
  const lines = needs.needLines(rv).filter((l) => l.key === 'commission');
  assert.equal(lines.length, 1);
  assert.equal(lines[0].label, 'Conference vote');
  assert.equal(lines[0].due, '18 April 1900');
  assert.deepEqual(lines[0].action, { word: 'Vote', to: 'sheet', sheet: 'diplomacy' });
});

test('on the desk a conference vote is For, Against or Abstain, sealed until the tally', () => {
  assert.equal(requestChoices('free', VOTE_ITEM).kind, 'vote');
  const { calls, act } = recorder();
  const panel = needsAnswer({ style: 'free', items: [VOTE_ITEM] }, { act, today: '1900-04-14' });
  assert.match(words(panel), /No one sees your vote before the tally/);
  buttons(panel, 'For')[0].click();
  assert.deepEqual(calls.map((c) => [c.action, c.body]), [['conference-vote', { conference: 'commission', vote: 'for' }]]);
});

// --- Rule 5: the conference sheet ------------------------------------------------------------

test('the conference sheet calls a conference: its text, the nations invited, the voting day and whether it is public', () => {
  const rv = seat();
  const { calls, act } = recorder();
  const draft = dpl.freshCall();
  const el = dpl.conferencesSection(rv, draft, { act });
  const form = el.querySelector('form.rl-dp-call');
  const text = form.querySelector('textarea');
  text.value = 'A toll-free strait.';
  fire(text, 'input');
  const sud = form.querySelectorAll('input[type="checkbox"]').find((i) => i.value === SUDLAND);
  sud.checked = true;
  fire(sud, 'change');
  const day = form.querySelector('input[type="date"]');
  assert.equal(day.value, '1900-04-18', 'the earliest voting day by default');
  const pub = form.querySelectorAll('input[type="checkbox"]').find((i) => i.getAttribute('name') === 'public');
  pub.checked = true;
  fire(pub, 'change');
  fire(form, 'submit');
  assert.deepEqual(calls.map((c) => [c.action, c.body]), [['conference-call', {
    text: 'A toll-free strait.', invited: [SUDLAND], voting_day: '1900-04-18', public: true,
  }]]);
});

test('an open conference shows its text, the invited, the voting day and the seat\'s own sealed vote, and takes a vote', () => {
  const { calls, act } = recorder();
  const el = dpl.conferencesSection(seat(), dpl.freshCall(), { act });
  const conf = conferenceOf(el, 'commission');
  const said = words(conf);
  assert.match(said, /A standing commission for the strait\./);
  assert.match(said, /Invited: Norra, Sudland, Ostmark/);
  assert.match(said, /Votes on 18 April 1900/);
  assert.match(said, /Your vote, sealed until the tally: Abstain/);
  assert.match(said, /Norra: no war declared on Vesta/);
  assert.equal(buttons(conf, 'Abstain')[0].getAttribute('aria-pressed'), 'true');
  assert.equal(buttons(conf, 'For')[0].getAttribute('aria-pressed'), 'false');
  assert.match(said, /To replace your vote, vote again before this wake closes/);
  buttons(conf, 'Against')[0].click();
  assert.deepEqual(calls.map((c) => [c.action, c.body]), [['conference-vote', { conference: 'commission', vote: 'against' }]]);
});

test('a vote sealed in an earlier wake stands: no buttons, and it says so', () => {
  const rv = seat((x) => { x.conferences.conferences[1].can_vote = false; });
  const conf = conferenceOf(dpl.conferencesSection(rv, dpl.freshCall(), recorder()), 'commission');
  assert.equal(conf.querySelectorAll('.rl-dp-vote button').length, 0);
  assert.match(words(conf), /Your vote, sealed until the tally: Abstain/);
});

test('after the tally: the result, an agreement or a resolution, and each nation\'s counted vote', () => {
  const result = (r) => {
    const rv = seat((x) => { x.conferences.conferences[0].result = r; });
    return words(conferenceOf(dpl.conferencesSection(rv, dpl.freshCall(), recorder()), 'charter').querySelector('.rl-dp-result'));
  };
  assert.match(result('agreement'), /Passed: an agreement among Norra and Ostmark/);
  assert.match(result('resolution'), /Passed as a resolution that binds no one/);
  assert.match(result('failed'), /Not passed/);
  assert.match(result('cancelled'), /Cancelled: too few nations voted/);
  const conf = conferenceOf(dpl.conferencesSection(seat(), dpl.freshCall(), recorder()), 'charter');
  assert.deepEqual(conf.querySelectorAll('.rl-dp-votes li').map(words), ['Norra: For', 'Sudland: Abstain', 'Ostmark: For']);
  assert.match(words(conf), /Tallied 11 April 1900/);
  assert.equal(conf.querySelectorAll('.rl-dp-vote button').length, 0);
});

test('no other nation\'s vote is drawn before the tally, even if one reaches the client', () => {
  const rv = seat((x) => { x.conferences.conferences[1].votes = [{ nation: 'Sudland', vote: 'for' }]; });
  const conf = conferenceOf(dpl.conferencesSection(rv, dpl.freshCall(), recorder()), 'commission');
  assert.doesNotMatch(words(conf), /Sudland: For/);
  assert.equal(conf.querySelector('.rl-dp-votes'), null);
});

// --- Rule 6: Publish --------------------------------------------------------------------------

test('an agreement the seat is party to has Publish, which files agreement-publish', () => {
  const { calls, act } = recorder();
  const el = dpl.agreementsSection(withPact(seat()).agreements, { act });
  buttons(agreementOf(el, 'agr-0'), 'Publish')[0].click();
  assert.deepEqual(calls.map((c) => [c.action, c.body]), [['agreement-publish', { agreement: 'agr-0' }]]);
  assert.equal(buttons(agreementOf(el, 'pact-1'), 'Publish').length, 0, 'not a party: no Publish');
  assert.match(words(agreementOf(el, 'pact-1')), /Public since 1 April 1900/);
  const rv = seat((x) => { x.agreements.agreements[0].published = '1900-04-03'; });
  assert.equal(buttons(dpl.agreementsSection(rv.agreements, { act }), 'Publish').length, 0, 'published already: no Publish');
  const other = seat((x) => { x.agreements.agreements[0].party = false; });
  assert.equal(buttons(dpl.agreementsSection(other.agreements, { act }), 'Publish').length, 0, 'not a party, not public: no Publish');
});

// --- The room: the Diplomacy sheet ------------------------------------------------------------

const gameOf = (id, rv) => ({ id, name: 'Toy', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'Ilse Varg' } } });
const settle = () => new Promise((r) => setTimeout(r, 0));

async function room(rv) {
  const doc = installDom();
  setRoomLayout('map');
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
  uiFor(id);
  const ctx = { me, refresh: async () => doc.body.replaceChildren(realismRoom(ctx)), go: () => {} };
  const root = realismRoom(ctx);
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  await settle();
  await settle();
  return { root: () => doc.body.firstElementChild ?? root, calls };
}

/** Part `key` of World: World opened from the bar, then the part's own tab; undefined when World has no such part. */
const tabOf = (root, key) => {
  const world = root.querySelectorAll('.rl-sheettabs button').find((b) => b.getAttribute('data-group') === 'world');
  if (world && world.getAttribute('aria-expanded') !== 'true') world.click();
  return root.querySelectorAll('.rl-over .rl-parts button').find((b) => b.getAttribute('data-sheet') === key);
};

test('the map-first room has a Diplomacy sheet: the agreements, the offer builder and the conferences', async () => {
  const { root } = await room(seat());
  const tab = tabOf(root(), 'diplomacy');
  assert.ok(tab, 'the Diplomacy tab');
  tab.click();
  const sheet = root().querySelector('.rl-over');
  assert.equal(sheet.getAttribute('data-sheet'), 'diplomacy');
  assert.equal(words(sheet.querySelector('.rl-over-title')), 'World');
  for (const cls of ['rl-dp-agreements', 'rl-dp-builder', 'rl-dp-conferences']) assert.ok(sheet.querySelector(`.${cls}`), cls);
});

test('the offer builder\'s reading opens in the sheet, and signing it sends the file call', async () => {
  const { root, calls } = await room(seat());
  api.realism = async (action, body) => {
    calls.push([action, body]);
    if (action === 'agreement-offer') return reading();
    return { reply: 'Sent.', refused: false };
  };
  tabOf(root(), 'diplomacy').click();
  const sheet = () => root().querySelector('.rl-over');
  const text = sheet().querySelector('.rl-dp-builder textarea');
  text.value = 'Peace on the isle.';
  fire(text, 'input');
  const sud = sheet().querySelectorAll('.rl-dp-builder input[type="checkbox"]').find((i) => i.value === SUDLAND);
  sud.checked = true;
  fire(sud, 'change');
  buttons(sheet(), 'Read the terms')[0].click();
  await settle();
  await settle();
  assert.ok(sheet().querySelector('.rl-dp-terms'), 'the terms to sign');
  buttons(sheet(), 'Sign and send')[0].click();
  await settle();
  await settle();
  assert.deepEqual(calls.filter(([a]) => a === 'agreement-offer' || a === 'file').map(([a]) => a), ['agreement-offer', 'file']);
  assert.equal(sheet().querySelector('.rl-dp-terms'), null, 'signed: the builder is fresh again');
});

test('a game with neither agreements nor conferences has no Diplomacy tab', async () => {
  const { root } = await room(seat((x) => { delete x.agreements; delete x.conferences; }));
  assert.equal(tabOf(root(), 'diplomacy'), undefined);
});

test('a conference vote line opens the Diplomacy sheet', async () => {
  const { root } = await room(seat((x) => { x.agenda.items = [VOTE_ITEM]; }));
  const act = root().querySelectorAll('.rl-needs .rl-need-act').find((b) => b.getAttribute('data-need') === 'commission');
  act.click();
  assert.equal(root().querySelector('.rl-over').getAttribute('data-sheet'), 'diplomacy');
});
