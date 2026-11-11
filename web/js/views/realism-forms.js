// "Standard forms" (Train 2 unit M3): the seat's levers, folded by default.

import { h } from '../dom.js';
import { instrument } from './realism.js';

/** The summary line: "Standard forms (n)". */
export function formsSummary(levers) {
  return `Standard forms (${levers.length})`;
}

/**
 * A closed `<details class="rl-forms">` with `formsSummary` as its summary; inside, one
 * `instrument(lever, { onSubmit, entities })` (realism.js) per lever, then the line "For
 * anything a form does not cover, write the order in your own words.". No levers: null.
 */
export function standardForms(desk, { onSubmit, entities }) {
  const levers = desk.levers ?? [];
  if (!levers.length) return null;
  return h('details', { class: 'rl-forms' },
    h('summary', {}, formsSummary(levers)),
    h('ul', { class: 'rl-instruments', role: 'list' },
      levers.map((lever) => instrument(lever, { onSubmit, entities }))),
    h('p', { class: 'rl-forms-note' }, 'For anything a form does not cover, write the order in your own words.'));
}
