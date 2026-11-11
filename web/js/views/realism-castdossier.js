// The dossier behind a cast card or a listed figure, on the character-select screen
// (Train 3 unit P3): full for a person with sidecar text, short for anyone else; "Play
// <name>" and Close.

import { h } from '../dom.js';
import { portraitNode } from './realism-dossier.js';

void portraitNode;

export const DRAW_NOTE = 'Drawing up their papers takes about a minute.';

/**
 * The model for `person`, a roster entry (name, pitch, reach, taken, sides, dossier) or a
 * listed figure (name, title, side, power), with its `dossier` (a Dossier, or null):
 * `{ name, full, listed, sections }`.
 * - `full`: the dossier has a bio. `listed`: `person` is a listed figure, not a roster entry
 *   (it has `power` and no `pitch`).
 * - `sections`, `{ heading, lines }`, only those with content, in this order:
 *   Side (roster: the distinct `sides[].side` joined by " and "; figure: `side`),
 *   Title (figure only), Kind of power (figure only), Who they are (`pitch`),
 *   Their reach (`reach`), Your arena (`arena`), Biography (`bio`),
 *   As history had it (the `history` lines, then the line "Not binding: you may do otherwise."),
 *   In their words (“<quote>” then "— <source>"; left out when the quote has no source),
 *   A fact (`fact`).
 * contract stub
 */
export function castDossierModel(person, dossier) {
  return { name: person?.name ?? '', full: false, listed: false, sections: [] };
}

/**
 * `<dialog class="rl-cd" aria-labelledby="rl-cd-title">`: `portraitNode(name, dossier, 'rl-cd')`,
 * the h2 name (`#rl-cd-title`), each section as an h3 plus a paragraph or a list, then the
 * foot: when `canPlay`, a primary button "Play <name>" calling `onPlay(person)`; for a listed
 * figure, the `DRAW_NOTE` line beside it; and a Close button calling `onClose()`. The
 * dialog's `close` event (Esc) also calls `onClose()`.
 * contract stub
 */
export function castDossier({ person, dossier = null, canPlay = true, onPlay, onClose } = {}) {
  return h('dialog', { class: 'rl-cd', 'aria-labelledby': 'rl-cd-title' },
    h('h2', { id: 'rl-cd-title' }, person?.name ?? ''));
}
