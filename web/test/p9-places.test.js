// The destination picker on a movement form: the places the server sends with the form's
// destination, grouped as it groups them, each with the routed days and the reach of the
// chosen force. A refused place stays listed, cannot be picked, and says why. The server's
// own tests cover a place that is not on the map (tests/test_web_destinations.py).
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { fire, installDom, words } from './dom-fake.js';

installDom();
const { daysLabel, standardForms, tierLabel } = await import('../js/views/realism-forms.js');

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));
const FLEET = 'us_atlantic_fleet';
const fleetLever = fixture.desk.levers.find((l) => l.params.some((p) => p.places?.length));

/** The fixture's fleet form, with Tokyo refused for the Atlantic Fleet. */
function withRefusal() {
  const lever = structuredClone(fleetLever);
  const to = lever.params.find((p) => p.places.length);
  const tokyo = to.places.find((p) => p.value === 'tokyo');
  tokyo.reach[FLEET] = { tier: 'refused', base: 'pearl_harbor_base', reason: 'Too far from Pearl Harbor, the nearest base it can work from.' };
  return lever;
}

/** The desk's forms for `levers`, and what was filed. */
function draw(levers = [fleetLever]) {
  const filed = [];
  const forms = standardForms({ ...fixture.desk, levers }, { onSubmit: (v) => filed.push(v), entities: [] });
  const item = forms.querySelector('.rl-instrument');
  return { forms, item, filed };
}

const chooseForce = (item, value) => {
  const sel = item.querySelector('select[name="force"]');
  sel.value = value;
  fire(sel, 'change');
};
const radios = (item) => item.querySelectorAll('.rl-places input[type="radio"]');
/** A place's row: its label (radio, name, days, tier) and, when refused, the reason under it. */
const row = (item, value) => radios(item).find((r) => r.value === value).closest('li');
const pick = (item, value) => {
  const r = radios(item).find((x) => x.value === value);
  if (r.disabled) return;
  r.checked = true;
  fire(r, 'change');
};
/** Submit the form. The fake DOM has no `#id` selector, which the form's handler reads its fields by. */
const submit = (item) => {
  const form = item.querySelector('form');
  const query = form.querySelector.bind(form);
  form.querySelector = (s) => (s.startsWith('#') ? form.querySelectorAll('[id]').find((e) => e.id === s.slice(1)) ?? null : query(s));
  fire(form, 'submit');
};

test('the fixture has a movement form whose destination carries places', () => {
  assert.ok(fleetLever, 'a lever with places');
});

test('the places are grouped as the server groups them, in its order, each once', () => {
  const { item } = draw();
  const groups = item.querySelectorAll('.rl-place-group').map((g) => ({
    head: words(g.querySelector('.rl-place-group-h')),
    places: g.querySelectorAll('input[type="radio"]').map((r) => r.value),
  }));
  assert.deepEqual(groups, [
    { head: 'Your bases', places: ['argentia', 'norfolk', 'pearl_harbor_base'] },
    { head: 'Allied bases', places: ['scapa_flow'] },
    { head: 'Routes', places: ['halifax_port'] },
    { head: 'Contested', places: ['lorient'] },
    { head: 'Elsewhere', places: ['tokyo'] },
  ]);
});

test('the select the form would have drawn for the destination is gone', () => {
  const { item } = draw();
  assert.equal(item.querySelector('select[name="to"]'), null);
  assert.ok(item.querySelector('select[name="force"]'), 'the force stays a select');
});

test('day labels: there now, one day, n days, no known route', () => {
  assert.equal(daysLabel(0), 'There now');
  assert.equal(daysLabel(1), '1 day');
  assert.equal(daysLabel(13), '13 days');
  assert.equal(daysLabel(null), 'No known route');
});

test('tier labels, each a word', () => {
  assert.equal(tierLabel({ tier: 'sustained' }), 'Sustained');
  assert.equal(tierLabel({ tier: 'operate' }), 'Operate');
  assert.equal(tierLabel({ tier: 'raid' }), 'Raid');
  assert.equal(tierLabel({ tier: 'refused' }), 'Out of reach');
  assert.equal(tierLabel(null), null);
});

test('before a force is chosen, no days or tiers show, and the picker says why', () => {
  const { item } = draw();
  assert.equal(item.querySelectorAll('.rl-place-days').length, 0);
  assert.equal(item.querySelectorAll('.rl-place-tier').length, 0);
  assert.match(words(item.querySelector('.rl-places-hint')), /Choose which fleet/);
});

