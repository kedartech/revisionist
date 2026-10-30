// The wake on the desk (Phase 4 unit C1): the header, the agenda, initiative, commit
// and how each order landed. Built from view.realism (realism_api.py).

import { h } from '../dom.js';

const nothing = () => document.createDocumentFragment();

/** The wake header. Phase 4 unit C1 replaces Advance, kept here as it was, with commit. */
export function wakeHeader(wake, { act }) {
  return h('button', {
    type: 'button', class: 'primary',
    onclick: () => act('The wake is running. New papers are being written; this can take a minute…', 'advance', {}),
  }, 'Advance to next wake');
}

/** Each agenda item with its options or plan. Phase 4 unit C1. */
export function agendaPanel(agenda, { act }) {
  return nothing();
}

/** The options offered outside the agenda. Phase 4 unit C1. */
export function initiativePanel(agenda, { act }) {
  return nothing();
}

/** Seal this seat's orders for the wake. Phase 4 unit C1. */
export function commitPanel(wake, { act }) {
  return nothing();
}

/** How each routed order landed, under the pending orders. Phase 4 unit C1. */
export function resultsPanel(results) {
  return nothing();
}
