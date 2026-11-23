// A proper projection: a longitude-latitude map is drawn in Equal Earth, centred on its own
// box, with a forward and an inverse; a tap is turned back by the inverse; frames are the box
// around what is projected; nothing is cut at the map's edge longitude.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom } from './dom-fake.js';

installDom();
const { MAP_PROJECTION, PROJECTIONS, boxOf, frameRect, territoryProjection, trace } = await import('../js/map/projection.js');
const { areaAt } = await import('../js/map/hit.js');
const { territoryDrawing } = await import('../js/views/realism-territory.js');

const WORLD = JSON.parse(readFileSync(new URL('../../worlds/maps/autumn-1941.json', import.meta.url)));
const BOX = boxOf(WORLD.box);
const DESK = { width: 960, height: 740 };
const near = (a, b, eps = 5e-5) => Math.abs(a - b) <= eps;

/** The seat's map block for a map file: each area land, in one region. */
const blockOf = (shapes) => ({
  coords: shapes.coords, box: shapes.box, marks: [], places: [], regions: [{ key: 'r', name: 'R', parent: null }],
  areas: Object.keys(shapes.areas).map((key) => ({ key, name: key, kind: 'land', region: 'r', terrain: 'plain', neighbours: [] })),
});

/** The rings of an SVG path `d` (M ... L ... Z), as lists of points. */
const ringsOf = (d) => d.split('M').filter(Boolean).map((r) => r.replace(/Z$/, '').split('L').map((p) => p.trim().split(/\s+/).map(Number)));

/** Even-odd: inside an odd number of `rings`. */
function inside(rings, [x, y]) {
  let odd = false;
  for (const pts of rings) {
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i, i += 1) {
      const [xi, yi] = pts[i];
      const [xj, yj] = pts[j];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) odd = !odd;
    }
  }
  return odd;
}

// --- Rule 1: the chosen projection, centred on the box, forward and inverse ---------------

test('forward then inverse returns the point, to four decimals, over a grid of the 1941 box', () => {
  const proj = territoryProjection('lonlat', BOX);
  let n = 0;
  for (let lon = BOX.west; lon <= BOX.east; lon += 7.5) {
    for (let lat = BOX.south; lat <= BOX.north; lat += 3.5) {
      const [x, y] = proj.invert(proj.point([lon, lat]));
      assert.ok(near(x, lon) && near(y, lat), `${lon}, ${lat} came back as ${x}, ${y}`);
      n += 1;
    }
  }
  assert.ok(n > 1000);
});

// The Accept line asks for half: that is the figure of a projection true along its parallels.
// Equal Earth keeps area instead, so a degree's cell at 60 north is half the equator's, and its
// width is Equal Earth's own 0.753 of the equator's.
test('the high north is not drawn too big: a degree at 60 north covers half the equator\'s, within 5 percent', () => {
  const proj = territoryProjection('lonlat', BOX);
  const mid = (BOX.west + BOX.east) / 2;
  const cell = (lat) => {
    const [a, b, c] = [proj.point([mid - 0.5, lat - 0.5]), proj.point([mid + 0.5, lat - 0.5]), proj.point([mid - 0.5, lat + 0.5])];
    return { w: b[0] - a[0], area: Math.abs((b[0] - a[0]) * (c[1] - a[1])) };
  };
  const area = cell(60).area / cell(0).area;
  assert.ok(Math.abs(area - 0.5) <= 0.025, `a degree's cell at 60 north is ${area.toFixed(3)} of one at the equator`);
  const width = cell(60).w / cell(0).w;
  assert.ok(Math.abs(width - 0.7534) <= 0.0377, `a degree at 60 north is ${width.toFixed(3)} as wide as one at the equator`);
});

test('the map is centred on the middle longitude of its own box', () => {
  const proj = territoryProjection('lonlat', BOX);
  const mid = (BOX.west + BOX.east) / 2;
  assert.ok(near(proj.point([mid, 0])[0], proj.width / 2, 1e-9), 'the middle meridian is the middle of the drawing');
  const [w, e] = [proj.point([BOX.west, 0])[0], proj.point([BOX.east, 0])[0]];
  assert.ok(near(w, 0, 0.01) && near(e, proj.width, 0.01), 'the edges at the equator are the drawing\'s edges');
  assert.ok(proj.point([BOX.west, BOX.north])[0] > proj.point([BOX.west, 0])[0], 'the meridians lean in towards the pole');
});

test('a flat map is a plain scale, with an inverse, and is never curved', () => {
  const box = { west: 10, south: 20, east: 310, north: 220 };
  const proj = territoryProjection('flat', box);
  assert.deepEqual(proj.point([60, 40]), [50, 180]);
  assert.deepEqual(proj.invert([50, 180]), [60, 40]);
  assert.deepEqual([proj.width, proj.height], [300, 200]);
  assert.deepEqual(trace(proj, [[10, 20], [310, 20]]), [[0, 200], [300, 200]], 'a flat edge is not cut');
});

