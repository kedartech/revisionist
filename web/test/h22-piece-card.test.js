// The piece's card (KPB), one test or more per rule: 1. a piece's sheet opens on its card: the
// picture, the kind's name, the five figures as five-step meters, and under them what is changing
// each one here, a line each with its direction and its cause; 2. with a piece picked, each lit
// area shows the days the step would take there, and tapping one shows the figures as they would
// stand there beside the figures now; 3. the odds panel names the kinds on each side as the seat
// knows them and shows which cause moved the odds most; 4. a region's weather this month and next
// is one line on the card, with what it does to this kind; 5. an enemy report's sheet shows its
// kind's picture and name only when the report names it, with the source and age.
// Keeps: the client works out no figure (each step, cause and day is the server's); an enemy's
// card shows only its report; with the switches off the sheets are as today.
// Mutants: a figure drawn for an enemy; a cause with no figure.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { api } = await import('../js/api.js');
const { piecePanel } = await import('../js/views/realism-board.js');
const { theatreBoard, forgetShapes } = await import('../js/views/realism-theatre.js');
const { forgetMarks } = await import('../js/views/realism-territory.js');
const { oddsPanel, forgetOdds } = await import('../js/views/realism-odds.js');
const { reportSheet } = await import('../js/views/realism-reports.js');
const { realismRoom } = await import('../js/views/realism-room.js');
const { setRoomLayout } = await import('../js/views/realism-sheets.js');
const piece = await import('../js/views/realism-piece.js');

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const fixture = JSON.parse(read('./fixtures/realism-seat.json'));
const SHAPES = JSON.parse(read('./fixtures/toy.map.json'));
const TMAP = fixture.territory_map;
const LEVY = 'The Norra Levy';
const KITES = 'The Norra Kites';
const TODAY = '1900-10-16';

/** The Levy's kind and figures as the server sends them with `kinds_in_battle` on. */
const LEVY_KIND = () => ({
  key: 'levy', name: 'Levy', picture: 'infantry',
  figures: { attack: 3, defence: 3, speed: 2, reach: 1, hidden: 2 },
  here: { attack: 3, defence: 4, speed: 1, reach: 1, hidden: 2 },
  changes: [
    { figure: 'defence', direction: 'up', cause: 'terrain', words: 'Hills' },
    { figure: 'speed', direction: 'down', cause: 'weather', words: 'Autumn mud' },
  ],
});
const KITE_KIND = () => ({
  key: 'kite_wing', name: 'Kite Wing', picture: 'fighters',
  figures: { attack: 2, defence: 2, speed: 5, reach: 3, hidden: 1 },
  here: { attack: 2, defence: 2, speed: 5, reach: 3, hidden: 1 }, changes: [],
});
/** The Levy's move to the Sudland Coast as it would stand there: the server's own figures and causes. */
const THERE = () => ({
  figures: { attack: 2, defence: 3, speed: 1, reach: 1, hidden: 2 },
  changes: [
    { figure: 'attack', direction: 'down', cause: 'enemy_kind', words: 'Galley' },
    { figure: 'speed', direction: 'down', cause: 'weather', words: 'Autumn mud' },
  ],
});
/** The weather block: every region this month and next, and what each does to the seat's own kinds. */
const WEATHER = () => ({
  month: 'oct', next_month: 'nov',
  regions: [
    { region: 'mainland', now: 'clear', next: 'clear' }, { region: 'north', now: 'mud', next: 'frost' },
    { region: 'south', now: 'clear', next: 'clear' }, { region: 'waters', now: null, next: null },
  ],
  kinds: [
    { key: 'clear', name: 'Clear', does: [] },
    { key: 'mud', name: 'Autumn mud', does: [
      { kind: 'levy', figure: 'speed', direction: 'down', terrain: ['plain', 'forest'] },
      { kind: 'kite_wing', figure: 'reach', direction: 'down', terrain: [] },
    ] },
    { key: 'frost', name: 'Frost', does: [{ kind: 'kite_wing', figure: 'attack', direction: 'down', terrain: [] }] },
  ],
});
/** A report of an enemy galley, as KPC's reports block sends it with the switch on. */
const GALLEY = () => ({
  key: 'r-galley', kind: 'galley', kind_name: 'Galley', picture: 'battle_fleet', strength_low: 2, strength_high: 3,
  area: { key: 'sudland_coast', name: 'The Sudland Coast' }, bound_for: null, seen: '1900-10-13', source: 'air',
  person: 'Brann Hollis', confidence: 'B', document: 'd-r1', ring: null,
});
/** A report that names no kind: the server sends no picture for it. */
const UNNAMED = () => ({
  ...GALLEY(), key: 'r-unknown', kind: null, kind_name: 'unknown', seen: '1900-10-15', source: 'patrol', person: 'Ilse', document: null,
});

