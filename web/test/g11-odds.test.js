// The odds panel (ODC). "Odds" on the move chip and on the battle sheet opens a panel fed only by
// the `odds` action: whose picture it is (each report used, with its source, age and confidence),
// the outcome bar with its three shares and a text twin, the loss range for each side, the chance
// and the days to take the territory, the risk of being forced back and where to, and a table of
// the win share at each strength in the reported range. With no report it says the enemy is
// unknown and shows no figure. Never one headline number, and nothing filed by asking or closing.
// On a phone it is a half sheet; every figure is reachable by keyboard.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { theatreBoard, forgetShapes } = await import('../js/views/realism-theatre.js');
const { forgetMarks } = await import('../js/views/realism-territory.js');
const { battleSheet } = await import('../js/views/realism-battle.js');
const { oddsPanel, forgetOdds } = await import('../js/views/realism-odds.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const TMAP = fixture.territory_map;
const LEVY = 'The Norra Levy';
const TODAY = '1900-04-16';
const BANDS = /\b(impossible|long shot|contested|likely|assured)\b/i;

/** The report the fixture's spread was read from, as the seat's reports block gives it. */
const REPORT = {
  key: 'r1', kind: 'galley', kind_name: 'Sudland Levy', strength_low: 3, strength_high: 5,
  area: { key: 'sudland_coast', name: 'The Sudland Coast' }, bound_for: null, seen: '1900-04-13', source: 'air',
  person: 'Brann Hollis', confidence: 'B', document: 'd-r1', ring: ['sudland_coast'],
};

const MOVE = {
  name: 'move_piece', label: 'Move a piece', summary: 'Send a piece to another area.', pipeline: 'field_order',
  params: [
    { name: 'force', label: 'Which piece', kind: 'enum', lo: null, hi: null, places: [], choices: [
      { value: 'norra_levy', label: LEVY }, { value: 'norra_kites', label: 'The Norra Kites' }] },
    { name: 'to', label: 'To', kind: 'enum', lo: null, hi: null, places: [], choices: [
      { value: 'isle', label: 'The Isle' }, { value: 'sudland_coast', label: 'The Sudland Coast' },
      { value: 'the_gulf', label: 'The Gulf' }, { value: 'norra_hills', label: 'The Norra Hills' }] },
  ],
};

function seat(change = () => {}) {
  const map = structuredClone(TMAP);
  map.reports = [structuredClone(REPORT)];
  const rv = {
    ...structuredClone(fixture),
    map,
    battles: [structuredClone(fixture.battles[0])],
    desk: { ...fixture.desk, levers: [structuredClone(MOVE)] },
    court: { load_limit: 2, ring: [], chambers: [], paths: [{ id: 'field_order', name: 'A field order', forms: ['Move a piece'],
      steps: [{ person: 'P-ILSE', name: 'Ilse', office: 'Marshal of Norra', kind: 'decision', days: 1, you: false, orders: [] }] }] },
    clock: { ...fixture.clock, world_date: TODAY },
    orders: { orders: [] },
  };
  delete rv.locks; // a game with locks off: no move is checked (g20-locks.test.js)
  change(rv);
  return rv;
}

const SPREAD = () => structuredClone(fixture.spread);
const KNOWN = () => ({ reply: 'The odds as your own picture has them.', refused: false, odds: SPREAD() });
const UNKNOWN = () => ({
  reply: 'The odds as your own picture has them.', refused: false,
  odds: { ...SPREAD(), known: false, runs: 0, shares: null, own_lost: null, enemy_lost: null, taken: null, taken_days: null,
    forced_back: null, by_strength: [], reports: [] },
});

/** The `odds` calls the panel makes, answered with `answer(body)`; every other call is recorded too. */
function stubApi(answer = () => KNOWN()) {
  const calls = [];
  api.realism = async (action, body) => {
    if (action === 'map') return { reply: '', refused: false, file: TMAP.file, map: SHAPES };
    calls.push({ action, body });
    return action === 'odds' ? answer(body) : { reply: '', refused: false };
  };
  return calls;
}
const settle = async () => { for (let i = 0; i < 4; i += 1) await new Promise((ok) => setTimeout(ok, 0)); };

async function room(rv) {
  const acts = [];
  const ui = { piece: null, theatre: { mode: 'map', scope: 'reports' } };
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
    forgetOdds();
    r.draw();
    await settle();
  } finally { globalThis.fetch = was; }
  r.draw();
  return r;
}
/** An element's text with its cells and terms set apart by spaces, as a reader hears them. */
const spaced = (el) => el.querySelectorAll('dt, dd, th, td, p, h4, li').map(words).join(' ');
const button = (el, label) => el.querySelectorAll('button').find((b) => words(b) === label);
const panelOf = (el) => el.querySelector('.rl-odds');
const chipOf = (view) => view.querySelector('.rl-pup-chip');

