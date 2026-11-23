// Land not in play drawn as land: where a longitude-latitude map has a backdrop, the coastline file the
// repository already serves is drawn inside the map's box under the areas, in a tone for land that is not
// in play; it takes no tap and has no label; a flat map and a map with no backdrop draw as before.
// Run: node --test web/test/

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { theatreBoard, forgetShapes } = await import('../js/views/realism-theatre.js');
const { territoryDrawing } = await import('../js/views/realism-territory.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const FLAT = JSON.parse(readFileSync(new URL('./fixtures/toy.map.json', import.meta.url)));
const CSS_TEXT = readFileSync(new URL('../css/c-map.css', import.meta.url), 'utf8');
const DESK = { width: 960, height: 740 };

const lonlat = (backdrop) => ({
  format: 1, coords: 'lonlat', box: [20, 50, 40, 60],
  vertices: [[20, 50], [30, 50], [30, 60], [20, 60], [40, 50], [40, 60], [22, 52], [24, 52], [24, 54]],
  areas: { west: { rings: [[0, 1, 2, 3, 0]], label: [25, 55] }, east: { rings: [[1, 4, 5, 2, 1]], label: [35, 55] } },
  backdrop,
});
const BACKDROP = [[6, 7, 8, 6]];
const block = (shapes) => ({
  coords: shapes.coords, box: shapes.box, marks: [], places: [], regions: [{ key: 'r', name: 'R', parent: null }],
  areas: ['west', 'east'].map((key) => ({ key, name: key, kind: 'land', region: 'r', terrain: 'plain', neighbours: [] })),
});
// one island inside the box, one far outside it, one just east of the antimeridian's far side
const COAST = { rings: [
  [[26, 52], [28, 52], [28, 54], [26, 54], [26, 52]],
  [[-100, -10], [-90, -10], [-90, 0], [-100, 0], [-100, -10]],
] };
const draw = (shapes, coast, map = block(shapes)) => territoryDrawing(map, shapes, { px: DESK, coast });
const landOf = (pic) => pic.querySelectorAll('path.rl-tm-notland');
const order = (pic) => pic.querySelectorAll('path').map((p) => p.getAttribute('class'));

test('rule 1: the land inside the box is drawn under the areas, and none outside it', () => {
  const pic = draw(lonlat(BACKDROP), COAST);
  const land = landOf(pic);
  assert.equal(land.length, 1);
  const d = land[0].getAttribute('d');
  assert.equal(d.split('M').filter(Boolean).length, 1, 'the island in the box, not the one far outside it');
  const classes = order(pic);
  const at = classes.indexOf('rl-tm-notland');
  assert.ok(at >= 0 && classes.slice(0, at).every((c) => c !== 'rl-area rl-area-land'), 'before every area');
  assert.ok(classes.indexOf('rl-area rl-area-land') > at, 'the areas come after it');
  assert.ok(at < classes.indexOf('rl-tm-backdrop'), 'under the backdrop too');
});

test('rule 1: land past the box edge on the far side of the antimeridian is brought in', () => {
  const wide = { ...lonlat(BACKDROP), box: [-126, -11.5, 234, 71.5] };
  const east = { rings: [[[-170, 10], [-165, 10], [-165, 15], [-170, 15], [-170, 10]]] };
  const pic = draw(wide, east);
  assert.equal(landOf(pic)[0]?.getAttribute('d').split('M').filter(Boolean).length, 1, '-170 is 190 on this map');
});

test('rule 2: the land takes no tap, has no label and is not read out', () => {
  const pic = draw(lonlat(BACKDROP), COAST);
  const land = landOf(pic)[0];
  assert.equal(land.getAttribute('aria-hidden'), 'true');
  for (const a of ['data-area', 'tabindex', 'role', 'aria-label', 'data-text']) assert.equal(land.getAttribute(a), null, a);
  assert.match(CSS_TEXT, /\.rl-tm-notland\s*\{[^}]*pointer-events:\s*none/);
  assert.equal(pic.querySelectorAll('.rl-area').length, 2, 'the same two areas as before');
  assert.ok(!words(pic).includes('Land'), 'no word of its own');
});

test('rule 2: the tone is from the theme, drawn as land and as not in play', () => {
  const rule = CSS_TEXT.match(/\.rl-tm-notland\s*\{([^}]*)\}/)?.[1] ?? '';
  assert.match(rule, /fill:\s*var\(--chart-land\)/);
  assert.match(rule, /opacity:\s*0\.\d+/, 'dimmer than land in play');
  assert.doesNotMatch(rule, /#|rgb\(|hsl\(/);
});

test('rule 3: a flat map is drawn as today', () => {
  const pic = territoryDrawing({ ...block(FLAT), coords: 'flat', box: FLAT.box, areas: [] }, FLAT, { px: DESK, coast: COAST });
  assert.equal(landOf(pic).length, 0);
});

test('rule 4: a map with no backdrop draws nothing extra, and so does one with no coastline yet', () => {
  assert.equal(landOf(draw(lonlat([]), COAST)).length, 0);
  assert.equal(landOf(draw(lonlat(BACKDROP), null)).length, 0);
  assert.equal(landOf(draw(lonlat(BACKDROP), { rings: [] })).length, 0);
});

test('the board fetches the coastline file for a backdrop map and draws it when it lands; never for others', async () => {
  const shapes = lonlat(BACKDROP);
  const hash = fixture.territory_map.file.sha256;
  const run = async (mapShapes) => {
    forgetShapes();
    const asked = [];
    const was = globalThis.fetch;
    globalThis.fetch = async (url) => {
      asked.push(url);
      const body = url === '/api/realism/map' ? { reply: '', refused: false, file: fixture.territory_map.file, map: mapShapes }
        : url === '/assets/land-110m.json' ? COAST : {};
      return { ok: true, status: 200, json: async () => structuredClone(body) };
    };
    try {
      const seat = { ...fixture, map: { ...structuredClone(fixture.territory_map), ...block(mapShapes), file: { name: 'x', sha256: hash } } };
      const view = theatreBoard(seat, { piece: null, theatre: { mode: 'map', scope: 'reports' } }, { pick: () => {}, act: () => {} });
      document.body.append(view);
      for (let i = 0; i < 6; i += 1) await new Promise((ok) => setTimeout(ok, 0));
      const fig = document.body.querySelector('figure.rl-map-figure');
      const n = fig ? landOf(fig).length : -1;
      view.remove();
      return { asked, n };
    } finally { globalThis.fetch = was; }
  };
  const some = await run(shapes);
  assert.ok(some.asked.includes('/assets/land-110m.json'));
  assert.equal(some.n, 1);
  const none = await run(lonlat([]));
  assert.ok(!none.asked.includes('/assets/land-110m.json'), 'no backdrop, no coastline fetched');
  assert.equal(none.n, 0);
});