const MOVE = {
  name: 'move_piece', label: 'Move a piece', summary: 'Send a piece to another area.', pipeline: 'field_order',
  params: [
    { name: 'force', label: 'Which piece', kind: 'enum', lo: null, hi: null, places: [], choices: [
      { value: 'norra_levy', label: LEVY }, { value: 'norra_kites', label: KITES }] },
    { name: 'to', label: 'To', kind: 'enum', lo: null, hi: null, places: [], choices: [
      { value: 'isle', label: 'The Isle' }, { value: 'sudland_coast', label: 'The Sudland Coast' },
      { value: 'the_gulf', label: 'The Gulf' }, { value: 'open_sea', label: 'The Open Sea' }] },
  ],
};

/** The seat's view of the toy map, with the three piece switches on unless `off`. */
function seat({ off = false, change = () => {} } = {}) {
  const map = structuredClone(TMAP);
  const unnamed = UNNAMED();
  delete unnamed.picture;
  map.reports = [GALLEY(), unnamed];
  if (!off) {
    const levy = map.marks.find((m) => m.name === LEVY).piece;
    levy.figures = LEVY_KIND();
    for (const mv of levy.moves) Object.assign(mv, mv.area.key === 'sudland_coast' ? THERE() : { figures: { ...LEVY_KIND().here }, changes: [] });
    map.marks.find((m) => m.name === KITES).piece.figures = KITE_KIND();
    map.weather = WEATHER();
  }
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
  delete rv.locks;
  change(rv);
  return rv;
}

const settle = async () => { for (let i = 0; i < 4; i += 1) await new Promise((ok) => setTimeout(ok, 0)); };
const panelFor = (rv, name) => piecePanel(rv, { kind: 'force', name }, () => {}, { pick: () => {}, act: () => {} });
const cardOf = (el) => el.querySelector('.rl-pc-card');
const metersOf = (el) => el.querySelectorAll('.rl-pc-meter');
const label = (el) => el.getAttribute('aria-label');
const onSteps = (meter) => meter.querySelectorAll('.rl-mark-step').filter((s) => s.classList.contains('on')).length;

/** The theatre with the Levy picked; `area` taps a lit area. Answers the map call with the toy shapes. */
async function theatre(rv, area = null) {
  const ui = { piece: null, theatre: { mode: 'map', scope: 'reports' } };
  const was = globalThis.fetch;
  globalThis.fetch = async (url) => ({ ok: true, status: 200, json: async () => (url === '/api/realism/map' ? { reply: '', refused: false, file: TMAP.file, map: SHAPES } : {}) });
  let view = null;
  const draw = () => {
    view?.remove();
    view = theatreBoard(rv, ui, { pick: (p) => { if (p.theatre) ui.theatre = p.theatre; if (p.piece !== undefined) ui.piece = p.piece; draw(); }, act: () => {} });
    document.body.append(view);
  };
  try {
    forgetShapes();
    forgetMarks();
    forgetOdds();
    draw();
    await settle();
  } finally { globalThis.fetch = was; }
  ui.piece = { kind: 'force', name: LEVY };
  draw();
  if (area) view.querySelectorAll('g.rl-map-target').find((g) => g.getAttribute('data-area') === area).click();
  return view;
}

// --- rule 1: the sheet opens on the card ---------------------------------------------------

