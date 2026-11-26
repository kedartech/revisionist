// A picture for every kind of piece (KPC), one test or more per rule: 1. a fixed set of fourteen
// pictures is drawn by key, the same list the core holds; 2. a piece is drawn with its kind's
// picture inside today's frame; 3. a mark with no picture, or a key the client does not have, takes
// its domain's glyph of today; 4. each picture reads at 24 px in one colour and differs from every
// other by outline, not by colour; 5. the pictures are used wherever a piece is named with a mark:
// the map, the list, the battle sheet.
// Keeps: the frame still says whose it is by shape and the tick still says a report is stale; a
// mark is at least 24 px; nothing is drawn that the mark does not carry.
// Mutant: an enemy report given a picture its mark did not carry.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { svg } = await import('../js/dom.js');
const { MIN_MARK_PX } = await import('../js/realism-rules.js');
const { PICTURES, forceGlyph, mapDrawing, mapView, markSwatch } = await import('../js/views/realism-map.js');
const { reportMarks, reportTables } = await import('../js/views/realism-reports.js');
const { battleSheet } = await import('../js/views/realism-battle.js');
const { territoryDrawing, territoryView } = await import('../js/views/realism-territory.js');

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const fixture = JSON.parse(read('./fixtures/realism-seat.json'));
const SHAPES = JSON.parse(read('./fixtures/toy.map.json'));
const TODAY = '1900-04-16';
const FOURTEEN = [
  'infantry', 'armour', 'garrison', 'cavalry', 'artillery', 'battle_fleet', 'carrier',
  'submarines', 'transports', 'gunboat', 'ironclad', 'fighters', 'bombers', 'envoy',
];

/** Every element under `nodes` (an element, or an array of them and nulls), itself included. */
function all(nodes) {
  const out = [];
  const walk = (n) => {
    if (!n) return;
    if (Array.isArray(n)) { n.forEach(walk); return; }
    out.push(n);
    (n.children ?? []).forEach(walk);
  };
  walk(nodes);
  return out;
}
const pictureIn = (nodes) => all(nodes).find((n) => n.getAttribute?.('data-picture')) ?? null;
const glyphIn = (nodes) => all(nodes).find((n) => n.classList?.contains('rl-mk-glyph')) ?? null;

/** The toy territory map with its own pieces' kinds carrying `pictures` by piece name. */
function withPictures(pictures) {
  const map = structuredClone(fixture.territory_map);
  for (const m of map.marks) {
    if (!m.piece || !(m.name in pictures)) continue;
    m.piece.figures = {
      key: m.piece.kind.toLowerCase(), name: m.piece.kind, picture: pictures[m.name],
      figures: { attack: 3, defence: 3, speed: 3, reach: 1, hidden: 1 },
      here: { attack: 3, defence: 3, speed: 3, reach: 1, hidden: 1 }, changes: [],
    };
  }
  return map;
}

/** A report of the enemy's levy in the Gulf, with `extra` fields. */
const levyReport = (extra = {}) => ({ ...structuredClone(fixture.reports_map.reports[0]), kind: 'levy', kind_name: 'Levy', ...extra });

/** Each point a path's commands visit (end points and control points), absolute. */
function pathPoints(d) {
  const tokens = d.match(/[a-zA-Z]|-?\d*\.?\d+(?:e-?\d+)?/g);
  const pts = [];
  let i = 0; let cmd = null; let x = 0; let y = 0; let sx = 0; let sy = 0;
  const num = () => Number(tokens[i++]);
  const arity = { m: 2, l: 2, h: 1, v: 1, q: 4, c: 6, s: 4, t: 2, a: 7, z: 0 };
  while (i < tokens.length) {
    if (/[a-zA-Z]/.test(tokens[i])) cmd = tokens[i++];
    const lo = cmd.toLowerCase();
    const rel = cmd !== cmd.toUpperCase();
    if (lo === 'z') { x = sx; y = sy; cmd = null; continue; }
    const args = Array.from({ length: arity[lo] }, num);
    const bx = rel ? x : 0; const by = rel ? y : 0;
    if (lo === 'h') x = bx + args[0];
    else if (lo === 'v') y = by + args[0];
    else if (lo === 'a') { x = bx + args[5]; y = by + args[6]; }
    else {
      for (let k = 0; k + 2 < args.length; k += 2) pts.push([bx + args[k], by + args[k + 1]]);
      x = bx + args[args.length - 2]; y = by + args[args.length - 1];
    }
    pts.push([x, y]);
    if (lo === 'm') { sx = x; sy = y; cmd = rel ? 'l' : 'L'; }
  }
  return pts;
}