// --- Rule 5: three functions, one constant -------------------------------------------------

test('the three functions the spike proved stay in the module, each with an inverse; one constant picks Equal Earth', () => {
  assert.deepEqual(Object.keys(PROJECTIONS).sort(), ['equal-earth', 'miller', 'natural-earth']);
  assert.equal(MAP_PROJECTION, 'equal-earth');
  for (const [name, f] of Object.entries(PROJECTIONS)) {
    for (const [l, p] of [[0, 0], [120, 45], [-170, -60], [33.3, 71.5], [179, 10]]) {
      const [x, y] = f.inverse(...f.forward(l, p));
      assert.ok(near(x, l) && near(y, p), `${name}: ${l}, ${p} came back as ${x}, ${y}`);
    }
  }
  const proj = territoryProjection('lonlat', BOX);
  const mid = (BOX.west + BOX.east) / 2;
  const [x0, y0] = PROJECTIONS['equal-earth'].forward(100, 40);
  const [x1, y1] = PROJECTIONS['equal-earth'].forward(0, 0);
  const [px, py] = proj.point([mid + 100, 40]);
  const [qx, qy] = proj.point([mid, 0]);
  assert.ok(near(px - qx, x0 - x1, 1e-9) && near(qy - py, y0 - y1, 1e-9), 'the drawing uses the constant\'s function');
});

// --- Long edges are curves, not chords -----------------------------------------------------

test('an edge longer than a degree is cut into one-degree steps before it is projected', () => {
  const proj = territoryProjection('lonlat', BOX);
  const line = trace(proj, [[60, 60], [120, 60]]);
  assert.equal(line.length, 61);
  const chordY = (line[0][1] + line.at(-1)[1]) / 2;
  assert.ok(Math.abs(line[30][1] - chordY) < 1e-9, 'a parallel stays straight in Equal Earth');
  const meridian = trace(proj, [[200, -10], [200, 70]]);
  const [a, b, m] = [meridian[0], meridian.at(-1), meridian[40]];
  const chordX = a[0] + ((b[0] - a[0]) * (m[1] - a[1])) / (b[1] - a[1]);
  assert.ok(Math.abs(m[0] - chordX) > 0.5, 'a far meridian is drawn as the curve it is');
});

// --- Rule 3: frames, labels and marks at their projected places ----------------------------

test('a region\'s frame is the box around its corners and edges as projected', () => {
  const proj = territoryProjection('lonlat', BOX);
  const frame = { west: 150, south: -10, east: 230, north: 70 };
  const rect = frameRect(frame, proj);
  const edge = trace(proj, [[150, -10], [230, -10], [230, 70], [150, 70], [150, -10]]);
  const xs = edge.map(([x]) => x); const ys = edge.map(([, y]) => y);
  assert.ok(near(rect.x, Math.min(...xs), 1e-9) && near(rect.y, Math.min(...ys), 1e-9));
  assert.ok(near(rect.x + rect.w, Math.max(...xs), 1e-9) && near(rect.y + rect.h, Math.max(...ys), 1e-9));
  assert.ok(rect.x + rect.w >= proj.point([230, 0])[0] - 1e-9, 'the east edge bulges at the equator, between the corners');
  const whole = frameRect(BOX, proj);
  assert.ok(near(whole.x, 0, 1e-9) && near(whole.y, 0, 1e-9) && near(whole.w, proj.width, 1e-9) && near(whole.h, proj.height, 1e-9));
});

test('each 1941 area\'s label point falls inside its own projected shape', () => {
  const proj = territoryProjection('lonlat', BOX);
  const pic = territoryDrawing(blockOf(WORLD), WORLD, { px: DESK, still: true });
  const paths = new Map(pic.querySelectorAll('path.rl-area').map((p) => [p.getAttribute('data-area'), ringsOf(p.getAttribute('d'))]));
  const labels = pic.querySelectorAll('g.rl-tm-label');
  assert.equal(labels.length, Object.keys(WORLD.areas).length);
  for (const l of labels) {
    const key = l.getAttribute('data-area');
    const xy = [Number(l.getAttribute('data-x')), Number(l.getAttribute('data-y'))];
    const [lx, ly] = proj.point(WORLD.areas[key].label);
    assert.ok(near(xy[0], lx, 0.006) && near(xy[1], ly, 0.006), `${key}: the label is at its projected point`);
    assert.ok(inside(paths.get(key), xy), `${key}: its label point is inside its drawn shape`);
  }
});

// --- Rule 2: a tap is turned back by the inverse -------------------------------------------