test('an own piece\'s sheet opens on its card: the picture, the kind\'s name and five meters', () => {
  const panel = panelFor(seat(), LEVY);
  const card = cardOf(panel);
  assert.ok(card, 'the card is drawn');
  const after = panel.children.filter((c) => !c.classList.contains('rl-sheet-close') && c.tagName !== 'H2');
  assert.equal(after[0], card, 'the card comes first, under the piece\'s name');
  assert.ok(card.querySelector('[data-picture="infantry"]'), 'the kind\'s picture');
  assert.match(words(card.querySelector('.rl-pc-kind')), /^Levy\b/);
  assert.deepEqual(metersOf(card).map((m) => m.getAttribute('data-figure')), ['attack', 'defence', 'speed', 'reach', 'hidden']);
});

test('each meter is five steps, as many on as the server\'s figure here, the kind\'s own beside it', () => {
  const card = cardOf(panelFor(seat(), LEVY));
  const [attack, defence, speed] = metersOf(card);
  assert.equal(attack.querySelectorAll('.rl-mark-step').length, 5);
  assert.deepEqual([attack, defence, speed].map(onSteps), [3, 4, 1]);
  assert.equal(label(attack), 'Attack: 3 of 5');
  assert.equal(label(defence), 'Defence: 4 of 5 here, 3 for its kind');
  assert.equal(label(speed), 'Speed: 1 of 5 here, 2 for its kind');
  assert.equal(speed.querySelectorAll('.rl-pc-lost').length, 1, 'the step the speed lost here is drawn apart');
  assert.equal(defence.querySelectorAll('.rl-pc-gained').length, 1, 'the step the defence gained here is drawn apart');
  assert.equal(words(speed.querySelector('.rl-mark-num')), '1', 'the number on the mark');
});

test('under the meters, a line for each change: its figure, its direction and its cause, in the server\'s order', () => {
  const card = cardOf(panelFor(seat(), LEVY));
  const lines = card.querySelectorAll('.rl-pc-changes li');
  assert.deepEqual(lines.map(words), ['Defence up: the ground (Hills)', 'Speed down: the weather (Autumn mud)']);
  assert.deepEqual(lines.map((l) => [l.getAttribute('data-figure'), l.getAttribute('data-direction'), l.getAttribute('data-cause')]),
    [['defence', 'up', 'terrain'], ['speed', 'down', 'weather']]);
});

test('a cause is never drawn without the figure it changes (mutant: a cause with no figure)', () => {
  const rv = seat();
  rv.map.marks.find((m) => m.name === LEVY).piece.figures.changes = [
    { figure: 'attack', direction: 'up', cause: 'air_cover', words: 'air cover' },
    { figure: 'hidden', direction: 'down', cause: 'out_of_supply', words: 'out of supply' },
  ];
  const lines = cardOf(panelFor(rv, LEVY)).querySelectorAll('.rl-pc-changes li');
  assert.deepEqual(lines.map(words), ['Attack up: air cover', 'Hidden down: out of supply']);
  for (const l of lines) assert.match(words(l), /^(Attack|Defence|Speed|Reach|Hidden) (up|down): /);
});

test('a change that names no figure the card knows is not drawn', () => {
  const rv = seat();
  rv.map.marks.find((m) => m.name === LEVY).piece.figures.changes = [
    { direction: 'down', cause: 'weather', words: 'Autumn mud' },
    { figure: 'morale', direction: 'down', cause: 'out_of_supply', words: 'out of supply' },
    { figure: 'speed', direction: 'down', cause: 'weather', words: 'Autumn mud' },
  ];
  assert.deepEqual(cardOf(panelFor(rv, LEVY)).querySelectorAll('.rl-pc-changes li').map(words), ['Speed down: the weather (Autumn mud)']);
});

test('a piece with nothing changing it here says so under its meters', () => {
  const card = cardOf(panelFor(seat(), KITES));
  assert.equal(card.querySelectorAll('.rl-pc-changes li').length, 0);
  assert.equal(words(card.querySelector('.rl-pc-none')), 'Nothing here changes its figures.');
});

