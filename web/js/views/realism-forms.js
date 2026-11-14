// "Standard forms" (Train 2 unit M3): the seat's levers, folded by default. A movement
// form's destination is drawn as a place picker (realism_api.py PlaceChoice).

import { h } from '../dom.js';
import { instrument } from './realism.js';
import { tag } from './ui-kit.js';

/** The summary line: "Standard forms (n)". */
export function formsSummary(levers) {
  return `Standard forms (${levers.length})`;
}

/** The picker's groups, in the order the server ranks them, each with its heading. */
const GROUPS = [
  ['own', 'Your bases'],
  ['allied', 'Allied bases'],
  ['route', 'Routes'],
  ['contested', 'Contested'],
  ['other', 'Elsewhere'],
];

/** A reach tier in words, and its tone. */
const TIERS = {
  sustained: ['Sustained', 'ok'],
  operate: ['Operate', 'info'],
  raid: ['Raid', 'warn'],
  refused: ['Out of reach', 'danger'],
};

/** The form's param whose choice a place's days and reach are given for. */
const FORCE = 'force';

/** Routed days in words: "There now", "1 day", "n days"; null: "No known route". */
export function daysLabel(days) {
  if (days === null || days === undefined) return 'No known route';
  if (days === 0) return 'There now';
  return days === 1 ? '1 day' : `${days} days`;
}

/** A `PlaceReach` in words; null when there is none. */
export function tierLabel(reach) {
  return reach ? TIERS[reach.tier][0] : null;
}

let pickerSeq = 0;

/**
 * Replace the select `instrument` drew for `param` in `item` with the place picker: a hidden
 * field with the select's id and name (what the form reads on submit), and one radio per
 * place under its group. Days and reach follow the form's force select; a place refused for
 * that force is disabled, with its reason.
 */
function placePicker(item, param, forceLabel) {
  const select = item.querySelector(`select[name="${param.name}"]`);
  if (!select) return;
  const force = item.querySelector(`select[name="${FORCE}"]`);
  const id = `rl-places-${pickerSeq++}`;
  const field = h('input', { type: 'hidden', id: select.id, name: param.name, value: '' });
  const hint = h('p', { class: 'rl-places-hint' },
    `Choose ${forceLabel.toLowerCase()} first to see the days and the reach of each place.`);
  const list = h('div', { class: 'rl-places-list' });
  const choose = (value) => { field.value = value; };

  const placeRow = (place, key, n) => {
    const reach = key ? place.reach?.[key] ?? null : null;
    const refused = reach?.tier === 'refused';
    if (refused && field.value === place.value) choose('');
    const why = refused ? h('p', { class: 'rl-place-why', id: `${id}-why-${n}` }, reach.reason ?? '') : null;
    return h('li', {},
      h('label', { class: `rl-place${refused ? ' refused' : ''}` },
        h('input', {
          type: 'radio', name: id, value: place.value, required: true, disabled: refused,
          checked: field.value === place.value, 'aria-describedby': why?.id,
          onchange: () => choose(place.value),
        }),
        h('span', { class: 'rl-place-name' }, place.label),
        key ? h('span', { class: 'rl-place-days' }, daysLabel(place.days?.[key] ?? null)) : null,
        reach ? h('span', { class: 'rl-place-tier' }, tag(tierLabel(reach), TIERS[reach.tier][1])) : null),
      why);
  };

  const draw = () => {
    const key = force?.value ?? '';
    let n = 0;
    list.replaceChildren(...GROUPS.map(([group, head]) => {
      const places = param.places.filter((p) => p.group === group);
      return places.length
        ? h('div', { class: 'rl-place-group' },
          h('p', { class: 'rl-place-group-h' }, head),
          h('ul', { class: 'rl-place-rows', role: 'list' }, places.map((p) => placeRow(p, key, n++))))
        : null;
    }).filter(Boolean));
    if (key) hint.remove();
    else if (!hint.parentNode) list.before(hint);
  };

  const picker = h('fieldset', { class: 'rl-places' }, h('legend', {}, param.label), field, list);
  force?.addEventListener('change', draw);
  select.closest('.rl-field').replaceChildren(picker);
  draw();
}

