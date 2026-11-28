// Weather, and pieces being raised, on the map (KMS), one test or more per rule: 1. an area under
// weather that changes a move or a fight of the seat's own kinds is hatched on the Military layer,
// with the weather's name at its region's label; the hatch is a pattern, not a colour alone, and
// differs from the hatching of enemy-held territory; 2. a piece being raised is drawn at its place
// as its kind's picture in outline, with the day it arrives; 3. both take a tap: the weather's
// line, and the raising's sheet; 4. the map draws each own piece and each report with its kind's
// picture.
// Keeps: drawing only; a mark at least 24 px; nothing drawn that the reply does not carry; the
// layers of today stay.
// Mutant: a region hatched for weather that changes nothing.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { territoryDrawing, territoryView, forgetMarks } = await import('../js/views/realism-territory.js');
const { theatreBoard, forgetShapes } = await import('../js/views/realism-theatre.js');
const { MIN_MARK_PX, MIN_TAP_PX, boxOf, territoryProjection } = await import('../js/realism-rules.js');

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const fixture = JSON.parse(read('./fixtures/realism-seat.json'));
const SHAPES = JSON.parse(read('./fixtures/toy.map.json'));
const CSS_TEXT = read('../css/c-map.css');
const DESK = { width: 960, height: 740 };
const TODAY = '1900-03-12';

/** The thaw: the levy slower on the plain and weaker everywhere; fair weather changes nothing. */
const THAW = { key: 'thaw', name: 'The Thaw', does: [
  { kind: 'levy', figure: 'speed', direction: 'down', terrain: ['plain'] },
  { kind: 'levy', figure: 'attack', direction: 'down', terrain: [] },
  { kind: 'galley', figure: 'speed', direction: 'closed', terrain: ['deep'] },
] };
const FAIR = { key: 'fair', name: 'Fair', does: [] };

/** The weather block: the mainland under `now` this month, the waters fair; fair everywhere next month. */
function weather(now = THAW) {
  const row = (region, key) => ({ region, now: key, next: 'fair' });
  return {
    month: 'March', next_month: 'April',
    regions: [row('mainland', now.key), row('north', now.key), row('south', now.key), row('waters', 'fair')],
    kinds: now.key === 'fair' ? [FAIR] : [FAIR, now],
  };
}

/** The toy territory map with the weather block, the levy's kind carrying its picture. */
function wmap(now = THAW) {
  const map = structuredClone(fixture.territory_map);
  map.weather = weather(now);
  const levy = map.marks.find((m) => m.name === 'The Norra Levy');
  levy.piece.figures = {
    key: 'levy', name: 'Levy', picture: 'infantry',
    figures: { attack: 3, defence: 3, speed: 3, reach: 1, hidden: 1 },
    here: { attack: 3, defence: 3, speed: 3, reach: 1, hidden: 1 }, changes: [],
  };
  return map;
}

/** A piece being raised, as the economy block sends it. */
const raising = (more = {}) => ({
  kind: 'fire_kite', name: 'Fire Kites', place: 'norrhavn', place_name: 'Norrhavn', area: 'norra_plain',
  day: '1900-04-22', fixed: true, picture: 'bombers', ...more,
});

const draw = (map, opts = {}) => territoryDrawing(map, SHAPES, { px: DESK, today: TODAY, ...opts });
const hatched = (pic) => pic.querySelectorAll('path.rl-wx').map((p) => p.getAttribute('data-area')).sort();
const tags = (pic) => pic.querySelectorAll('g.rl-wx-tag');
const raised = (pic) => pic.querySelectorAll('g.rl-tm-raise');
const xyOf = (g) => [Number(g.getAttribute('data-x')), Number(g.getAttribute('data-y'))].map(Math.round);

