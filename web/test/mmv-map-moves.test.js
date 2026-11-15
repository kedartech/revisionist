// Moves picked on the map: while a form that moves a force is open on the theatre board, each
// place the form offers is lit on the map with its days; a click on a lit place sets the form's
// destination, and a place the form does not offer does nothing. The list picker stays, in step
// with the map both ways. A place reached by sea shows the tonnage the lift needs and the
// tonnage reported, or that none is reported yet, on the map and in the list.
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { buttons, fire, installDom, words } from './dom-fake.js';

installDom();
globalThis.window = globalThis;
globalThis.CSS = { escape: (s) => s };
// The fake does not reflect `hidden`, which the Draft toggle reads; this file's process only.
Object.defineProperty(Object.getPrototypeOf(document.createElement('div')), 'hidden', {
  get() { return this.hasAttribute('hidden'); },
  set(v) { if (v) this.setAttribute('hidden', ''); else this.removeAttribute('hidden'); },
});
const { theatreBoard } = await import('../js/views/realism-theatre.js');
const { liftLabel } = await import('../js/views/realism-forms.js');

const fixture = JSON.parse(readFileSync(new URL('./fixtures/realism-seat.json', import.meta.url)));
const FLEET = 'us_atlantic_fleet';
const piece = { kind: 'force', name: 'US Atlantic Fleet' };

// The fixture's map holds only some places; a game's map holds every located place.
const MORE = [
  { name: 'Argentia', lat: 47.3, lon: -54.0, theatre: 'North America' },
  { name: 'Norfolk', lat: 36.9, lon: -76.3, theatre: 'North America' },
  { name: 'Tokyo', lat: 35.7, lon: 139.7, theatre: 'Asia-Pacific' },
];

/** The seat with every offered place on its map; `edit(places)` changes the form's places. */
function seat(edit = () => {}) {
  const rv = structuredClone(fixture);
  rv.map.places = [...rv.map.places, ...MORE];
  const lever = rv.desk.levers.find((l) => l.name === 'move_fleet');
  edit(lever.params.find((p) => p.places?.length).places);
  return rv;
}

const offered = fixture.desk.levers.find((l) => l.name === 'move_fleet').params.find((p) => p.places?.length).places;
const ui = (theatre = {}, picked = piece) => ({ piece: picked, theatre: { mode: 'map', scope: 'world', layer: 'military', ...theatre } });
const board = (rv, u = ui(), more = {}) => theatreBoard(rv, u, { pick: () => {}, act: () => {}, ...more });
const targets = (view) => view.querySelectorAll('.rl-map-svg .rl-map-target');
const target = (view, name) => targets(view).find((t) => t.getAttribute('data-place') === name);
const form = (view) => view.querySelector('.rl-theatre-forms .rl-instrument');
const field = (view) => form(view).querySelector('input[name="to"]');
const radio = (view, value) => form(view).querySelectorAll('input[type="radio"]').find((r) => r.value === value);
const draft = (view) => buttons(form(view), 'Draft')[0];

test('while a form that moves a force is open, every place it offers is lit on the map with its days', () => {
  const view = board(seat());
  assert.deepEqual(targets(view).map((t) => t.getAttribute('data-place')).sort(), offered.map((p) => p.label).sort());
  assert.match(words(target(view, 'Argentia')), /5 days/);
  assert.match(words(target(view, 'Norfolk')), /There now/);
  assert.match(words(target(view, 'Tokyo')), /38 days/);
  assert.match(target(view, 'Argentia').getAttribute('aria-label'), /Argentia.*5 days/);
  draft(view).click();
  assert.equal(targets(view).length, 0, 'a closed form lights nothing');
  draft(view).click();
  assert.equal(targets(view).length, offered.length, 'opened again, lit again');
  assert.equal(targets(board(seat(), ui({}, null))).length, 0, 'nothing picked lights nothing');
  assert.equal(targets(board(seat(), ui({ layer: 'diplomatic' }))).length, 0, 'the Diplomatic layer lights nothing');
});

test('a lit place outside the reports\' box is still drawn: the box takes in what the form offers', () => {
  const view = board(seat(), ui({ scope: 'reports' }));
  assert.deepEqual(targets(view).map((t) => t.getAttribute('data-place')).sort(), offered.map((p) => p.label).sort());
});

test('clicking a lit place sets the form\'s destination; a place the form does not offer does nothing', () => {
  const filed = [];
  const view = board(seat(), ui(), { act: (_w, _k, v) => filed.push(v) });
  target(view, 'Argentia').click();
  assert.equal(field(view).value, 'argentia');
  const plain = view.querySelector('.rl-map-svg .rl-map-place[data-place="Reykjavik"]');
  assert.ok(plain, 'Reykjavik is on the map');
  assert.equal(target(view, 'Reykjavik'), undefined, 'not offered, not lit');
  plain.click();
  assert.equal(field(view).value, 'argentia', 'a click on a place not offered changes nothing');
  const key = { key: 'Enter', preventDefault() {} };
  for (const fn of target(view, 'Halifax').listeners.get('keydown') ?? []) fn(key);
  assert.equal(field(view).value, 'halifax_port', 'Enter on a lit place picks it too');
  const f = form(view).querySelector('form');
  const query = f.querySelector.bind(f);
  f.querySelector = (s) => (s.startsWith('#') ? f.querySelectorAll('[id]').find((e) => e.id === s.slice(1)) ?? null : query(s));
  fire(f, 'submit');
  assert.deepEqual(filed, [{ lever: 'move_fleet', params: { force: FLEET, to: 'halifax_port' } }]);
});

