// Reports on the map (RPC): each report the seat's nation holds is a mark with its kind's glyph
// (or an unknown one), solid pips to the low end of its range and hollow ones to the high end,
// and an age badge; it fades as it ages and goes when the data drops it. A tap opens its sheet:
// range, age, the person who reported it, the confidence and the paper. A picked report with a
// ring draws the ring as an outline; the threats switch, inside the Military layer, draws every
// ring faintly and marks the seat's own areas one could reach. The intelligence orders are placed
// like pieces: a recon token on a lit area in its wing's range, an agent token on an area,
// concealment on a piece's sheet, codebreaking on the economy sheet. List mode has a twin for
// every report and ring. A wrong report draws exactly like a right one.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { theatreBoard, forgetShapes } = await import('../js/views/realism-theatre.js');
const { territoryDrawing, territoryView, forgetMarks } = await import('../js/views/realism-territory.js');
const { piecePanel } = await import('../js/views/realism-board.js');
const { ownSheet } = await import('../js/views/realism-economy.js');
const rules = await import('../js/realism-rules.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const SHAPES = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const TMAP = fixture.territory_map;
const DESK = { width: 960, height: 740 };
const TODAY = '1900-04-12';

const area = (key) => ({ key, name: TMAP.areas.find((a) => a.key === key).name });

/** A report as the server sends it (RPD, RNG). */
const report = (key, more) => ({
  key, kind: null, kind_name: 'unknown', strength_low: null, strength_high: null, area: null, bound_for: null,
  seen: TODAY, source: 'contact', person: '', confidence: 'A', document: null, ring: null, ...more,
});

/** Four reports: a fresh wing, a levy 2 days old with a ring, an unknown 9 days old with a ring, and a decrypt. */
const REPORTS = [
  report('rWing', { kind: 'kite_wing', kind_name: 'Kite Wing', strength_low: 2, strength_high: 3, area: area('the_gulf'),
    person: 'Ilse Varg', document: 'DOC-1' }),
  report('rLevy', { kind: 'levy', kind_name: 'Levy', strength_low: 1, strength_high: 4, area: area('sudland_coast'),
    seen: '1900-04-10', source: 'air', person: 'Brann Hollis', confidence: 'B', document: 'DOC-2',
    ring: ['norra_hills', 'sudland_coast', 'the_gulf'] }),
  report('rOld', { strength_low: 3, strength_high: 5, area: area('isle'), seen: '1900-04-03', source: 'agent',
    person: 'Oda Strand', confidence: 'C', document: 'DOC-3', ring: ['norra_plain', 'isle', 'open_sea'] }),
  report('rCode', { kind: 'galley', kind_name: 'Galley', bound_for: 'waters', seen: '1900-04-11', source: 'codebreaking',
    person: 'Kel Lund', confidence: 'B', document: 'DOC-4' }),
];

/** The toy territory map with the reports, the seat holding the north, and the threats the server names. */
function rmap() {
  const map = structuredClone(TMAP);
  map.reports = structuredClone(REPORTS);
  const held = new Map(fixture.economy_areas.map((a) => [a.key, a.holder]));
  for (const a of map.areas) {
    a.holder = held.get(a.key) ?? null;
    a.threatened_from = a.holder?.relation === 'own' ? [] : null;
  }
  map.areas.find((a) => a.key === 'norra_plain').threatened_from = ['rOld'];
  map.areas.find((a) => a.key === 'norra_hills').threatened_from = ['rLevy'];
  return map;
}

const draw = (map, opts = {}) => territoryDrawing(map, SHAPES, { px: DESK, today: TODAY, ...opts });
const marks = (pic) => pic.querySelectorAll('g.rl-rp-mark');
const markOf = (pic, key) => marks(pic).find((g) => g.getAttribute('data-report') === key);
const rings = (pic) => pic.querySelectorAll('g.rl-rp-ring');

/** A drawing as text: every element, its attributes and text, the page-unique ids made plain. */
function serial(el) {
  if (!el.tagName) return el.textContent;
  const attrs = [...el.attrs].map(([k, v]) => `${k}=${v.replace(/rl-(tm-clip|hp)-\d+/g, 'rl-$1-N')}`).sort().join(' ');
  return `<${el.tagName} ${attrs}>${el.childNodes.map(serial).join('')}</${el.tagName}>`;
}

// --- the intelligence forms, as INT puts them on the desk -----------------------------

const intelLever = (name, intel, params) => ({
  name, label: `Form ${name}`, summary: '', pipeline: 'P1', rule: 'intel', intel,
  params: [{ name: 'intel', label: 'Order', kind: 'enum', lo: null, hi: null, places: [], areas: {}, choices: [{ value: intel, label: intel }] },
    ...params],
});
const enumParam = (name, choices) => ({ name, label: name, kind: 'enum', lo: null, hi: null, places: [], areas: {}, choices });
const AREA_CHOICES = ['norra_hills', 'norra_plain', 'sudland_coast', 'isle', 'the_gulf', 'open_sea'].map((k) => ({ value: k, label: area(k).name }));
const PIECES = [{ value: 'norra_kites', label: 'The Norra Kites' }, { value: 'norra_levy', label: 'The Norra Levy' }];
/** The forms carry names unlike their orders: the board finds them by rule name and order kind. */
const LEVERS = [
  intelLever('a1', 'recon', [enumParam('piece', [PIECES[0]]), enumParam('area', AREA_CHOICES)]),
  intelLever('a2', 'agent', [enumParam('area', AREA_CHOICES)]),
  intelLever('a3', 'codebreaking', []),
  intelLever('a4', 'conceal', [enumParam('piece', PIECES), enumParam('concealed', [{ value: 'yes', label: 'Yes' }, { value: 'no', label: 'No' }])]),
  { ...intelLever('recon', 'recon', []), rule: 'movement', intel: null },
];

function seat(map = rmap()) {
  return {
    ...fixture,
    map,
    desk: { ...fixture.desk, levers: structuredClone(LEVERS) },
    court: { load_limit: 2, ring: [], chambers: [], paths: [] },
    clock: { ...fixture.clock, world_date: TODAY },
    orders: { orders: [] },
  };
}

async function room(rv, theatre = {}) {
  const ui = { piece: null, theatre: { mode: 'map', scope: 'reports', ...theatre } };
  const acts = [];
  const opened = [];
  const was = globalThis.fetch;
  globalThis.fetch = async (url) => ({ ok: true, status: 200, json: async () => (url === '/api/realism/map' ? { reply: '', refused: false, file: rv.map.file, map: SHAPES } : {}) });
  const r = {
    ui, acts, opened, view: null,
    draw() {
      r.view?.remove();
      r.view = theatreBoard(rv, ui, {
        pick: (p) => { if (p.theatre) ui.theatre = p.theatre; if (p.piece !== undefined) ui.piece = p.piece; r.draw(); },
        act: (message, action, body, then) => { acts.push({ message, action, body, then }); },
        open: (p) => opened.push(p),
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
const lit = (view) => view.querySelectorAll('g.rl-map-target').map((g) => g.getAttribute('data-area')).sort();
const litArea = (view, key) => view.querySelectorAll('g.rl-map-target').find((g) => g.getAttribute('data-area') === key);
const button = (el, label) => el.querySelectorAll('button').find((b) => words(b) === label);
const filed = (r) => r.acts.filter((a) => a.action === 'lever').map((a) => a.body);

// --- rule 1: a mark with its glyph, its range as pips and an age badge -------------------

test('the rules: age in days, the badge, the range as pips, the words for range, source and confidence', () => {
  assert.equal(rules.reportAge('1900-04-10', TODAY), 2);
  assert.equal(rules.reportAge(TODAY, TODAY), 0);
  assert.equal(rules.reportAgeWord(0), 'now');
  assert.equal(rules.reportAgeWord(9), '9d');
  assert.deepEqual(rules.rangePips({ strength_low: 2, strength_high: 3 }), { filled: 2, slots: 3 });
  assert.deepEqual(rules.rangePips({ strength_low: 0, strength_high: 2 }), { filled: 0, slots: 2 });
  assert.equal(rules.rangePips({ strength_low: null, strength_high: null }), null);
  assert.equal(rules.rangeWords({ strength_low: 2, strength_high: 3 }), 'strength 2 to 3');
  assert.equal(rules.rangeWords({ strength_low: 4, strength_high: 4 }), 'strength 4');
  assert.equal(rules.rangeWords({ strength_low: null, strength_high: null }), 'strength not given');
  assert.equal(rules.confidenceWord('B'), 'probable');
  assert.equal(rules.sourceWord('air'), 'Air search');
});

test('each report is a mark: the decrypt at its region, the rest at their areas', () => {
  const pic = draw(rmap());
  assert.deepEqual(marks(pic).map((g) => g.getAttribute('data-report')).sort(), ['rCode', 'rLevy', 'rOld', 'rWing']);
  assert.equal(markOf(pic, 'rLevy').getAttribute('data-area'), 'sudland_coast');
  assert.equal(markOf(pic, 'rCode').getAttribute('data-region'), 'waters');
});

test('a known kind draws its glyph, read from the seat\'s own pieces of that kind; an unknown kind or domain draws the unknown glyph', () => {
  const pic = draw(rmap());
  assert.equal(markOf(pic, 'rWing').getAttribute('data-glyph'), 'air', 'the seat\'s Kites are a Kite Wing, an air piece');
  assert.equal(markOf(pic, 'rLevy').getAttribute('data-glyph'), 'army');
  assert.equal(markOf(pic, 'rOld').getAttribute('data-glyph'), 'unknown');
  assert.equal(markOf(pic, 'rCode').getAttribute('data-glyph'), 'unknown', 'no own galley says what a galley is');
  assert.ok(markOf(pic, 'rOld').querySelector('text.rl-rp-unknown'), 'the unknown glyph is drawn');
});

test('the range is pips: solid to the low end, hollow to the high end; a decrypt has none', () => {
  const pic = draw(rmap());
  const pips = markOf(pic, 'rLevy').querySelector('g.rl-tm-pips');
  assert.equal(pips.getAttribute('data-filled'), '1');
  assert.equal(pips.getAttribute('data-slots'), '4');
  assert.equal(pips.querySelectorAll('rect.rl-pip-empty').length, 3);
  assert.equal(markOf(pic, 'rCode').querySelector('g.rl-tm-pips'), null);
});

test('each mark has an age badge and says all of it in words', () => {
  const pic = draw(rmap());
  assert.deepEqual(['rWing', 'rLevy', 'rOld'].map((k) => words(markOf(pic, k).querySelector('g.rl-rp-age'))), ['now', '2d', '9d']);
  assert.equal(markOf(pic, 'rLevy').getAttribute('aria-label'),
    'Report: Levy, strength 1 to 4, in The Sudland Coast, seen 10 Apr, 2 days ago, by Brann Hollis (Air search), probable');
});

// --- the keep: a wrong report draws exactly like a right one ----------------------------

test('two maps that differ only in a report\'s truth draw the same, in map and in list', () => {
  const right = rmap();
  const wrong = rmap();
  // what the truth holds, attached where a careless client might read it
  Object.assign(wrong.reports[1], { strength: 9, true_strength: 9, true_area: 'isle', correct: false, right: false });
  Object.assign(right.reports[1], { strength: 2, true_strength: 2, true_area: 'sudland_coast', correct: true, right: true });
  for (const opts of [{}, { report: 'rLevy' }, { threats: true }]) {
    forgetMarks();
    const a = serial(draw(right, opts));
    forgetMarks();
    assert.equal(serial(draw(wrong, opts)), a, JSON.stringify(opts));
  }
  const list = (map) => serial(territoryView(map, SHAPES, { mode: 'list', today: TODAY }));
  assert.equal(list(wrong), list(right));
  const sheet = (map) => serial(territoryView(map, SHAPES, { report: 'rLevy', today: TODAY, px: DESK }).querySelector('.rl-rp-sheet'));
  assert.equal(sheet(wrong), sheet(right));
});

// --- rule 2: a tap opens the report's sheet ---------------------------------------------

test('a tap on a report picks it, and its sheet gives range, age, person, confidence and the paper', async () => {
  const r = await room(seat());
  markOf(r.view, 'rLevy').click();
  assert.equal(r.ui.theatre.report, 'rLevy');
  const sheet = r.view.querySelector('.rl-rp-sheet');
  assert.ok(sheet, 'the sheet is open');
  const said = words(sheet);
  for (const bit of ['Levy', 'strength 1 to 4', '10 Apr, 2 days ago', 'Brann Hollis', 'Air search', 'Probable', 'The Sudland Coast']) {
    assert.ok(said.includes(bit), `${bit} in: ${said}`);
  }
  button(sheet, 'Open the paper').click();
  assert.deepEqual(r.opened, [{ id: 'DOC-2' }]);
  assert.equal(markOf(r.view, 'rLevy').getAttribute('aria-pressed'), 'true');
  button(sheet, 'Close').click();
  assert.equal(r.ui.theatre.report, null);
  assert.equal(r.view.querySelector('.rl-rp-sheet'), null);
});

test('a report no one is named for has no paper to open, and says so', () => {
  const map = rmap();
  Object.assign(map.reports[0], { person: '', document: null });
  const sheet = territoryView(map, SHAPES, { report: 'rWing', today: TODAY, px: DESK }).querySelector('.rl-rp-sheet');
  assert.equal(button(sheet, 'Open the paper'), undefined);
  assert.match(words(sheet), /No paper: seen in contact/);
});

// --- rule 3: the ring, and the threats switch -------------------------------------------

test('a picked report with a ring draws the ring as one outline round its areas', () => {
  const pic = draw(rmap(), { report: 'rLevy' });
  const ring = rings(pic);
  assert.equal(ring.length, 1);
  assert.equal(ring[0].getAttribute('data-report'), 'rLevy');
  assert.equal(ring[0].getAttribute('data-areas'), 'norra_hills sudland_coast the_gulf');
  assert.match(ring[0].getAttribute('aria-label'), /could be in 3 areas: The Norra Hills, The Sudland Coast, The Gulf/);
  // only the outline: no edge between two areas of the ring
  const edges = rules.ringEdges(['norra_hills', 'sudland_coast', 'the_gulf'], SHAPES);
  const inside = rules.borders(SHAPES).filter(({ between }) => between.every((k) => ['norra_hills', 'sudland_coast', 'the_gulf'].includes(k)));
  const key = ([p, q]) => (p < q ? `${p} ${q}` : `${q} ${p}`);
  const out = new Set(edges.map(key));
  for (const b of inside) for (const e of b.edges) assert.ok(!out.has(key(e)), `inner edge ${e}`);
  assert.ok(edges.length > 0);
});

test('a fresh report, which carries no ring, draws none when picked or under threats', () => {
  assert.equal(rings(draw(rmap(), { report: 'rWing' })).length, 0);
  assert.equal(rings(draw(rmap(), { report: 'rCode' })).length, 0);
  const pic = draw(rmap(), { threats: true });
  assert.deepEqual(rings(pic).map((g) => g.getAttribute('data-report')).sort(), ['rLevy', 'rOld']);
});

test('no picked report and the threats switch off: no ring and no threat mark', () => {
  const pic = draw(rmap());
  assert.equal(rings(pic).length, 0);
  assert.equal(pic.querySelectorAll('.rl-rp-threat').length, 0);
});

test('the threats switch draws every ring faintly and marks the seat\'s own areas the server names in reach', () => {
  const pic = draw(rmap(), { threats: true, report: 'rLevy' });
  const faint = rings(pic).filter((g) => g.classList.contains('faint'));
  assert.deepEqual(faint.map((g) => g.getAttribute('data-report')), ['rOld'], 'the picked ring stays full');
  const threat = pic.querySelectorAll('.rl-rp-threat');
  assert.deepEqual(threat.map((p) => p.getAttribute('data-area')).sort(), ['norra_hills', 'norra_plain']);
  assert.match(threat.find((p) => p.getAttribute('data-area') === 'norra_hills').getAttribute('aria-label'),
    /The Norra Hills: in reach of Levy, strength 1 to 4/);
});

test('the threats switch sits in the Military layer and is a pressed button', async () => {
  const r = await room(seat());
  const sw = r.view.querySelectorAll('button').find((b) => b.classList.contains('rl-rp-threats'));
  assert.ok(sw);
  assert.equal(sw.getAttribute('aria-pressed'), 'false');
  sw.click();
  assert.equal(r.ui.theatre.threats, true);
  assert.equal(r.view.querySelectorAll('button').find((b) => b.classList.contains('rl-rp-threats')).getAttribute('aria-pressed'), 'true');
  assert.ok(r.view.querySelectorAll('.rl-rp-threat').length > 0);
  const econ = territoryView(rmap(), SHAPES, { layer: 'economy', threats: true, today: TODAY, px: DESK });
  assert.equal(econ.querySelectorAll('button').find((b) => b.classList.contains('rl-rp-threats')), undefined);
  assert.equal(econ.querySelectorAll('g.rl-rp-mark').length, 0, 'reports are drawn in the Military layer only');
});

// --- rule 4: intelligence orders placed like pieces --------------------------------------

test('the forms are found by rule name and order kind, never by a form\'s name', () => {
  assert.equal(rules.intelForm(LEVERS, 'recon').name, 'a1');
  assert.equal(rules.intelForm(LEVERS, 'patrol'), null);
  assert.equal(rules.intelForm([{ ...LEVERS[0], rule: 'movement' }], 'recon'), null);
});

test('a recon token lights the wing\'s moves the form offers; a lit area opens the chip and Send files the form', async () => {
  const r = await room(seat());
  button(r.view, 'Recon with The Norra Kites').click();
  const kites = TMAP.marks.find((m) => m.name === 'The Norra Kites');
  assert.deepEqual(lit(r.view), kites.piece.moves.map((mv) => mv.area.key).sort());
  litArea(r.view, 'the_gulf').click();
  const chip = r.view.querySelector('.rl-rp-chip');
  assert.match(words(chip), /Fly a reconnaissance flight over The Gulf with The Norra Kites/);
  assert.ok(r.view.querySelector('g.rl-rp-token[data-area="the_gulf"]'), 'the token stands on the area');
  button(chip, 'Send it').click();
  assert.deepEqual(filed(r), [{ lever: 'a1', params: { intel: 'recon', piece: 'norra_kites', area: 'the_gulf' } }]);
});

test('a recon token cannot be put down out of the wing\'s range or where the form offers no area', async () => {
  const rv = seat();
  rv.desk.levers[0].params[2].choices = AREA_CHOICES.filter((c) => c.value !== 'open_sea');
  const r = await room(rv);
  button(r.view, 'Recon with The Norra Kites').click();
  assert.deepEqual(lit(r.view), ['isle', 'sudland_coast', 'the_gulf']);
  assert.equal(litArea(r.view, 'norra_hills'), undefined, 'out of range is not lit');
  for (const key of ['norra_hills', 'open_sea']) {
    r.view.querySelectorAll('path.rl-area').find((p) => p.getAttribute('data-area') === key).click();
    assert.equal(r.view.querySelector('.rl-rp-chip'), null, key);
  }
  assert.deepEqual(filed(r), []);
});

test('an agent token lights every area the form offers and files the agent form', async () => {
  const r = await room(seat());
  button(r.view, 'Place an agent').click();
  assert.deepEqual(lit(r.view), AREA_CHOICES.map((c) => c.value).sort());
  litArea(r.view, 'sudland_coast').click();
  const chip = r.view.querySelector('.rl-rp-chip');
  assert.match(words(chip), /Place an agent in The Sudland Coast/);
  button(chip, 'Back').click();
  assert.equal(r.view.querySelector('.rl-rp-chip'), null);
  litArea(r.view, 'sudland_coast').click();
  button(r.view.querySelector('.rl-rp-chip'), 'Send it').click();
  assert.deepEqual(filed(r), [{ lever: 'a2', params: { intel: 'agent', area: 'sudland_coast' } }]);
});

test('with no intelligence form, no token is offered', async () => {
  const rv = seat();
  rv.desk.levers = [];
  const r = await room(rv);
  assert.equal(r.view.querySelector('.rl-rp-tokens'), null);
});

test('concealment is a switch on a piece\'s sheet the conceal form lists, filing the form', () => {
  const rv = seat();
  const acts = [];
  const act = (m, a, b) => acts.push({ a, b });
  const panel = piecePanel(rv, { kind: 'force', name: 'The Norra Levy' }, () => {}, { act });
  const sw = panel.querySelector('.rl-rp-conceal');
  assert.ok(sw, 'the switch is on the sheet');
  button(sw, 'Conceal').click();
  button(sw, 'Stop concealing').click();
  assert.deepEqual(acts.map((x) => x.b), [
    { lever: 'a4', params: { intel: 'conceal', piece: 'norra_levy', concealed: 'yes' } },
    { lever: 'a4', params: { intel: 'conceal', piece: 'norra_levy', concealed: 'no' } },
  ]);
  assert.ok(acts.every((x) => x.a === 'lever'));
  const herald = piecePanel(rv, { kind: 'force', name: 'The Norra Herald' }, () => {}, { act });
  assert.equal(herald.querySelector('.rl-rp-conceal'), null, 'a piece the form does not list has none');
});

test('codebreaking is in the economy sheet and files its form', () => {
  const rv = seat();
  const acts = [];
  const sheet = ownSheet(rv.economy, rv.map, { levers: rv.desk.levers, act: (m, a, b) => acts.push({ a, b }) });
  const block = sheet.querySelector('.rl-rp-codebreaking');
  assert.ok(block);
  button(block, 'Fund codebreaking').click();
  assert.deepEqual(acts, [{ a: 'lever', b: { lever: 'a3', params: { intel: 'codebreaking' } } }]);
  assert.equal(ownSheet(rv.economy, rv.map).querySelector('.rl-rp-codebreaking'), null, 'no form, no block');
});

// --- rule 5: a report fades as it ages and goes when the data drops it ------------------

test('a report fades with age: fresh, ageing from 5 days, old from 9', () => {
  assert.deepEqual([0, 4, 5, 8, 9, 30].map(rules.reportFade), [0, 0, 1, 1, 2, 2]);
  const pic = draw(rmap());
  const fade = (k) => markOf(pic, k).getAttribute('data-fade');
  assert.deepEqual(['rWing', 'rLevy', 'rOld'].map(fade), ['0', '0', '2']);
  assert.ok(markOf(pic, 'rOld').classList.contains('rl-rp-fade-2'));
});

test('a report the data drops is gone, its sheet and its ring with it', async () => {
  const rv = seat();
  const r = await room(rv, { report: 'rLevy' });
  assert.ok(r.view.querySelector('.rl-rp-sheet'));
  rv.map.reports = rv.map.reports.filter((x) => x.key !== 'rLevy');
  r.draw();
  assert.equal(markOf(r.view, 'rLevy'), undefined);
  assert.equal(r.view.querySelector('.rl-rp-sheet'), null);
  assert.equal(rings(r.view).length, 0);
});

// --- rule 6: list mode has a twin for every report and ring -------------------------------

test('list mode has a row for every report, with its ring, and one for every own area in reach', () => {
  const view = territoryView(rmap(), SHAPES, { mode: 'list', today: TODAY });
  const rows = view.querySelectorAll('table.rl-rp-list tbody tr');
  assert.deepEqual(rows.map((tr) => tr.getAttribute('data-report')).sort(), ['rCode', 'rLevy', 'rOld', 'rWing']);
  const levy = words(rows.find((tr) => tr.getAttribute('data-report') === 'rLevy'));
  for (const bit of ['Levy', 'strength 1 to 4', 'The Sudland Coast', '10 Apr, 2 days ago', 'Air search', 'Brann Hollis', 'Probable',
    'Could be in 3 areas: The Norra Hills, The Sudland Coast, The Gulf']) assert.ok(levy.includes(bit), `${bit} in: ${levy}`);
  const code = words(rows.find((tr) => tr.getAttribute('data-report') === 'rCode'));
  assert.ok(code.includes('Bound for The Waters'), code);
  const threats = view.querySelectorAll('table.rl-rp-threat-list tbody tr');
  assert.deepEqual(threats.map((tr) => tr.getAttribute('data-area')).sort(), ['norra_hills', 'norra_plain']);
});

test('Find on map from a report\'s row picks it in map mode', () => {
  const picked = [];
  const view = territoryView(rmap(), SHAPES, { mode: 'list', today: TODAY, onReport: (k, mode) => picked.push([k, mode]) });
  const row = view.querySelectorAll('table.rl-rp-list tbody tr').find((tr) => tr.getAttribute('data-report') === 'rOld');
  button(row, 'Find on map').click();
  assert.deepEqual(picked, [['rOld', 'map']]);
});

test('a game with no reports draws no report and offers no switch', () => {
  const map = structuredClone(TMAP);
  const pic = territoryView(map, SHAPES, { today: TODAY, px: DESK });
  assert.equal(pic.querySelectorAll('g.rl-rp-mark').length, 0);
  assert.equal(pic.querySelectorAll('button').find((b) => b.classList.contains('rl-rp-threats')), undefined);
});

test('c-reports.css is linked from the page and draws with tokens only', () => {
  const page = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  assert.ok(page.includes('<link rel="stylesheet" href="/css/c-reports.css">'));
  const css = readFileSync(new URL('../css/c-reports.css', import.meta.url), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgba?\(/, 'no literal colour');
  for (const sel of ['.rl-rp-ring-line', '.rl-rp-threat', '.rl-rp-fade-2', '.rl-rp-badge']) assert.ok(css.includes(sel), sel);
});