async function chipToCoast() {
  const r = await room(seat());
  r.ui.piece = { kind: 'force', name: LEVY };
  r.draw();
  r.view.querySelectorAll('g.rl-map-target').find((g) => g.getAttribute('data-area') === 'sudland_coast').click();
  return r;
}

function battleRoom(change) {
  forgetOdds();
  const rv = seat(change);
  const acts = [];
  const host = document.createElement('div');
  const draw = () => host.replaceChildren(battleSheet(rv, 'sudland_coast', { act: (m, action, body) => acts.push({ action, body }), pick: () => {}, theatre: {} }));
  draw();
  document.body.append(host);
  return { rv, host, acts, draw };
}

const panel = (out, opts = {}) => oddsPanel(seat(), out, { what: 'The Norra Levy into The Sudland Coast', onClose: () => {}, ...opts });

// --- rule 1: Odds on the chip and on the battle sheet asks the odds action ----------------

test('the move chip has an Odds button that asks the odds action for the piece and the area, and opens the panel', async () => {
  const calls = stubApi();
  const r = await chipToCoast();
  const odds = button(chipOf(r.view), 'Odds');
  assert.ok(odds, 'the chip has Odds');
  assert.equal(panelOf(r.view), null, 'no panel until asked');
  odds.click();
  await settle();
  assert.deepEqual(calls, [{ action: 'odds', body: { force: 'norra_levy', to: 'sudland_coast' } }]);
  assert.ok(panelOf(r.view), 'the panel opens with the reply');
  assert.match(words(panelOf(r.view)), /84 in 100/);
});

test('the battle sheet has an Odds button that asks for the battle with the decision in force', async () => {
  const calls = stubApi();
  const b = battleRoom();
  button(b.host, 'Odds').click();
  await settle();
  assert.deepEqual(calls, [{ action: 'odds', body: { force: 'norra_levy', battle: 'sudland_coast', decision: 'press' } }]);
  assert.ok(panelOf(b.host));
});

test('a defender, or a side that has given its decision, is asked the odds of the decision in force', async () => {
  const calls = stubApi();
  const b = battleRoom((rv) => { Object.assign(rv.battles[0], { side: 'defender' }); });
  button(b.host, 'Odds').click();
  await settle();
  const c = battleRoom((rv) => { Object.assign(rv.battles[0], { decision: 'withdraw', decided: true }); });
  button(c.host, 'Odds').click();
  await settle();
  assert.deepEqual(calls.map((x) => x.body.decision), ['hold', 'withdraw']);
});

test('in the battle panel another decision is asked by its own button, and files nothing', async () => {
  const calls = stubApi();
  const b = battleRoom();
  button(b.host, 'Odds').click();
  await settle();
  const hold = panelOf(b.host).querySelectorAll('.rl-odds-if button').find((x) => words(x) === 'Hold');
  assert.ok(hold, 'Hold is offered');
  hold.click();
  await settle();
  assert.deepEqual(calls.map((c) => c.body.decision), ['press', 'hold']);
  assert.deepEqual(b.acts, []);
});