test('a refused place is lit as out of reach and a click on it does nothing', () => {
  const view = board(seat((places) => {
    places.find((p) => p.value === 'tokyo').reach[FLEET] = { tier: 'refused', base: 'pearl_harbor_base', reason: 'Too far from Pearl Harbor.' };
  }));
  const tokyo = target(view, 'Tokyo');
  assert.match(words(tokyo), /Out of reach/);
  assert.equal(tokyo.getAttribute('aria-disabled'), 'true');
  tokyo.click();
  assert.equal(field(view).value, '');
});

test('the list picker stays and stays in step with the map', () => {
  const view = board(seat());
  assert.equal(form(view).querySelectorAll('input[type="radio"]').length, offered.length, 'the list is still there');
  const scapa = radio(view, 'scapa_flow');
  scapa.checked = true;
  fire(scapa, 'change');
  assert.equal(target(view, 'Scapa Flow').getAttribute('aria-pressed'), 'true', 'picked in the list, marked on the map');
  assert.equal(target(view, 'Halifax').getAttribute('aria-pressed'), 'false');
  target(view, 'Halifax').click();
  assert.equal(radio(view, 'halifax_port').checked, true, 'picked on the map, checked in the list');
  assert.equal(radio(view, 'scapa_flow').checked, false);
  const force = form(view).querySelector('select[name="force"]');
  force.value = 'us_pacific_fleet';
  fire(force, 'change');
  assert.doesNotMatch(words(target(view, 'Argentia')), /5 days/, 'the map\'s days follow the form\'s force');
});

test('a place reached by sea shows the tonnage the lift needs and the tonnage reported, or not yet reported', () => {
  const view = board(seat((places) => {
    places.find((p) => p.value === 'argentia').lift[FLEET] = { need: 40000, reported: 1200000 };
    places.find((p) => p.value === 'tokyo').lift[FLEET] = { need: 40000, reported: null };
  }));
  assert.match(words(target(view, 'Argentia')), /By sea: needs 40,000 GRT; 1,200,000 GRT reported free/);
  assert.match(words(target(view, 'Tokyo')), /By sea: needs 40,000 GRT; not yet reported/);
  const notes = (name) => target(view, name).querySelectorAll('text.rl-target-note').map(words);
  assert.deepEqual(notes('Argentia'), ['5 days', 'Lift 40,000 GRT · 1,200,000 GRT free'], 'beside the ring, short');
  assert.deepEqual(notes('Tokyo'), ['38 days', 'Lift 40,000 GRT · not yet reported']);
  assert.match(target(view, 'Argentia').getAttribute('aria-label'), /By sea: needs 40,000 GRT; 1,200,000 GRT reported free/);
  assert.doesNotMatch(words(target(view, 'Norfolk')), /By sea|Lift/, 'a place reached without a lift says nothing of one');
  const leg = target(view, 'Argentia').querySelector('path.rl-map-sealeg');
  assert.ok(leg, 'a sea leg is drawn to a place reached by sea');
  const dot = view.querySelector('.rl-map-place[data-place="Reykjavik"] circle');
  const [rx, ry] = ['cx', 'cy'].map((k) => Number(dot.getAttribute(k)));
  const [lx, ly] = leg.getAttribute('d').match(/^M([-\d.]+) ([-\d.]+)L/).slice(1).map(Number);
  assert.ok(Math.abs(lx - rx) < 0.05 && Math.abs(ly - ry) < 0.05, 'from where the seat\'s page places the force');
  assert.equal(target(view, 'Norfolk').querySelector('path.rl-map-sealeg'), null, 'no sea leg without a lift');
  const row = radio(view, 'argentia').closest('li');
  assert.match(words(row), /needs 40,000 GRT; 1,200,000 GRT reported free/, 'the list says it too');
  assert.match(words(radio(view, 'tokyo').closest('li')), /not yet reported/);
  assert.equal(liftLabel(null), null);
});

test('c-map.css draws lit places with tokens only; p5-forms.css places the lift line', () => {
  const strip = (f) => readFileSync(new URL(`../css/${f}`, import.meta.url), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  const map = strip('c-map.css');
  for (const sel of ['.rl-map-target', '.rl-map-target.chosen', '.rl-map-target.refused', '.rl-map-target:focus-visible']) {
    assert.ok(map.includes(sel), `a rule for ${sel}`);
  }
  assert.doesNotMatch(map, /#[0-9a-fA-F]{3,8}\b/, 'tokens only');
  assert.ok(strip('p5-forms.css').includes('.rl-place-lift'), 'a rule for the lift line');
});