test('the card works out no figure: a figure the server did not send is not drawn', () => {
  const rv = seat();
  delete rv.map.marks.find((m) => m.name === LEVY).piece.figures.here.hidden;
  const card = cardOf(panelFor(rv, LEVY));
  assert.deepEqual(metersOf(card).map((m) => m.getAttribute('data-figure')), ['attack', 'defence', 'speed', 'reach']);
});

test('an enemy\'s sheet draws no figure, even where its mark carries one (mutant: a figure drawn for an enemy)', () => {
  const rv = seat();
  rv.map.marks.push({
    key: 'm-sud', name: 'Sudland Levy', kind: 'army', side: 'other', side_name: 'Sudland', certainty: 'reported',
    places: [], area: null, reported: '1900-10-10', source: 'Ilse', document: 'd-1', strength: 3,
    piece: { ...structuredClone(rv.map.marks.find((m) => m.name === LEVY).piece) },
  });
  const panel = panelFor(rv, 'Sudland Levy');
  assert.equal(cardOf(panel), null);
  assert.equal(metersOf(panel).length, 0);
});

test('with the switches off an own piece\'s sheet is as today: no card', () => {
  const panel = panelFor(seat({ off: true }), LEVY);
  assert.equal(cardOf(panel), null);
  assert.ok(panel.querySelector('dl'), 'today\'s rows stay');
});

test('in the map-first room a force\'s sheet opens on its card', async () => {
  const doc = installDom();
  setRoomLayout('map');
  forgetShapes();
  api.realism = async (action) => (action === 'map' ? { reply: '', refused: false, file: TMAP.file, map: SHAPES } : {});
  api.catchup = async () => ({});
  api.game = async () => ({ reply: '', leaders: [] });
  const rv = { ...seat(), documents: fixture.listing, wake_tick: 1 };
  const me = { account: { handle: 'josh' }, game: { id: 'g-kpb', name: 'Toy', ruleset: 'realism', phase: 'play', host: true, view: { realism: rv, seat: { name: 'Ilse' } } } };
  const ctx = { me, refresh: async () => {}, go: () => {} };
  const root = realismRoom(ctx);
  Object.getPrototypeOf(root).scrollIntoView ??= function scrollIntoView() {};
  doc.body.append(root);
  await settle();
  const find = () => root.querySelectorAll('.rl-mapfirst g[data-stack]').find((m) => (m.getAttribute('aria-label') ?? '').startsWith(LEVY));
  if (!find()) root.querySelectorAll('.rl-mapfirst g[data-count]').find((g) => (g.getAttribute('aria-label') ?? '').includes(LEVY))?.click();
  find().click();
  const sheet = root.querySelector('.rl-over');
  assert.equal(sheet.getAttribute('data-sheet'), 'piece');
  const panel = sheet.querySelector('.rl-piece');
  assert.equal(panel.children[0], cardOf(panel), 'the card first in the sheet');
  setRoomLayout(null);
});

// --- rule 2: the lit areas' days, and a lit area's figures beside the figures now -------------

test('each lit area shows the days its step would take, as the server counts them with the weather', async () => {
  const rv = seat();
  const levy = rv.map.marks.find((m) => m.name === LEVY).piece;
  levy.moves.find((mv) => mv.area.key === 'sudland_coast').days = 9;
  const view = await theatre(rv);
  const coast = view.querySelectorAll('g.rl-map-target').find((g) => g.getAttribute('data-area') === 'sudland_coast');
  assert.match(words(coast), /\b9 days\b/);
});

test('tapping a lit area shows the figures as they would stand there beside the figures now', async () => {
  const view = await theatre(seat(), 'sudland_coast');
  const box = view.querySelector('.rl-pup-chip .rl-pc-there');
  assert.ok(box, 'the comparison is on the chip');
  assert.match(words(box.querySelector('h4')), /The Sudland Coast/);
  const rows = box.querySelectorAll('.rl-pc-row');
  assert.deepEqual(rows.map((r) => r.getAttribute('data-figure')), ['attack', 'defence', 'speed', 'reach', 'hidden']);
  const attack = rows[0];
  const [now, there] = metersOf(attack);
  assert.equal(label(now), 'Attack now: 3 of 5');
  assert.equal(label(there), 'Attack in The Sudland Coast: 2 of 5, 3 now');
  assert.deepEqual([onSteps(now), onSteps(there)], [3, 2]);
  assert.deepEqual(box.querySelectorAll('.rl-pc-changes li').map(words), ['Attack down: an enemy kind reported there (Galley)', 'Speed down: the weather (Autumn mud)']);
});