test('a battle the seat commands no piece in has no Odds button', () => {
  stubApi();
  const b = battleRoom((rv) => { rv.battles[0].pieces = []; });
  assert.equal(button(b.host, 'Odds'), undefined);
});

test('a panel still open shows again from the same reply when the sheet is drawn again, without asking twice', async () => {
  const calls = stubApi();
  const b = battleRoom();
  button(b.host, 'Odds').click();
  await settle();
  b.draw();
  assert.ok(panelOf(b.host), 'still open');
  assert.equal(calls.length, 1);
});

test('a new report or a new wake asks again rather than show the old reply', async () => {
  const calls = stubApi();
  const b = battleRoom();
  button(b.host, 'Odds').click();
  await settle();
  b.rv.map.reports.push({ ...structuredClone(REPORT), key: 'r9', seen: TODAY });
  b.draw();
  assert.equal(panelOf(b.host), null, 'the old panel is not shown over a new picture');
  button(b.host, 'Odds').click();
  await settle();
  assert.equal(calls.length, 2);
});

// --- rule 2: whose picture ---------------------------------------------------------------

test('the first line says whose picture it is: each report used, with its source, age and confidence', () => {
  const p = panel(KNOWN());
  const first = p.querySelector('.rl-odds-whose');
  assert.ok(first, 'whose picture');
  assert.equal(p.querySelector('.rl-odds-body').firstElementChild ?? p.querySelector('.rl-odds-body').children[0], first, 'it comes first');
  const said = words(first);
  assert.match(said, /Yours/);
  assert.match(said, /Brann Hollis \(Air search\)/);
  assert.match(said, /3 days ago/);
  assert.match(said, /probable/);
  assert.match(said, /strength 3 to 5/);
});

test('a report the reply used that the map no longer holds is named as such, not dropped', () => {
  const out = KNOWN();
  out.odds.reports = ['r1', 'gone'];
  const said = words(panel(out).querySelector('.rl-odds-whose'));
  assert.match(said, /2 reports/);
  assert.match(said, /a report no longer on your map/);
});

// --- rule 3: the spread ------------------------------------------------------------------

test('the outcome bar has the three shares, each with its word, and a text twin', () => {
  const p = panel(KNOWN());
  const bar = p.querySelector('.rl-odds-bar');
  assert.ok(bar);
  const segs = bar.querySelectorAll('.rl-odds-seg');
  assert.deepEqual(segs.map((s) => s.getAttribute('data-outcome')), ['win', 'loss'], 'a share of none draws no segment');
  assert.match(words(bar), /win 84/);
  assert.match(words(bar), /loss 16/);
  const twin = words(p.querySelector('.rl-odds-twin'));
  assert.match(twin, /In 100 runs/);
  assert.match(twin, /84 win/);
  assert.match(twin, /0 end with neither side through/);
  assert.match(twin, /16 lose/);
});

test('the loss range for each side, in steps', () => {
  const said = words(panel(KNOWN()).querySelector('.rl-odds-losses'));
  assert.match(said, /Yours: 0 to 3 steps/);
  assert.match(said, /Theirs: 1 to 3 steps/);
});

test('the chance and the days to take the territory, and the risk of being forced back and where to', () => {
  const said = spaced(panel(KNOWN()).querySelector('.rl-odds-take'));
  assert.match(said, /Chance 84 in 100/);
  assert.match(said, /When, if taken day 4 of the fighting, in half the runs that took it/);
  assert.match(said, /Forced back 16 in 100, to The Norra Hills/);
});

test('a battle with no territory to take says so, and nowhere to fall back to says so', () => {
  const out = KNOWN();
  Object.assign(out.odds, { taken: null, taken_days: null, back_to: null });
  const said = spaced(panel(out).querySelector('.rl-odds-take'));
  assert.match(said, /A win here takes no territory/);
  assert.match(said, /nowhere to fall back to/);
});

