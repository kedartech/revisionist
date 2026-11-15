// The theatre board: the map fills the board, each theatre a labelled rounded box around its
// places; a Military or Diplomatic layer; a picked force shows the forms that can move it, a
// picked capital opens its leader's figure card; the list of marks stays. Only what the
// seat's map holds is drawn.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
const { theatreBoard } = await import('../js/views/realism-theatre.js');
const { mapDrawing } = await import('../js/views/realism-map.js');
const { capitalLine, formsMoving, theatreAreas } = await import('../js/realism-rules.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const rv = (map = {}) => ({ ...fixture, map: { ...fixture.map, ...map } });
const ui = (theatre = {}, piece = null) => ({ piece, theatre: { mode: 'map', scope: 'world', ...theatre } });
const board = (r, u, more = {}) => theatreBoard(r, u, { pick: () => {}, act: () => {}, ...more });
const texts = (el) => el.querySelectorAll('text').map(words);
const pressed = (group) => group.querySelectorAll('button').filter((b) => b.getAttribute('aria-pressed') === 'true').map(words);
const layerGroup = (el) => el.querySelectorAll('[role="group"]').find((g) => g.getAttribute('aria-label') === 'Layer');

test('theatreAreas: one area a theatre, a box around its places; a place with no theatre is in none', () => {
  const areas = theatreAreas([
    { name: 'A', lat: 10, lon: 20, theatre: 'East' },
    { name: 'B', lat: 30, lon: 40, theatre: 'East' },
    { name: 'C', lat: -5, lon: -60, theatre: 'West' },
    { name: 'D', lat: 0, lon: 0, theatre: null },
  ]);
  assert.deepEqual(areas, [
    { name: 'East', parts: [{ west: 20, east: 40, south: 10, north: 30 }] },
    { name: 'West', parts: [{ west: -60, east: -60, south: -5, north: -5 }] },
  ]);
});

test('theatreAreas: a theatre closer across the date line than around the map is drawn in two parts', () => {
  const [area] = theatreAreas([
    { name: 'Tokyo', lat: 35.7, lon: 139.7, theatre: 'Asia-Pacific' },
    { name: 'Manila', lat: 14.6, lon: 121.0, theatre: 'Asia-Pacific' },
    { name: 'Pearl Harbor', lat: 21.4, lon: -158.0, theatre: 'Asia-Pacific' },
  ]);
  assert.deepEqual(area.parts, [
    { west: 121.0, east: 139.7, south: 14.6, north: 35.7 },
    { west: -158.0, east: -158.0, south: 21.4, north: 21.4 },
  ]);
  const [plain] = theatreAreas([
    { name: 'Halifax', lat: 44.6, lon: -63.6, theatre: 'North America' },
    { name: 'Washington', lat: 38.9, lon: -77.0, theatre: 'North America' },
  ]);
  assert.equal(plain.parts.length, 1);
});

test('the map fills the board: each theatre is a labelled rounded box, none for a place without one', () => {
  const view = board(rv(), ui());
  assert.ok(view.classList.contains('rl-theatre'), 'the theatre board');
  assert.equal(view.querySelector('.rl-map-detail'), null, 'the piece is in the side panel, not under the map');
  const areas = view.querySelectorAll('.rl-map-svg .rl-theatre-area');
  const named = [...new Set(fixture.map.places.map((p) => p.theatre).filter(Boolean))].sort();
  assert.deepEqual(areas.map((a) => a.getAttribute('data-theatre')), named);
  for (const a of areas) {
    const box = a.querySelector('rect');
    assert.ok(Number(box.getAttribute('rx')) > 0, 'a rounded box');
    assert.equal(words(a.querySelector('text')), a.getAttribute('data-theatre'), 'labelled with its name');
  }
  const none = board(rv({ places: fixture.map.places.map((p) => ({ ...p, theatre: null })) }), ui());
  assert.equal(none.querySelectorAll('.rl-theatre-area').length, 0);
});

test('a theatre box encloses its own places on the drawing', () => {
  const view = board(rv(), ui());
  const area = view.querySelectorAll('.rl-theatre-area').find((a) => a.getAttribute('data-theatre') === 'North Atlantic');
  const box = area.querySelector('rect');
  const [x, y, w, hgt] = ['x', 'y', 'width', 'height'].map((k) => Number(box.getAttribute(k)));
  const inside = fixture.map.places.filter((p) => p.theatre === 'North Atlantic').map((p) => p.name);
  const dots = view.querySelectorAll('.rl-map-place').filter((g) => inside.includes(g.getAttribute('data-place')));
  assert.equal(dots.length, inside.length);
  for (const g of dots) {
    const c = g.querySelector('circle');
    const [cx, cy] = [Number(c.getAttribute('cx')), Number(c.getAttribute('cy'))];
    assert.ok(cx > x && cx < x + w && cy > y && cy < y + hgt, `${g.getAttribute('data-place')} inside its theatre`);
  }
});

test('the desk\'s and the wake\'s drawings draw no theatres', () => {
  assert.equal(mapDrawing(fixture.map, null, { scope: 'world' }).querySelectorAll('.rl-theatre-area').length, 0);
  assert.equal(mapDrawing(fixture.map, null, { still: true, compact: true }).querySelectorAll('.rl-theatre-area').length, 0);
});

test('a layer switch: Military first and pressed; Diplomatic picks the layer, keeping the map\'s switches', () => {
  const picked = [];
  const view = board(rv(), ui(), { pick: (p) => picked.push(p) });
  const group = layerGroup(view);
  assert.ok(group, 'a group named Layer');
  assert.deepEqual(group.querySelectorAll('button').map(words), ['Military', 'Diplomatic']);
  assert.deepEqual(pressed(group), ['Military']);
  buttons(group, 'Diplomatic')[0].click();
  assert.deepEqual(picked, [{ theatre: { mode: 'map', scope: 'world', layer: 'diplomatic' } }]);
  assert.deepEqual(pressed(layerGroup(board(rv(), ui({ layer: 'diplomatic' })))), ['Diplomatic']);
});

test('Military: forces, routes and orders as today, and no capital', () => {
  const view = board(rv(), ui({ layer: 'military' }));
  assert.equal(view.querySelectorAll('.rl-map-svg .rl-mk').length, fixture.map.marks.length);
  assert.equal(view.querySelectorAll('.rl-map-svg .rl-mk-order').length, fixture.map.orders.length);
  assert.equal(view.querySelectorAll('.rl-cap').length, 0);
});

test('Diplomatic: a mark at each capital with the leader, the stance word and step, and no force', () => {
  const view = board(rv(), ui({ layer: 'diplomatic' }));
  assert.equal(view.querySelectorAll('.rl-map-svg .rl-mk').length, 0, 'no force, route or front');
  assert.equal(view.querySelectorAll('.rl-map-svg .rl-mk-order').length, 0, 'no order arrow');
  const caps = view.querySelectorAll('.rl-map-svg .rl-cap');
  assert.deepEqual(caps.map((c) => c.getAttribute('data-leader')), fixture.map.capitals.map((c) => c.name));
  const hitler = caps[0];
  assert.match(words(hitler), /Adolf Hitler/);
  assert.match(words(hitler), /Hostile, 1 of 5/);
  assert.match(hitler.getAttribute('aria-label'), /Berlin/);
  assert.equal(capitalLine(fixture.map.capitals[1]), 'Joseph Stalin, Moscow: Cooperative, 4 of 5');
});

test('a capital at war carries a war mark; one at peace has none', () => {
  const [hitler, stalin] = fixture.map.capitals;
  const view = board(rv({ capitals: [{ ...hitler, at_war: true }, stalin] }), ui({ layer: 'diplomatic' }));
  const [h1, s1] = view.querySelectorAll('.rl-cap');
  assert.ok(h1.querySelector('.rl-cap-war'), 'the war mark');
  assert.match(h1.getAttribute('aria-label'), /at war/);
  assert.equal(s1.querySelector('.rl-cap-war'), null);
  assert.doesNotMatch(s1.getAttribute('aria-label'), /at war/);
  assert.equal(capitalLine({ ...hitler, at_war: true }), 'Adolf Hitler, Berlin: Hostile, 1 of 5, at war');
});

test('a stance with no step shows its word only', () => {
  const [hitler] = fixture.map.capitals;
  const fogged = { ...hitler, stance: { step: null, word: 'Unknown', as_of: null, confidence: null } };
  assert.equal(capitalLine(fogged), 'Adolf Hitler, Berlin: Unknown');
  assert.equal(capitalLine({ ...hitler, stance: { ...hitler.stance, step: 7 } }), 'Adolf Hitler, Berlin: Hostile', 'a step outside 1 to 5 is no step');
});

test('fog: the drawing names only what the seat\'s map holds', () => {
  const map = fixture.map;
  const held = new Set([
    ...map.places.map((p) => p.name), ...map.places.map((p) => p.theatre).filter(Boolean),
    ...map.marks.map((m) => m.name), ...map.orders.flatMap((o) => [`Ordered: ${o.force}`, `Under way: ${o.force}`]),
    ...map.capitals.flatMap((c) => [c.name, c.place.name, `${c.stance.word}, ${c.stance.step} of 5`, 'At war']),
  ]);
  for (const layer of ['military', 'diplomatic']) {
    const svg = board(rv(), ui({ layer })).querySelector('.rl-map-svg');
    for (const t of texts(svg)) assert.ok(held.has(t), `${layer}: "${t}" is not in the seat's map`);
  }
  const bare = board(rv({ capitals: [] }), ui({ layer: 'diplomatic' }));
  assert.equal(bare.querySelectorAll('.rl-cap').length, 0, 'no capital the map does not hold');
  const roster = fixture.people.opponents.map((l) => l.name);
  for (const name of roster) assert.doesNotMatch(words(bare), new RegExp(name), 'the roster alone puts no one on the map');
});

test('picking a capital opens its leader\'s figure card; closing it takes the card away', () => {
  const doc = installDom();
  const view = board(rv(), ui({ layer: 'diplomatic' }));
  doc.body.append(view);
  view.querySelectorAll('.rl-cap')[0].click();
  const card = doc.body.querySelector('dialog.rl-fc');
  assert.ok(card, 'the figure card');
  assert.equal(card.open, true);
  assert.match(words(card), /Adolf Hitler/);
  assert.match(words(card), /Fuehrer and Reich Chancellor/, 'the roster\'s line for that leader');
  card.close();
  assert.equal(doc.body.querySelector('dialog.rl-fc'), null);
});

test('a capital whose leader the roster does not hold is drawn but opens nothing', () => {
  const doc = installDom();
  const view = board({ ...rv(), people: { ...fixture.people, opponents: [] } }, ui({ layer: 'diplomatic' }));
  doc.body.append(view);
  const cap = view.querySelectorAll('.rl-cap')[0];
  assert.equal(cap.getAttribute('role'), 'img', 'a picture, not a button');
  assert.equal(cap.getAttribute('tabindex'), null);
  cap.click();
  assert.equal(doc.body.querySelector('dialog.rl-fc'), null);
});

test('formsMoving: the forms whose force list holds the force, by its name; none for a foreign force', () => {
  const levers = fixture.desk.levers;
  const own = fixture.map.marks.find((m) => m.name === 'US Atlantic Fleet');
  assert.deepEqual(formsMoving(levers, own).map((f) => [f.lever.name, f.force]), [['move_fleet', 'us_atlantic_fleet']]);
  const detachment = { ...own, name: 'US Atlantic Fleet detachment 1' };
  assert.deepEqual(formsMoving(levers, detachment).map((f) => f.force), ['us_atlantic_fleet__d1']);
  const foreign = fixture.map.marks.find((m) => m.name === 'Home Fleet');
  assert.deepEqual(formsMoving(levers, foreign), []);
  assert.deepEqual(formsMoving(levers, { ...own, side: 'other' }), [], 'a foreign mark with the same name is not the seat\'s');
  assert.deepEqual(formsMoving(levers, { ...own, name: 'Atlantic Fleet Train' }), [], 'a name that only shares words is not the force');
});

test('a picked force of the seat\'s shows the forms that can move it, with the force chosen', () => {
  const sent = [];
  const piece = { kind: 'force', name: 'US Atlantic Fleet' };
  const view = board(rv(), ui({ layer: 'military' }, piece), { act: (...a) => sent.push(a) });
  const block = view.querySelector('.rl-theatre-forms');
  assert.ok(block, 'the forms block');
  assert.match(words(block.querySelector('h3')), /US Atlantic Fleet/);
  const forms = block.querySelectorAll('.rl-instrument');
  assert.deepEqual(forms.map((f) => f.getAttribute('data-lever')), ['move_fleet']);
  const select = forms[0].querySelector('select[name="force"]');
  assert.equal(select.value, 'us_atlantic_fleet');
  assert.match(words(forms[0]), /5 days/, 'the place picker follows the chosen force');
});

test('a picked foreign force shows no form; nothing picked shows no form', () => {
  const foreign = board(rv(), ui({}, { kind: 'force', name: 'Home Fleet' }));
  assert.equal(foreign.querySelector('.rl-theatre-forms'), null);
  assert.equal(board(rv(), ui()).querySelector('.rl-theatre-forms'), null);
});

test('the list of marks stays; on Diplomatic it lists the capitals, each opening its card', () => {
  const doc = installDom();
  const list = board(rv(), ui({ mode: 'list', layer: 'military' }));
  assert.equal(list.querySelectorAll('.rl-map-list tbody tr').length, fixture.map.marks.length);
  assert.ok(layerGroup(list), 'the layer switch is there in the list too');
  const dip = board(rv(), ui({ mode: 'list', layer: 'diplomatic' }));
  doc.body.append(dip);
  const rows = dip.querySelectorAll('.rl-map-list tbody tr');
  assert.deepEqual(rows.map((r) => words(r.querySelector('th'))), fixture.map.capitals.map((c) => c.name));
  assert.match(words(rows[0]), /Berlin/);
  assert.match(words(rows[0]), /Hostile, 1 of 5/);
  assert.match(words(rows[0]), /Not at war/, 'the war cell says it in words, with no header on a phone');
  buttons(rows[0], 'Open the card')[0].click();
  assert.match(words(doc.body.querySelector('dialog.rl-fc')), /Adolf Hitler/);
});

test('c-map.css draws theatres and capitals with tokens only, and lets the map fill the board', () => {
  const css = readFileSync(new URL('../css/c-map.css', import.meta.url), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  for (const sel of ['.rl-theatre-area rect', '.rl-theatre-area text', '.rl-cap-shape', '.rl-cap-war', '.rl-theatre .rl-map-svg']) {
    assert.ok(css.includes(sel), `a rule for ${sel}`);
  }
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b/, 'tokens only');
});