test('with the force chosen, each place shows its days and its tier for that force', () => {
  const { item } = draw();
  chooseForce(item, FLEET);
  assert.equal(item.querySelector('.rl-places-hint'), null);
  assert.equal(words(row(item, 'norfolk').querySelector('.rl-place-days')), 'There now');
  assert.equal(words(row(item, 'argentia').querySelector('.rl-place-days')), '5 days');
  assert.equal(words(row(item, 'argentia').querySelector('.rl-place-tier')), 'Sustained');
  assert.equal(words(row(item, 'scapa_flow').querySelector('.rl-place-tier')), 'Operate');
  assert.equal(words(row(item, 'tokyo').querySelector('.rl-place-tier')), 'Raid');
  assert.equal(words(row(item, 'tokyo').querySelector('.rl-place-days')), '38 days');
});

test('a force no page places shows no known route and no tier', () => {
  const { item } = draw();
  chooseForce(item, 'us_pacific_fleet');
  assert.equal(words(row(item, 'argentia').querySelector('.rl-place-days')), 'No known route');
  assert.equal(row(item, 'argentia').querySelector('.rl-place-tier'), null);
});

test('a refused place stays listed, cannot be picked, and gives its reason naming the base', () => {
  const { item, filed } = draw([withRefusal()]);
  chooseForce(item, FLEET);
  const tokyo = row(item, 'tokyo');
  const radio = tokyo.querySelector('input[type="radio"]');
  assert.equal(radio.disabled, true);
  assert.ok(tokyo.querySelector('.rl-place').classList.contains('refused'));
  assert.equal(words(tokyo.querySelector('.rl-place-tier')), 'Out of reach');
  const why = tokyo.querySelector('.rl-place-why');
  assert.match(words(why), /Pearl Harbor/);
  assert.equal(radio.getAttribute('aria-describedby'), why.id);
  pick(item, 'tokyo');
  submit(item);
  assert.notEqual(filed[0]?.params.to, 'tokyo');
});

test('a place refused for one force can be picked for another', () => {
  const { item } = draw([withRefusal()]);
  chooseForce(item, FLEET);
  chooseForce(item, 'us_pacific_fleet');
  assert.equal(row(item, 'tokyo').querySelector('input[type="radio"]').disabled, false);
});

test('a pick that the new force cannot reach is cleared', () => {
  const lever = withRefusal();
  lever.params.find((p) => p.places.length).places.find((p) => p.value === 'tokyo').reach.us_pacific_fleet = { tier: 'raid', base: 'pearl_harbor_base', reason: null };
  const { item, filed } = draw([lever]);
  chooseForce(item, 'us_pacific_fleet');
  pick(item, 'tokyo');
  chooseForce(item, FLEET);
  assert.equal(radios(item).filter((r) => r.checked).length, 0);
  submit(item);
  assert.notEqual(filed[0]?.params.to, 'tokyo');
});

test('any listed place can be filed, with the force', () => {
  for (const place of fleetLever.params.find((p) => p.places.length).places) {
    const { item, filed } = draw();
    chooseForce(item, FLEET);
    pick(item, place.value);
    submit(item);
    assert.deepEqual(filed, [{ lever: fleetLever.name, params: { force: FLEET, to: place.value } }], place.value);
  }
});

test('the places are radios of one name, so the keyboard moves between them', () => {
  const { item } = draw();
  const names = new Set(radios(item).map((r) => r.getAttribute('name')));
  assert.equal(names.size, 1);
  assert.ok(radios(item).every((r) => r.hasAttribute('required')));
  assert.equal(item.querySelector('fieldset.rl-places legend') !== null, true);
});

test('a form whose parameters carry no places draws as before', () => {
  const plain = fixture.desk.levers.find((l) => l.params.every((p) => !p.places?.length));
  const { item } = draw([plain]);
  assert.equal(item.querySelector('.rl-places'), null);
});

test('on a phone the list scrolls inside the form', () => {
  const css = read('css/p5-forms.css').replace(/\/\*[\s\S]*?\*\//g, '');
  const body = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .filter((m) => m[1].split(',').some((s) => s.trim() === '.rl-places-list')).map((m) => m[2]).join(';');
  assert.match(body, /max-height:\s*[^;]+/);
  assert.match(body, /overflow-y:\s*auto/);
  assert.match(body, /overscroll-behavior:\s*contain/);
});