test('a lit area the server sent no figures for has no comparison: none is worked out', async () => {
  const rv = seat();
  const coast = rv.map.marks.find((m) => m.name === LEVY).piece.moves.find((mv) => mv.area.key === 'sudland_coast');
  delete coast.figures;
  delete coast.changes;
  const view = await theatre(rv, 'sudland_coast');
  assert.ok(view.querySelector('.rl-pup-chip'), 'the chip opens');
  assert.equal(view.querySelector('.rl-pc-there'), null);
});

test('with the switches off the chip has no comparison', async () => {
  const view = await theatre(seat({ off: true }), 'sudland_coast');
  assert.ok(view.querySelector('.rl-pup-chip'), 'the chip opens');
  assert.equal(view.querySelector('.rl-pc-there'), null);
});

// --- rule 3: the odds name the kinds on each side and the cause that moved them most ---------

const ODDS = (extra = {}) => ({
  reply: 'The odds as your own picture has them.', refused: false,
  odds: { ...structuredClone(fixture.spread), reports: ['r-galley', 'r-unknown'], moved_by: { cause: 'weather', words: 'Autumn mud', direction: 'against' }, ...extra },
});
const oddsFor = (out, body = { force: 'norra_levy', to: 'sudland_coast' }, rv = seat()) => oddsPanel(rv, out, { what: 'The Norra Levy into The Sudland Coast', onClose: () => {}, body });

test('the odds name the kinds on each side as the seat knows them: its own, and each report\'s or its domain\'s', () => {
  const panel = oddsFor(ODDS());
  const sides = panel.querySelector('.rl-odds-kinds');
  assert.ok(sides, 'a section names the kinds');
  assert.deepEqual(sides.querySelectorAll('.rl-odds-yours li').map(words), ['Levy: The Norra Levy']);
  assert.deepEqual(sides.querySelectorAll('.rl-odds-theirs li').map(words), ['Galley, as reported', 'A land piece, its kind not reported']);
  assert.ok(sides.querySelector('.rl-odds-yours [data-picture="infantry"]'), 'your kind\'s picture');
  assert.ok(sides.querySelector('.rl-odds-theirs [data-picture="battle_fleet"]'), 'the named report\'s picture');
  assert.equal(sides.querySelectorAll('.rl-odds-theirs [data-picture]').length, 1, 'no picture for a report naming no kind');
});

test('the odds for a battle name every piece of the seat\'s side in it', () => {
  const rv = seat();
  rv.battles[0].pieces.push({ force: 'norra_kites', name: KITES, strength: 2, contingency: null });
  const panel = oddsFor(ODDS(), { force: 'norra_levy', battle: 'sudland_coast', decision: 'press' }, rv);
  assert.deepEqual(panel.querySelectorAll('.rl-odds-yours li').map(words), ['Kite Wing: The Norra Kites', 'Levy: The Norra Levy']);
});

test('with no report the odds name no enemy kind: their side is not reported', () => {
  const panel = oddsFor(ODDS({ reports: [] }));
  assert.deepEqual(panel.querySelectorAll('.rl-odds-theirs li').map(words), ['None reported: their kind is not known']);
  assert.equal(panel.querySelectorAll('.rl-odds-theirs [data-picture]').length, 0);
});

test('the odds show which cause moved them most, and which way', () => {
  const line = oddsFor(ODDS()).querySelector('.rl-odds-moved');
  assert.equal(words(line), 'Moved most by the weather (Autumn mud), against you');
  assert.equal(words(oddsFor(ODDS({ moved_by: { cause: 'air_cover', words: 'air cover', direction: 'for' } })).querySelector('.rl-odds-moved')),
    'Moved most by air cover, for you');
  assert.equal(words(oddsFor(ODDS({ moved_by: null })).querySelector('.rl-odds-moved')), 'No one cause here moves the odds');
});

