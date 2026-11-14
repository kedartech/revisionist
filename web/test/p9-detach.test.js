// Detachments on the client: the split form's strength is a stepper inside the form's
// bounds, the force picker shows each detachment under the fleet it came from, and the
// map draws a detachment only where a page has sighted it. The server's own tests cover
// which detachments a seat is offered (tests/test_detach_picker.py).
// Run: node --test web/test/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { fire, installDom, words } from './dom-fake.js';

installDom();
const { forceGroups, standardForms, stepTo } = await import('../js/views/realism-forms.js');
const { mapDrawing, mapView } = await import('../js/views/realism-map.js');

const WEB = fileURLToPath(new URL('..', import.meta.url));
const read = (f) => readFileSync(join(WEB, f), 'utf8');
const fixture = JSON.parse(read('test/fixtures/realism-seat.json'));
const moveLever = fixture.desk.levers.find((l) => l.params.some((p) => p.places?.length));
const DETACHED = 'us_atlantic_fleet__d1';

/** The split form as the server sends it: the move form's force and places, and a strength from 1 to 4. */
function splitLever() {
  const lever = structuredClone(moveLever);
  lever.name = 'detach_fleet';
  lever.label = 'Detach part of a fleet';
  const force = lever.params.find((p) => p.name === 'force');
  force.choices = force.choices.filter((c) => c.value !== DETACHED);
  lever.params.push({ name: 'strength', label: 'How much of its strength', kind: 'int', lo: 1, hi: 4, choices: [], places: [] });
  return lever;
}

function draw(levers) {
  const filed = [];
  const forms = standardForms({ ...fixture.desk, levers }, { onSubmit: (v) => filed.push(v), entities: [] });
  return { forms, filed };
}
const itemOf = (forms, name) => forms.querySelectorAll('.rl-instrument').find((i) => i.getAttribute('data-lever') === name);
const stepButton = (item, label) => item.querySelectorAll('.rl-stepper button').find((b) => b.getAttribute('aria-label') === label);
const strength = (item) => item.querySelector('input[name="strength"]');
const submit = (item) => {
  const form = item.querySelector('form');
  const query = form.querySelector.bind(form);
  form.querySelector = (s) => (s.startsWith('#') ? form.querySelectorAll('[id]').find((e) => e.id === s.slice(1)) ?? null : query(s));
  fire(form, 'submit');
};

test('stepTo keeps a strength inside the bounds, and an empty or unreadable one at the least', () => {
  assert.equal(stepTo(3, 1, 4), 3);
  assert.equal(stepTo(9, 1, 4), 4);
  assert.equal(stepTo(0, 1, 4), 1);
  assert.equal(stepTo('', 1, 4), 1);
  assert.equal(stepTo('two', 1, 4), 1);
  assert.equal(stepTo('2.6', 1, 4), 3);
});

test('the strength is a stepper that starts at the least and says so at each end', () => {
  const item = itemOf(draw([splitLever()]).forms, 'detach_fleet');
  const less = stepButton(item, 'One less');
  const more = stepButton(item, 'One more');
  assert.ok(less && more, 'a less and a more button');
  assert.equal(strength(item).closest('.rl-stepper'), item.querySelector('.rl-stepper'), 'the field sits between them');
  assert.equal(strength(item).value, '1');
  assert.equal(less.getAttribute('aria-disabled'), 'true');
  assert.equal(more.getAttribute('aria-disabled'), 'false');
  for (let i = 0; i < 5; i += 1) more.click();
  assert.equal(strength(item).value, '4', 'more stops at the most');
  assert.equal(more.getAttribute('aria-disabled'), 'true');
  assert.equal(less.getAttribute('aria-disabled'), 'false');
  less.click();
  assert.equal(strength(item).value, '3');
  for (let i = 0; i < 5; i += 1) less.click();
  assert.equal(strength(item).value, '1', 'less stops at the least');
});

test('a typed strength outside the bounds is brought back inside them', () => {
  const item = itemOf(draw([splitLever()]).forms, 'detach_fleet');
  strength(item).value = '7';
  fire(strength(item), 'change');
  assert.equal(strength(item).value, '4');
  strength(item).value = '0';
  fire(strength(item), 'change');
  assert.equal(strength(item).value, '1');
});

test('the split is filed with the stepped strength as a number', () => {
  const { forms, filed } = draw([splitLever()]);
  const item = itemOf(forms, 'detach_fleet');
  const force = item.querySelector('select[name="force"]');
  force.value = 'us_atlantic_fleet';
  fire(force, 'change');
  const argentia = item.querySelectorAll('.rl-places input[type="radio"]').find((r) => r.value === 'argentia');
  argentia.checked = true;
  fire(argentia, 'change');
  stepButton(item, 'One more').click();
  submit(item);
  assert.deepEqual(filed, [{ lever: 'detach_fleet', params: { force: 'us_atlantic_fleet', to: 'argentia', strength: 2 } }]);
});