// --- rule 1: a fixed set of pictures by key -------------------------------------------------

test('the client draws the fourteen pictures, by key, in the list\'s order', () => {
  assert.deepEqual(Object.keys(PICTURES), FOURTEEN);
});

test('the client\'s pictures are the core\'s fixed list, key for key', () => {
  const src = read('../../src/revisionist/core/realism/kinds.py');
  const block = src.match(/class Picture\(StrEnum\):([\s\S]*?)\n\n\n/)[1];
  assert.deepEqual([...block.matchAll(/= "(\w+)"/g)].map((m) => m[1]), Object.keys(PICTURES));
});

// --- rule 2: a piece is drawn with its kind's picture inside today's frame --------------------

test('an own piece is drawn with its kind\'s picture inside the own frame, in place of the domain\'s glyph', () => {
  const [levy] = withPictures({ 'The Norra Levy': 'armour' }).marks.filter((m) => m.name === 'The Norra Levy');
  const drawn = forceGlyph({ ...levy, kind: 'army' }, MIN_MARK_PX);
  assert.equal(drawn[0].tagName.toLowerCase(), 'rect', 'own: the rectangle');
  assert.equal(pictureIn(drawn).getAttribute('data-picture'), 'armour');
  assert.equal(glyphIn(drawn), null, 'no domain glyph beside the picture');
});

test('a report that carries a picture is drawn with it inside the diamond', () => {
  const drawn = forceGlyph({ side: 'other', kind: 'fleet', certainty: 'reported', picture: 'carrier' }, MIN_MARK_PX);
  assert.equal(drawn[0].tagName.toLowerCase(), 'path', 'another\'s: the diamond');
  assert.match(drawn[0].getAttribute('d'), /^M0 /);
  assert.equal(pictureIn(drawn).getAttribute('data-picture'), 'carrier');
});

test('the stale tick is still drawn beside a picture', () => {
  const drawn = forceGlyph({ side: 'other', kind: 'army', certainty: 'stale', picture: 'infantry' }, MIN_MARK_PX);
  assert.ok(all(drawn).some((n) => n.classList?.contains('rl-mk-tick')));
  assert.ok(pictureIn(drawn));
});

test('the territory map draws each own piece with its kind\'s picture', () => {
  const map = withPictures({ 'The Norra Levy': 'infantry', 'The Norra Kites': 'fighters', 'The Norra Herald': 'envoy' });
  const drawn = territoryDrawing(map, SHAPES, { px: 900, selected: 'The Norra Levy' });
  const pics = drawn.querySelectorAll('.rl-tm-mark [data-picture]').map((n) => n.getAttribute('data-picture')).sort();
  assert.deepEqual(pics, ['envoy', 'fighters', 'infantry']);
  const closed = territoryDrawing(map, SHAPES, { px: 900 });
  assert.equal(closed.querySelectorAll('.rl-tm-stack-top [data-picture]').length, 1,
    'a stack\'s top piece too');
});

test('the point map draws an own piece with its kind\'s picture', () => {
  const map = structuredClone(fixture.map);
  const own = map.marks.find((m) => m.side === 'own' && m.places.length === 1);
  own.piece = { kind: 'Levy', domain: 'land', figures: { picture: 'garrison' } };
  const drawn = mapDrawing(map, null, {});
  assert.equal(drawn.querySelectorAll('.rl-mk [data-picture="garrison"]').length, 1);
});

// --- rule 3: no picture, or an unknown key: the domain's glyph of today -----------------------

test('a mark with no picture takes its domain\'s glyph of today', () => {
  for (const kind of ['army', 'fleet', 'air', 'envoy']) {
    const drawn = forceGlyph({ side: 'own', kind, certainty: 'known' }, MIN_MARK_PX);
    assert.equal(pictureIn(drawn), null);
    assert.ok(glyphIn(drawn), kind);
  }
  const levy = withPictures({ 'The Norra Levy': null }).marks.find((m) => m.name === 'The Norra Levy');
  assert.ok(glyphIn(forceGlyph({ ...levy, kind: 'army' }, MIN_MARK_PX)));
});