test('a table of the win share at each strength in the reported range', () => {
  const out = KNOWN();
  out.odds.by_strength.push({ strength: 6, win: null });
  const rows = panel(out).querySelectorAll('.rl-odds-table tbody tr').map(spaced);
  assert.deepEqual(rows, ['3 100 in 100', '4 93 in 100', '5 53 in 100', '6 no run drew it']);
});

test('the panel has no element marked as the answer: no verdict, no band word, no lone headline figure', () => {
  const p = panel(KNOWN());
  const all = (el) => [el, ...el.children.flatMap(all)];
  for (const el of all(p)) {
    assert.doesNotMatch(el.getAttribute('class') ?? '', /verdict|answer|headline|summary/, 'no answer element');
    assert.equal(el.getAttribute('data-answer'), null);
  }
  assert.doesNotMatch(words(p), BANDS);
  assert.doesNotMatch(words(p), /%/, 'shares read as so many in 100, beside their outcome');
  assert.equal(p.querySelectorAll('h4').length >= 4, true, 'the spread is in its sections');
});

// --- rule 4: no report, no figure -------------------------------------------------------

test('with no report it says the enemy is unknown, gives the terrain, and shows no figure', () => {
  const p = panel(UNKNOWN());
  const said = words(p);
  assert.match(said, /Nothing is known in The Sudland Coast\. No odds without a report\./);
  assert.match(said, /plain/);
  assert.equal(p.querySelector('.rl-odds-bar'), null);
  assert.equal(p.querySelector('.rl-odds-table'), null);
  assert.equal(p.querySelector('.rl-odds-losses'), null);
  assert.equal(p.querySelector('.rl-odds-take'), null);
  assert.doesNotMatch(said, /in 100|steps/);
});

test('a reply that says the enemy is unknown shows no figure even if figures came with it', () => {
  const out = UNKNOWN();
  out.odds.shares = { win: 50, stalemate: 0, loss: 50 };
  out.odds.by_strength = [{ strength: 2, win: 50 }];
  const p = panel(out);
  assert.equal(p.querySelector('.rl-odds-bar'), null);
  assert.doesNotMatch(words(p), /in 100/);
});

test('a busy or refused reply shows its words and Ask again, and no figure', async () => {
  let n = 0;
  const calls = stubApi(() => (n++ === 0 ? { reply: 'The odds desk is busy just now. Ask again in a moment.', refused: true, busy: true } : KNOWN()));
  const b = battleRoom();
  button(b.host, 'Odds').click();
  await settle();
  assert.match(words(panelOf(b.host)), /busy just now/);
  assert.doesNotMatch(words(panelOf(b.host)), /in 100/);
  button(panelOf(b.host), 'Ask again').click();
  await settle();
  assert.equal(calls.length, 2);
  assert.match(words(panelOf(b.host)), /84 in 100/);
});

// --- rule 5: closing changes nothing ------------------------------------------------------

test('closing the panel files nothing and leaves the chip as it was; Send it still files the move', async () => {
  const calls = stubApi();
  const r = await chipToCoast();
  const odds = button(chipOf(r.view), 'Odds');
  odds.click();
  await settle();
  button(panelOf(r.view), 'Close').click();
  assert.equal(panelOf(r.view), null);
  assert.deepEqual(r.acts, [], 'nothing filed');
  assert.deepEqual(calls.map((c) => c.action), ['odds']);
  assert.equal(document.activeElement, odds, 'focus back on Odds');
  assert.ok(chipOf(r.view), 'the chip stays');
  button(chipOf(r.view), 'Send it').click();
  assert.deepEqual(r.acts.map((a) => a.action), ['lever']);
});