/** A key pressed on `el`, sent up through its ancestors as a page would (the fake does not bubble). */
function press(el, key) {
  const ev = { type: 'keydown', key, target: el, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
  for (let n = el; n && n.dispatchEvent; n = n.parentNode) n.dispatchEvent(ev);
  return ev;
}

// --- rule 1: weather that changes a move or a fight is hatched, with its name ------------------

test('each area under weather that changes the seat\'s kinds there is hatched on the Military layer', () => {
  assert.deepEqual(hatched(draw(wmap())), ['norra_hills', 'norra_plain', 'sudland_coast']);
});

test('a region under weather that changes nothing is not hatched', () => {
  const pic = draw(wmap(FAIR));
  assert.deepEqual(hatched(pic), []);
  assert.equal(tags(pic).length, 0);
});

test('weather that changes nothing for the seat\'s own kinds is not hatched, whatever its name', () => {
  assert.deepEqual(hatched(draw(wmap({ key: 'drizzle', name: 'Drizzle', does: [] }))), []);
});

test('weather that acts on one terrain hatches only the areas of that terrain', () => {
  const slow = { key: 'mud', name: 'Mud', does: [THAW.does[0]] };
  assert.deepEqual(hatched(draw(wmap(slow))), ['norra_plain', 'sudland_coast']);
});

test('the hatch is a pattern of its own, apart from the enemy\'s hatching', () => {
  const map = wmap();
  map.areas.find((a) => a.key === 'sudland_coast').holder = { key: 'sud', name: 'Sudland', relation: 'enemy' };
  const pic = draw(map);
  const patterns = pic.querySelectorAll('pattern');
  const wx = patterns.find((p) => p.getAttribute('data-pattern') === 'weather');
  const enemy = patterns.find((p) => p.getAttribute('data-pattern') === 'cross');
  assert.ok(wx, 'a weather pattern');
  assert.ok(enemy, 'the enemy\'s pattern beside it');
  const lines = (p) => p.querySelectorAll('path').map((x) => x.getAttribute('d')).join(' ');
  assert.notEqual(lines(wx), lines(enemy));
  const fill = pic.querySelectorAll('path.rl-wx')[0].getAttribute('fill');
  assert.equal(fill, `url(#${wx.getAttribute('id')})`);
});

test('the weather\'s name stands once at each region\'s label, inside the hatch', () => {
  const pic = draw(wmap());
  const found = tags(pic);
  assert.deepEqual(found.map((g) => g.getAttribute('data-region')).sort(), ['north', 'south']);
  for (const g of found) assert.equal(words(g.querySelector('text.rl-wx-name')), 'The Thaw');
});

test('the weather is drawn on the Military layer only', () => {
  for (const layer of ['economy', 'diplomatic']) {
    const pic = draw(wmap(), { layer });
    assert.deepEqual(hatched(pic), [], layer);
    assert.equal(tags(pic).length, 0, layer);
  }
});

test('a map with no weather block draws no weather', () => {
  const map = wmap();
  delete map.weather;
  assert.deepEqual(hatched(draw(map)), []);
});

test('the hatch and the name take their colours from the theme\'s tokens', () => {
  const rules = CSS_TEXT.split('}').filter((r) => /\.rl-wx/.test(r));
  assert.ok(rules.length >= 2);
  for (const r of rules) assert.doesNotMatch(r, /#[0-9a-f]{3,8}\b|rgb\(|hsl\(/i);
  assert.match(CSS_TEXT, /\.rl-wx-line\s*\{[^}]*stroke:\s*var\(--/);
});

// --- rule 2: a piece being raised, at its place, in outline, with its day --------------------

test('a piece being raised is drawn at its place with its kind\'s picture inside the own frame', () => {
  const pic = draw(wmap(), { raisings: [raising()] });
  const [g] = raised(pic);
  assert.ok(g, 'drawn');
  assert.equal(g.getAttribute('data-raise'), 'norrhavn');
  const map = fixture.territory_map;
  const proj = territoryProjection(map.coords ?? SHAPES.coords, boxOf(map.box ?? SHAPES.box));
  const at = (name) => { const p = map.places.find((x) => x.name === name); return proj.point([p.lon, p.lat]).map(Math.round); };
  assert.deepEqual(xyOf(g), at('Norrhavn'));
  // Sudby stands apart from its territory's label point: the place, not the area, sets the spot
  const apart = draw(wmap(), { raisings: [raising({ place: 'sudby', place_name: 'Sudby', area: 'sudland_coast' })] });
  const label = apart.querySelector('g.rl-tm-label[data-area="sudland_coast"]');
  assert.deepEqual(xyOf(raised(apart)[0]), at('Sudby'));
  assert.notDeepEqual(at('Sudby'), xyOf(label));
  assert.ok(g.querySelector('rect.rl-mk-shape'), 'the own frame');
  assert.equal(g.querySelector('[data-picture]').getAttribute('data-picture'), 'bombers');
});

test('the raised piece is drawn in outline: its frame and picture are not filled', () => {
  assert.match(CSS_TEXT, /\.rl-tm-raise \.rl-mk-shape\s*\{[^}]*fill:\s*none[^}]*stroke-dasharray/);
  assert.match(CSS_TEXT, /\.rl-tm-raise \.rl-mk-pic\s*\{[^}]*fill:\s*none[^}]*stroke:\s*var\(--/);
});

test('the raised piece carries the day it arrives', () => {
  const [g] = raised(draw(wmap(), { raisings: [raising()] }));
  assert.equal(words(g.querySelector('text.rl-tm-raise-day')), 'arrives 22 Apr');
  assert.match(g.getAttribute('aria-label'), /Fire Kites being raised at Norrhavn: arrives 22 Apr/);
});

test('a raising whose place the map does not hold is drawn at its area\'s label', () => {
  const pic = draw(wmap(), { raisings: [raising({ place: 'hillfort', place_name: 'Hillfort', area: 'norra_hills' })] });
  const label = pic.querySelector('g.rl-tm-label[data-area="norra_hills"]');
  assert.deepEqual(xyOf(raised(pic)[0]), xyOf(label));
});

test('a raising with no picture is drawn as the own frame alone, with no glyph it does not carry', () => {
  const [g] = raised(draw(wmap(), { raisings: [raising({ picture: null })] }));
  assert.ok(g.querySelector('rect.rl-mk-shape'));
  assert.equal(g.querySelector('[data-picture]'), null);
  assert.equal(g.querySelector('.rl-mk-glyph'), null);
});

test('the raised piece\'s mark is 24 px or more and its target 44 px', () => {
  const [g] = raised(draw(wmap(), { raisings: [raising()] }));
  const hit = g.querySelector('rect.rl-tm-hit');
  assert.ok(Number(hit.getAttribute('width')) >= 44 && Number(hit.getAttribute('height')) >= 44);
  assert.ok(Number(g.querySelector('rect.rl-mk-shape').getAttribute('height')) >= 24);
  assert.ok(MIN_TAP_PX >= 44 && MIN_MARK_PX >= 24);
});

test('a piece being raised is drawn on the Military layer only, and not with none sent', () => {
  assert.equal(raised(draw(wmap(), { raisings: [raising()], layer: 'economy' })).length, 0);
  assert.equal(raised(draw(wmap(), { raisings: [raising()], layer: 'diplomatic' })).length, 0);
  assert.equal(raised(draw(wmap())).length, 0);
});

// --- rule 3: a tap on either opens its line or its sheet -------------------------------------

test('a tap on the weather\'s name asks for its region\'s line; Enter does the same', () => {
  const asked = [];
  const pic = draw(wmap(), { onWeather: (r) => asked.push(r) });
  const north = tags(pic).find((g) => g.getAttribute('data-region') === 'north');
  assert.equal(north.getAttribute('role'), 'button');
  north.click();
  press(north, 'Enter');
  assert.deepEqual(asked, ['north', 'north']);
  assert.ok(Number(north.querySelector('rect.rl-tm-hit').getAttribute('height')) >= 44);
});

test('the weather\'s line says this month\'s weather, what it does to the seat\'s kinds and next month\'s', () => {
  const view = territoryView(wmap(), SHAPES, { px: DESK, today: TODAY, weatherAt: 'north' });
  const sheet = view.querySelector('.rl-wx-sheet');
  assert.ok(sheet);
  const said = words(sheet);
  assert.match(said, /The North/);
  assert.match(said, /The Thaw in March/);
  assert.match(said, /Levy: speed down on plain/);
  assert.match(said, /Levy: attack down/);
  assert.match(said, /galley: cannot enter deep/);
  assert.match(said, /Fair in April/);
});

test('a tap on a piece being raised asks for its sheet, and the sheet says what, where and when', () => {
  const asked = [];
  const [g] = raised(draw(wmap(), { raisings: [raising()], onRaising: (p) => asked.push(p) }));
  assert.equal(g.getAttribute('role'), 'button');
  g.click();
  assert.deepEqual(asked, ['norrhavn']);
  const view = territoryView(wmap(), SHAPES, { px: DESK, today: TODAY, raisings: [raising()], raiseAt: 'norrhavn' });
  const sheet = view.querySelector('.rl-raise-sheet');
  assert.ok(sheet);
  const said = words(sheet);
  assert.match(said, /Fire Kites/);
  assert.match(said, /Norrhavn/);
  assert.match(said, /22 Apr/);
});

test('each sheet closes by its button and by Escape in the map-first room', () => {
  const closed = [];
  const opts = { px: DESK, today: TODAY, raisings: [raising()], overlay: true, onWeather: (r) => closed.push(['wx', r]), onRaising: (p) => closed.push(['raise', p]) };
  const wx = territoryView(wmap(), SHAPES, { ...opts, weatherAt: 'north' });
  wx.querySelector('.rl-wx-sheet button').click();
  assert.equal(press(wx.querySelector('.rl-wx-sheet button'), 'Escape').defaultPrevented, true);
  const rs = territoryView(wmap(), SHAPES, { ...opts, raiseAt: 'norrhavn' });
  rs.querySelector('.rl-raise-sheet button').click();
  assert.equal(press(rs.querySelector('.rl-raise-sheet button'), 'Escape').defaultPrevented, true);
  assert.deepEqual(closed, [['wx', null], ['wx', null], ['raise', null], ['raise', null]]);
});

test('the room hands the map the nation\'s raisings and opens each sheet by its theatre state', async () => {
  const map = wmap();
  const rv = { ...fixture, map, economy: structuredClone(fixture.raising_economy), clock: { ...fixture.clock, world_date: TODAY } };
  rv.economy.own.raising = [raising()];
  const ui = { piece: null, theatre: { mode: 'map', scope: 'reports' } };
  const was = globalThis.fetch;
  globalThis.fetch = async (url) => ({ ok: true, status: 200, json: async () => (url === '/api/realism/map' ? { reply: '', refused: false, file: map.file, map: SHAPES } : {}) });
  let view = null;
  const drawRoom = () => {
    view?.remove();
    view = theatreBoard(rv, ui, { pick: (p) => { if (p.theatre) ui.theatre = p.theatre; drawRoom(); } });
    document.body.append(view);
  };
  try {
    forgetShapes();
    forgetMarks();
    drawRoom();
    await new Promise((ok) => setTimeout(ok, 0));
    await new Promise((ok) => setTimeout(ok, 0));
  } finally { globalThis.fetch = was; }
  drawRoom();
  const [g] = view.querySelectorAll('g.rl-tm-raise');
  assert.ok(g, 'the raising is drawn');
  g.click();
  assert.equal(ui.theatre.raiseAt, 'norrhavn');
  assert.ok(view.querySelector('.rl-raise-sheet'));
  view.querySelectorAll('g.rl-wx-tag')[0].click();
  assert.ok(['north', 'south'].includes(ui.theatre.weatherAt));
  assert.ok(view.querySelector('.rl-wx-sheet'));
  view.remove();
});

// --- rule 4: each own piece and each report with its kind's picture --------------------------

test('the map draws an own piece, a stack\'s top and an order\'s ghost with the kind\'s picture', () => {
  const map = wmap();
  const levy = map.marks.find((m) => m.name === 'The Norra Levy');
  const pic = draw(map, { selected: 'The Norra Levy' });
  assert.ok(pic.querySelectorAll('.rl-tm-mark [data-picture]').some((n) => n.getAttribute('data-picture') === 'infantry'));
  levy.piece.waiting = { order: 'o-1', with_person: 'Ilse Varg', until: '1900-03-20', withdrawable: false };
  map.orders = [{ order: 'o-1', force: levy.name, mark: levy.name, to: { name: 'The Isle', lat: null, lon: null, theatre: null }, status: 'awaiting', with_person: 'Ilse Varg', filed: null }];
  const ghost = draw(map).querySelector('.rl-tm-ghost [data-picture]');
  assert.equal(ghost?.getAttribute('data-picture'), 'infantry');
  // the toy's three own pieces stand together on the plain: closed, the first is the stack's top
  const herald = map.marks.find((m) => m.name === 'The Norra Herald');
  herald.piece.figures = { ...levy.piece.figures, key: 'herald', name: 'Herald', picture: 'envoy' };
  const stack = draw(map).querySelectorAll('.rl-tm-stack-top [data-picture]');
  assert.deepEqual(stack.map((n) => n.getAttribute('data-picture')), ['envoy']);
});

test('the map draws a report that carries a picture with it', () => {
  const map = wmap();
  map.reports = [{
    key: 'rLevy', kind: 'levy', kind_name: 'Levy', picture: 'infantry', strength_low: 1, strength_high: 2,
    area: { key: 'sudland_coast', name: 'The Sudland Coast' }, bound_for: null, seen: TODAY, source: 'air', person: '',
    confidence: 'B', document: null, ring: null,
  }];
  const pic = draw(map);
  assert.ok(pic.querySelectorAll('[data-picture]').some((n) => n.getAttribute('data-picture') === 'infantry' && n.closest('g.rl-rp-mark')));
});