test('a key the client does not have takes the domain\'s glyph', () => {
  const levy = withPictures({ 'The Norra Levy': 'zeppelin' }).marks.find((m) => m.name === 'The Norra Levy');
  const drawn = forceGlyph({ ...levy, kind: 'army' }, MIN_MARK_PX);
  assert.equal(pictureIn(drawn), null);
  assert.ok(glyphIn(drawn));
  assert.equal(pictureIn(forceGlyph({ side: 'other', kind: 'fleet', certainty: 'reported', picture: 'toString' }, MIN_MARK_PX)), null);
});

// --- rule 4: each reads at 24 px in one colour, and differs by outline ------------------------

test('each picture is one outline in one colour: one path, its class alone, no colour of its own', () => {
  for (const key of FOURTEEN) {
    const drawn = pictureIn(forceGlyph({ side: 'own', kind: 'army', certainty: 'reported', picture: key }, MIN_MARK_PX));
    assert.equal(drawn.tagName.toLowerCase(), 'path', key);
    assert.equal(drawn.children.length, 0, key);
    assert.equal(drawn.getAttribute('class'), 'rl-mk-pic', key);
    for (const attr of ['fill', 'stroke', 'style', 'color', 'opacity']) assert.equal(drawn.getAttribute(attr), null, `${key} ${attr}`);
  }
});

test('no two pictures share an outline', () => {
  const outlines = FOURTEEN.map((k) => PICTURES[k]);
  assert.equal(new Set(outlines).size, FOURTEEN.length);
  // and no two share the same set of points visited, so a picture is not another moved
  const shapes = outlines.map((d) => JSON.stringify(pathPoints(d).map(([x, y]) => [Math.round(x), Math.round(y)]).sort()));
  assert.equal(new Set(shapes).size, FOURTEEN.length);
});

test('at 24 px each picture fills most of the frame and stays inside both frames', () => {
  for (const key of FOURTEEN) {
    const drawn = pictureIn(forceGlyph({ side: 'own', kind: 'army', certainty: 'reported', picture: key }, MIN_MARK_PX));
    const k = Number(drawn.getAttribute('transform').match(/^scale\(([\d.]+)\)$/)[1]);
    const pts = pathPoints(PICTURES[key]).map(([x, y]) => [x * k, y * k]);
    const r = MIN_MARK_PX / 2;
    for (const [x, y] of pts) {
      assert.ok(Math.abs(x) <= r * 1.4 && Math.abs(y) <= r, `${key} inside the rectangle at ${x},${y}`);
      assert.ok(Math.abs(x) + Math.abs(y) <= r * 1.4, `${key} inside the diamond at ${x},${y}`);
    }
    const wide = Math.max(...pts.map((p) => p[0])) - Math.min(...pts.map((p) => p[0]));
    const tall = Math.max(...pts.map((p) => p[1])) - Math.min(...pts.map((p) => p[1]));
    assert.ok(Math.max(wide, tall) >= 13, `${key} is ${wide} by ${tall} px at 24 px`);
  }
});