test('Escape in the panel closes it the same way', async () => {
  stubApi();
  const b = battleRoom();
  const odds = button(b.host, 'Odds');
  odds.click();
  await settle();
  panelOf(b.host).dispatchEvent({ type: 'keydown', key: 'Escape', preventDefault() {}, stopPropagation() {} });
  assert.equal(panelOf(b.host), null);
  assert.deepEqual(b.acts, []);
  assert.equal(document.activeElement, odds);
});

test('the panel says that closing it files nothing, and has no button that files', () => {
  const p = panel(KNOWN());
  assert.match(words(p), /Closing this files nothing/);
  const labels = p.querySelectorAll('button').map(words);
  for (const l of labels) assert.doesNotMatch(l, /send|file|confirm|order/i);
});

// --- rule 6: a half sheet on a phone; every figure by keyboard -------------------------------

test('the panel is a labelled dialog whose body takes keyboard focus, so every figure can be reached and scrolled', async () => {
  stubApi();
  const b = battleRoom();
  button(b.host, 'Odds').click();
  await settle();
  const p = panelOf(b.host);
  assert.equal(p.getAttribute('role'), 'dialog');
  assert.equal(p.getAttribute('aria-labelledby'), p.querySelector('h3').getAttribute('id'));
  const body = p.querySelector('.rl-odds-body');
  assert.equal(body.getAttribute('tabindex'), '0');
  assert.ok(body.getAttribute('aria-label'));
  assert.equal(document.activeElement, p.querySelector('h3'), 'focus goes to the panel on open');
  assert.ok(body.querySelector('.rl-odds-table'), 'the table is inside the focusable body');
});

test('on a phone the panel is a half sheet from the bottom; the styles use the theme\'s tokens only', () => {
  const read = (f) => readFileSync(new URL(`../${f}`, import.meta.url), 'utf8');
  assert.match(read('index.html'), /<link rel="stylesheet" href="\/css\/c-odds\.css">/);
  const css = read('css/c-odds.css');
  assert.equal(css.match(/#[0-9a-fA-F]{3,8}\b|rgba?\(/g), null, 'no raw colour');
  const phone = css.split('@media (max-width: 600px)')[1] ?? '';
  assert.match(phone, /\.rl-odds \{[^}]*position: fixed/);
  assert.match(phone, /\.rl-odds \{[^}]*bottom: 0/);
  assert.match(phone, /\.rl-odds \{[^}]*max-height: 60vh/);
  assert.match(css, /\.rl-odds button \{[^}]*min-height: 44px/);
});

test('in the bar each share carries its word, and a loss also a hatch, never colour alone', () => {
  const out = KNOWN();
  out.odds.shares = { win: 50, stalemate: 20, loss: 30 };
  const bar = panel(out).querySelector('.rl-odds-bar');
  const segs = bar.querySelectorAll('.rl-odds-seg');
  assert.deepEqual(segs.map((s) => s.getAttribute('data-outcome')), ['win', 'stalemate', 'loss']);
  const hatch = bar.querySelector('pattern');
  assert.ok(hatch, 'a hatch pattern');
  assert.equal(segs[2].getAttribute('fill'), `url(#${hatch.getAttribute('id')})`);
  assert.deepEqual(bar.querySelectorAll('.rl-odds-key').map(words), ['win 50', 'stalemate 20', 'loss 30']);
});

// --- rule 7: the design rule -------------------------------------------------------------

test('the web design rule on odds says they are a spread from the seat\'s own picture, asked before filing', () => {
  const doc = readFileSync(new URL('../../docs/web-design/README.md', import.meta.url), 'utf8');
  const rule = doc.split('\n').find((l) => l.startsWith('4. '));
  assert.doesNotMatch(rule, /shown after filing|bands \(Impossible/);
  assert.match(rule, /spread/);
  assert.match(rule, /own picture/);
  assert.match(rule, /never one headline figure/i);
  assert.match(rule, /files nothing/);
});
