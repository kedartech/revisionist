// A cast member's card on the character-select screen (Train 3 unit P1): portrait or
// monogram, name, side and pitch. The whole card is one button that opens the dossier;
// the card carries no Play button (the dossier does).

import { h } from '../dom.js';
import { monogram, portraitNode } from './realism-dossier.js';

void monogram; void portraitNode;

/**
 * The card's model for a roster entry `person` (snapshot.roster: name, pitch, reach, taken,
 * sides [{contest, side}], dossier) seen by a viewer who plays `mine` (a name, or null):
 * `{ name, side, pitch, monogram, tag, label }`.
 * - `side`: the distinct `sides[].side` names joined by " and ", in order; null when none.
 * - `pitch`: the pitch, or null when empty.
 * - `monogram`: `monogram(name)`.
 * - `tag`: "You" when `person.name === mine`, else "Taken" when `person.taken`, else null.
 * - `label`: "<name>: open the dossier".
 * contract stub
 */
export function cardModel(person, mine) {
  return { name: person?.name ?? '', side: null, pitch: null, monogram: '', tag: null, label: '' };
}

/**
 * `<article class="rl-cc">` (`rl-cc taken` when tagged) holding one
 * `<button type="button" class="rl-cc-open" aria-label=label>` that calls `onOpen(person)`.
 * Inside the button: `portraitNode(name, person.dossier, 'rl-cc')`, the name
 * (`.rl-cc-name`), the side (`.rl-cc-side`), the pitch (`.rl-cc-pitch`) and the tag
 * (`.rl-cc-tag`), each left out when empty.
 * contract stub
 */
export function castCard(person, { mine = null, onOpen } = {}) {
  return h('article', { class: 'rl-cc' }, person?.name ?? '');
}