test('an int other than a strength stays a plain number field', () => {
  const lend = fixture.desk.levers.find((l) => l.params.some((p) => p.name === 'share_pct'));
  const item = itemOf(draw([lend]).forms, lend.name);
  assert.equal(item.querySelector('.rl-stepper'), null);
  assert.equal(item.querySelector('input[name="share_pct"]').value, '');
});

test('forceGroups puts each detachment under the fleet it came from', () => {
  const choices = [
    { value: 'us_atlantic_fleet', label: 'The Atlantic Fleet' },
    { value: 'us_atlantic_fleet__d1', label: 'US Atlantic Fleet detachment 1' },
    { value: 'us_pacific_fleet', label: 'The Pacific Fleet' },
    { value: 'us_atlantic_fleet__d2', label: 'US Atlantic Fleet detachment 2' },
    { value: 'home_fleet__d1', label: 'Home Fleet detachment 1' },
  ];
  assert.deepEqual(forceGroups(choices).map((g) => g.map((c) => c.value)), [
    ['us_atlantic_fleet', 'us_atlantic_fleet__d1', 'us_atlantic_fleet__d2'],
    ['us_pacific_fleet'],
    ['home_fleet__d1'],
  ]);
});

test('the move form shows a detachment under its fleet, and a fleet without one alone', () => {
  const item = itemOf(draw([moveLever]).forms, moveLever.name);
  const select = item.querySelector('select[name="force"]');
  const groups = select.querySelectorAll('optgroup');
  assert.deepEqual(groups.map((g) => g.getAttribute('label')), ['The Atlantic Fleet']);
  assert.deepEqual(groups[0].querySelectorAll('option').map((o) => [o.value, words(o)]), [
    ['us_atlantic_fleet', 'The Atlantic Fleet'],
    [DETACHED, 'US Atlantic Fleet detachment 1'],
  ]);
  const alone = select.children.filter((c) => c.tagName === 'OPTION').map((o) => o.value);
  assert.deepEqual(alone, ['', 'us_pacific_fleet']);
});

test('a detachment picked from its group drives the place picker as any force does', () => {
  const item = itemOf(draw([moveLever]).forms, moveLever.name);
  const select = item.querySelector('select[name="force"]');
  select.value = DETACHED;
  fire(select, 'change');
  const days = item.querySelectorAll('.rl-place-days').map(words);
  assert.ok(days.length && days.every((d) => d === 'No known route'), 'no page places the detachment yet');
});

const AT = { name: 'Argentia', lat: 47.3, lon: -54.0 };
const sighted = {
  name: 'US Atlantic Fleet detachment 1', kind: 'fleet', side: 'own', side_name: 'United States', certainty: 'known',
  reported: '1941-10-20', source: 'Harold R. Stark', document: 'd-atlantic-1020', places: [AT],
};
const ordered = {
  order: 'o-move-1020', force: 'US Atlantic Fleet detachment 1', mark: null, to: AT,
  status: 'under_way', with_person: 'Harold R. Stark', filed: '1941-10-14',
};
const withMarks = (marks, orders = fixture.map.orders) => ({ ...fixture.map, marks: [...fixture.map.marks, ...marks], orders });
const markNamed = (root, name) => root.querySelectorAll('g.rl-mk').find((g) => g.querySelector('.rl-mk-name') && words(g.querySelector('.rl-mk-name')) === name);
const shapeWidth = (g) => Number(g.querySelector('rect').getAttribute('width'));

test('a sighted detachment is drawn as a detachment, smaller than its fleet', () => {
  const pic = mapDrawing(withMarks([sighted]), null);
  const det = markNamed(pic, sighted.name);
  const fleet = markNamed(pic, 'US Atlantic Fleet');
  assert.ok(det.classList.contains('rl-mk-detached'));
  assert.ok(!fleet.classList.contains('rl-mk-detached'));
  assert.ok(shapeWidth(det) < shapeWidth(fleet), 'a detachment is drawn smaller');
  assert.match(det.getAttribute('aria-label'), /^US Atlantic Fleet detachment 1: Fleet detachment, /);
});

test('a detachment no page has sighted is not drawn, even under way on an order', () => {
  const map = withMarks([], [...fixture.map.orders, ordered]);
  const pic = mapDrawing(map, null);
  assert.equal(pic.querySelector('.rl-mk-detached'), null);
  assert.equal(pic.querySelectorAll('g.rl-mk').length, fixture.map.marks.length);
  const list = mapView(map, null, { mode: 'list' });
  assert.ok(!list.querySelectorAll('tbody th').map(words).includes(sighted.name));
});

test('the list and the key name a detachment once one is sighted, and not before', () => {
  const list = mapView(withMarks([sighted]), null, { mode: 'list' });
  const row = list.querySelectorAll('tbody tr').find((r) => words(r.querySelector('th')) === sighted.name);
  assert.equal(words(row.querySelectorAll('td')[0]), 'Fleet detachment');
  const key = (map) => mapView(map, null, {}).querySelectorAll('.rl-legend li').map(words);
  assert.ok(key(withMarks([sighted])).some((w) => w.startsWith('Detachment:')));
  assert.ok(!key(fixture.map).some((w) => w.startsWith('Detachment:')));
});