const TOY = {
  format: 1, coords: 'lonlat', box: [20, 50, 40, 60],
  vertices: [[20, 50], [30, 50], [30, 60], [20, 60], [40, 50], [40, 60]],
  areas: { west: { rings: [[0, 1, 2, 3, 0]], label: [25, 55] }, east: { rings: [[1, 4, 5, 2, 1]], label: [35, 55] } },
  backdrop: [],
};

test('areaAt(): a point in the drawing is turned back into longitude and latitude before the area test', () => {
  const proj = territoryProjection('lonlat', boxOf(TOY.box));
  assert.equal(areaAt(TOY, proj, proj.point([26, 51]), ['west', 'east']), 'west');
  assert.equal(areaAt(TOY, proj, proj.point([39, 59]), ['west', 'east']), 'east');
  assert.equal(areaAt(TOY, proj, [-5, -5], ['west', 'east']), null);
});

test('a tap on the drawing picks the area under it, at every zoom', () => {
  for (const zoom of [1, 2, 4]) {
    for (const [lon, lat, want] of [[21, 51, 'west'], [29, 59, 'west'], [31, 51, 'east'], [38, 57, 'east']]) {
      const picked = [];
      const proj = territoryProjection('lonlat', boxOf(TOY.box));
      const centre = proj.point([30, 55]);
      const pic = territoryDrawing(blockOf(TOY), TOY, { px: DESK, zoom, centre, onArea: (key) => picked.push(key) });
      const [vx, vy, vw, vh] = pic.getAttribute('viewBox').split(' ').map(Number);
      const k = vw / 400;
      pic.getBoundingClientRect = () => ({ left: 0, top: 0, width: 400, height: vh / k });
      const [ux, uy] = proj.point([lon, lat]);
      if (ux < vx || ux > vx + vw || uy < vy || uy > vy + vh) continue;
      const [cx, cy] = [(ux - vx) / k, (uy - vy) / k];
      const ev = (type) => ({ type, pointerId: 1, clientX: cx, clientY: cy, target: pic, preventDefault() {}, stopPropagation() {} });
      pic.dispatchEvent(ev('pointerdown'));
      pic.dispatchEvent(ev('pointerup'));
      assert.deepEqual(picked, [want], `zoom ${zoom}: a tap at ${lon}, ${lat}`);
    }
  }
});

test('a tap on an area\'s own shape is its shape\'s, told once', () => {
  const picked = [];
  const pic = territoryDrawing(blockOf(TOY), TOY, { px: DESK, onArea: (key) => picked.push(key) });
  const west = pic.querySelector('path.rl-area[data-area="west"]');
  const [vx, vy, vw, vh] = pic.getAttribute('viewBox').split(' ').map(Number);
  const k = vw / 400;
  pic.getBoundingClientRect = () => ({ left: 0, top: 0, width: 400, height: vh / k });
  const [ux, uy] = territoryProjection('lonlat', boxOf(TOY.box)).point([25, 55]);
  const ev = (type) => ({ type, pointerId: 1, clientX: (ux - vx) / k, clientY: (uy - vy) / k, target: west, preventDefault() {}, stopPropagation() {} });
  pic.dispatchEvent(ev('pointerdown'));
  pic.dispatchEvent(ev('pointerup'));
  west.click();
  assert.deepEqual(picked, ['west']);
});

// --- Rule 4: nothing is cut at the map's edge longitude ------------------------------------

test('an area and the backdrop across the map\'s edge longitude are drawn once and unbroken', () => {
  const box = [-126, -11.5, 234, 71.5];
  const shapes = {
    format: 1, coords: 'lonlat', box,
    vertices: [[230, 40], [238, 40], [238, 50], [230, 50], [-130, 10], [-120, 10], [-120, 20], [-130, 20]],
    areas: { across: { rings: [[0, 1, 2, 3, 0]], label: [232, 45] } },
    backdrop: [[4, 5, 6, 7, 4]],
  };
  const pic = territoryDrawing(blockOf(shapes), shapes, { px: DESK, still: true });
  const proj = territoryProjection('lonlat', boxOf(box));
  const jump = (rings) => Math.max(...rings.flatMap((pts) => pts.slice(1).map((p, i) => Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]))));
  const areas = pic.querySelectorAll('path.rl-area');
  assert.equal(areas.length, 1, 'drawn once');
  const rings = ringsOf(areas[0].getAttribute('d'));
  assert.equal(rings.length, 1, 'one ring, not split at the edge');
  assert.ok(jump(rings) < proj.width / 2, 'no step runs back across the map');
  const back = pic.querySelectorAll('path.rl-tm-backdrop');
  assert.equal(back.length, 1);
  assert.ok(jump(ringsOf(back[0].getAttribute('d'))) < proj.width / 2, 'the backdrop is unbroken too');
});