test('odds sent with the kinds switch off are drawn as today: no kinds, no cause', () => {
  const out = ODDS();
  delete out.odds.moved_by;
  const panel = oddsFor(out);
  assert.equal(panel.querySelector('.rl-odds-kinds'), null);
  assert.equal(panel.querySelector('.rl-odds-moved'), null);
});

// --- rule 4: the weather line ---------------------------------------------------------------

test('the card carries one weather line: the region\'s weather this month and next, and what it does to this kind', () => {
  const line = cardOf(panelFor(seat(), LEVY)).querySelectorAll('.rl-pc-weather');
  assert.equal(line.length, 1);
  assert.equal(words(line[0]), 'Weather in The North: Autumn mud in October, Frost in November. Autumn mud: speed down on plain and forest. Frost: nothing to a Levy.');
});

test('what the weather does is this kind\'s alone', () => {
  const line = words(cardOf(panelFor(seat(), KITES)).querySelector('.rl-pc-weather'));
  assert.equal(line, 'Weather in The North: Autumn mud in October, Frost in November. Autumn mud: reach down. Frost: attack down.');
});

test('a region the table does not reach takes its parent\'s row, and a region with none says so', () => {
  const rv = seat();
  rv.map.weather.regions = rv.map.weather.regions.filter((r) => r.region !== 'north');
  assert.match(words(cardOf(panelFor(rv, LEVY)).querySelector('.rl-pc-weather')), /^Weather in The Mainland: Clear in October, Clear in November\./);
  rv.map.weather.regions = [];
  assert.equal(words(cardOf(panelFor(rv, LEVY)).querySelector('.rl-pc-weather')), 'Weather in The North: none given.');
});

test('with the weather off the card has no weather line', () => {
  const rv = seat();
  delete rv.map.weather;
  assert.equal(cardOf(panelFor(rv, LEVY)).querySelector('.rl-pc-weather'), null);
});

// --- rule 5: an enemy report's sheet ----------------------------------------------------------

const sheetOf = (rv, key) => reportSheet(rv.map, key, { today: TODAY });

test('a report that names its kind shows the kind\'s picture and name, with the source and age', () => {
  const head = sheetOf(seat(), 'r-galley').querySelector('.rl-pc-report');
  assert.ok(head);
  assert.ok(head.querySelector('[data-picture="battle_fleet"]'));
  assert.equal(words(head.querySelector('.rl-pc-kind')), 'Galley');
  assert.equal(words(head.querySelector('.rl-pc-said')), 'Air search, 3 days ago');
});

test('a report that names no kind shows no picture and no kind, even with a picture beside it', () => {
  const rv = seat();
  rv.map.reports.find((r) => r.key === 'r-unknown').picture = 'armour';
  const head = sheetOf(rv, 'r-unknown').querySelector('.rl-pc-report');
  assert.equal(head.querySelector('[data-picture]'), null);
  assert.equal(words(head.querySelector('.rl-pc-kind')), 'Unknown piece');
  assert.equal(words(head.querySelector('.rl-pc-said')), 'Patrol, 1 day ago');
});

test('a report\'s sheet draws no figure, whatever the report carries', () => {
  const rv = seat();
  Object.assign(rv.map.reports[0], { figures: LEVY_KIND().figures, here: LEVY_KIND().here, changes: LEVY_KIND().changes });
  const sheet = sheetOf(rv, 'r-galley');
  assert.equal(metersOf(sheet).length, 0);
  assert.equal(sheet.querySelector('.rl-pc-changes'), null);
});

// --- the module draws only what it is handed ---------------------------------------------------

test('the module names its five figures in a fixed order', () => {
  assert.deepEqual(piece.FIGURES.map(([k]) => k), ['attack', 'defence', 'speed', 'reach', 'hidden']);
});