test('the pictures take their one colour from the side, from the theme\'s tokens, and the page links the sheet', () => {
  const css = read('../css/c-pieces.css');
  assert.match(css, /\.rl-mk-pic\s*\{[^}]*fill:\s*var\(--side\)/);
  assert.match(css, /\.rl-c-known \.rl-mk-pic\s*\{[^}]*fill:\s*var\(--surface\)/);
  assert.doesNotMatch(css, /#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i);
  assert.match(read('../index.html'), /<link rel="stylesheet" href="\/css\/c-pieces\.css">/);
});

// --- rule 5: the map, the list, the battle sheet ----------------------------------------------

test('a report carrying a picture is drawn on the map with it, and no question mark', () => {
  const map = { ...structuredClone(fixture.territory_map), reports: [levyReport({ picture: 'cavalry' })] };
  const out = reportMarks({
    map, labelAt: new Map([['the_gulf', [100, 100]]]), atPx: (attrs, x, y, ...kids) => svg('g', { ...attrs, transform: `translate(${x} ${y})` }, kids),
    activate: () => ({}), opts: { today: TODAY },
  });
  assert.equal(pictureIn(out).getAttribute('data-picture'), 'cavalry');
  assert.ok(!all(out).some((n) => n.classList?.contains('rl-rp-unknown')));
});

test('a report is given no picture its mark does not carry, though the seat holds a piece of that kind', () => {
  const map = { ...withPictures({ 'The Norra Levy': 'infantry' }), reports: [levyReport()] };
  const out = reportMarks({
    map, labelAt: new Map([['the_gulf', [100, 100]]]), atPx: (attrs, x, y, ...kids) => svg('g', { ...attrs, transform: `translate(${x} ${y})` }, kids),
    activate: () => ({}), opts: { today: TODAY },
  });
  assert.equal(pictureIn(out), null);
  assert.ok(glyphIn(out), 'the domain\'s glyph of today');
  const rows = reportTables(map, { today: TODAY })[0];
  assert.equal(pictureIn(rows), null);
});

test('the reports list draws each report\'s mark with its picture', () => {
  const map = { ...structuredClone(fixture.territory_map), reports: [levyReport({ picture: 'infantry' })] };
  const [list] = reportTables(map, { today: TODAY });
  const row = list.querySelector('tbody tr');
  assert.equal(row.querySelector('[data-picture]').getAttribute('data-picture'), 'infantry');
  assert.match(words(row), /^Levy/);
});

test('the point map\'s list draws each piece\'s mark with its picture', () => {
  const map = structuredClone(fixture.map);
  const own = map.marks.find((m) => m.side === 'own' && m.places.length === 1);
  own.piece = { kind: 'Levy', domain: 'land', figures: { picture: 'artillery' } };
  const list = mapView(map, null, { mode: 'list' });
  const row = list.querySelectorAll('tbody tr').find((r) => words(r.querySelector('th')) === own.name);
  assert.equal(row.querySelector('[data-picture]').getAttribute('data-picture'), 'artillery');
});

test('the territory list draws each own piece\'s mark with its picture', () => {
  const map = withPictures({ 'The Norra Levy': 'infantry', 'The Norra Kites': 'bombers' });
  const list = territoryView(map, SHAPES, { mode: 'list' });
  const pic = (name) => list.querySelectorAll('tbody tr').find((r) => words(r.querySelector('th') ?? r) === name)
    ?.querySelector('[data-picture]')?.getAttribute('data-picture') ?? null;
  assert.equal(pic('The Norra Levy'), 'infantry');
  assert.equal(pic('The Norra Kites'), 'bombers');
  assert.equal(pic('The Norra Herald'), null, 'no picture sent: the glyph of today');
});

test('the battle sheet draws each of the seat\'s pieces there with its kind\'s picture', () => {
  const rv = structuredClone(fixture);
  rv.map = withPictures({ 'The Norra Levy': 'infantry' });
  rv.clock = { ...rv.clock, world_date: TODAY };
  const sheet = battleSheet(rv, 'sudland_coast', { today: TODAY });
  const who = sheet.querySelector('.rl-bt-own .rl-bt-who');
  assert.equal(who.querySelector('[data-picture]').getAttribute('data-picture'), 'infantry');
  assert.equal(words(who), 'The Norra Levy');
});

test('a list\'s mark is drawn at the mark\'s own size, 24 px or more', () => {
  const swatch = markSwatch({ side: 'own', kind: 'army', certainty: 'known', picture: 'infantry' });
  assert.ok(Number(swatch.getAttribute('width')) >= MIN_MARK_PX && Number(swatch.getAttribute('height')) >= MIN_MARK_PX);
  const [, , w] = swatch.getAttribute('viewBox').split(' ').map(Number);
  assert.equal(Number(swatch.getAttribute('width')), w, 'drawn one to one: the frame is the map\'s 24 px');
  assert.equal(swatch.getAttribute('aria-hidden'), 'true', 'the row\'s words say what it is');
  assert.equal(markSwatch({ side: 'none', kind: 'front', certainty: 'reported' }), null, 'a front has no mark');
});