/** The split form's param for how much of a fleet's strength goes. */
const STRENGTH = 'strength';

/** A detachment's force key: its fleet's key, then `__d` and its number. */
const DETACHED = /^(.+)__d\d+$/;

/** `value` as a whole number inside `lo` to `hi`; not a number: `lo`. */
export function stepTo(value, lo, hi) {
  const n = Math.round(Number(value));
  if (!Number.isFinite(n)) return lo;
  return Math.min(hi, Math.max(lo, n));
}

/**
 * The force choices in groups, in the server's order: a fleet with detachments on offer
 * heads a group of itself and them; any other choice is a group of one.
 */
export function forceGroups(choices) {
  const groups = new Map(choices.filter((c) => !DETACHED.test(c.value)).map((c) => [c.value, [c]]));
  const out = [];
  for (const c of choices) {
    const parent = groups.get(DETACHED.exec(c.value)?.[1]);
    if (parent) parent.push(c);
    else out.push(groups.get(c.value) ?? [c]);
  }
  return out;
}

/** Redraw the force select's options with each detachment under its fleet, as an optgroup. */
function groupForces(item, param) {
  const select = item.querySelector(`select[name="${FORCE}"]`);
  if (!select) return;
  const option = (c) => h('option', { value: c.value }, c.label);
  select.replaceChildren(h('option', { value: '' }, 'Choose…'),
    ...forceGroups(param.choices).map((g) => (g.length > 1 ? h('optgroup', { label: g[0].label }, g.map(option)) : option(g[0]))));
}

/**
 * Wrap the number field `instrument` drew for `param` in a stepper: one less, the field,
 * one more. It starts at the least; a button at its end says so (`aria-disabled`, so it
 * keeps focus) and does nothing; a typed number is brought inside the bounds.
 */
function strengthStepper(item, param) {
  const input = item.querySelector(`input[name="${param.name}"]`);
  if (!input || param.lo === null || param.hi === null) return;
  const step = (word, sign, glyph) => h('button', {
    type: 'button', class: 'rl-step', 'aria-label': word, 'aria-controls': input.id,
    onclick: () => set(Number(input.value) + sign),
  }, glyph);
  const less = step('One less', -1, '−');
  const more = step('One more', 1, '+');
  function set(value) {
    input.value = String(stepTo(value, param.lo, param.hi));
    less.setAttribute('aria-disabled', String(Number(input.value) <= param.lo));
    more.setAttribute('aria-disabled', String(Number(input.value) >= param.hi));
  }
  input.addEventListener('change', () => set(input.value));
  const box = h('div', { class: 'rl-stepper', role: 'group', 'aria-label': param.label });
  input.before(box);
  box.append(less, input, more);
  set(param.lo);
}

/**
 * `instrument(lever, ...)`, with the force select's detachments grouped under their fleets,
 * a place picker for each param that carries places, and a stepper for a strength.
 */
function formFor(lever, opts) {
  const item = instrument(lever, opts);
  const force = lever.params.find((p) => p.name === FORCE);
  const forceLabel = force?.label ?? 'the force';
  if (force?.kind === 'enum') groupForces(item, force);
  for (const p of lever.params) if (p.places?.length) placePicker(item, p, forceLabel);
  for (const p of lever.params) if (p.name === STRENGTH && p.kind === 'int') strengthStepper(item, p);
  return item;
}

/**
 * A closed `<details class="rl-forms">` with `formsSummary` as its summary; inside, one
 * `instrument(lever, { onSubmit, entities })` (realism.js) per lever, a destination that
 * carries places drawn as a place picker, then the line "For anything a form does not
 * cover, write the order in your own words.". No levers: null.
 */
export function standardForms(desk, { onSubmit, entities }) {
  const levers = desk.levers ?? [];
  if (!levers.length) return null;
  return h('details', { class: 'rl-forms' },
    h('summary', {}, formsSummary(levers)),
    h('ul', { class: 'rl-instruments', role: 'list' },
      levers.map((lever) => formFor(lever, { onSubmit, entities }))),
    h('p', { class: 'rl-forms-note' }, 'For anything a form does not cover, write the order in your own words.'));
}
