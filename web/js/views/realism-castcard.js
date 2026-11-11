// A cast member's card on the character-select screen (Train 3 unit P1): portrait or
// monogram, name, side and pitch. The whole card is one button that opens the dossier;
// the card carries no Play button (the dossier does).

import { h } from '../dom.js';
import { monogram, portraitNode } from './realism-dossier.js';

/**
 * The card's model for a roster entry `person` (snapshot.roster: name, pitch, reach, taken,
 * sides [{contest, side}], dossier) seen by a viewer who plays `mine` (a name, or null):
 * `{ name, side, pitch, monogram, tag, label }`.
 * - `side`: the distinct `sides[].side` names joined by " and ", in order; null when none.
 * - `pitch`: the pitch, or null when empty.
 * - `monogram`: `monogram(name)`.
 * - `tag`: "You" when `person.name === mine`, else "Taken" when `person.taken`, else null.
 * - `label`: "<name>: open the dossier".
 */
export function cardModel(person, mine) {
  const name = person?.name ?? '';
  const sides = Array.isArray(person?.sides) ? person.sides : [];
  const names = [...new Set(sides.map((s) => (typeof s?.side === 'string' ? s.side.trim() : '')).filter(Boolean))];
  const pitch = typeof person?.pitch === 'string' ? person.pitch.trim() : '';
  const tag = mine && name === mine ? 'You' : person?.taken ? 'Taken' : null;
  return {
    name,
    side: names.length ? names.join(' and ') : null,
    pitch: pitch || null,
    monogram: monogram(name),
    tag,
    label: `${name}: open the dossier`,
  };
}

/**
 * `<article class="rl-cc">` (`rl-cc taken` when tagged) holding one
 * `<button type="button" class="rl-cc-open" aria-label=label>` that calls `onOpen(person)`.
 * Inside the button: `portraitNode(name, person.dossier, 'rl-cc')`, the name
 * (`.rl-cc-name`), the side (`.rl-cc-side`), the pitch (`.rl-cc-pitch`) and the tag
 * (`.rl-cc-tag`), each left out when empty.
 */
export function castCard(person, { mine = null, onOpen } = {}) {
  const m = cardModel(person, mine);
  return h('article', { class: m.tag ? 'rl-cc taken' : 'rl-cc' },
    h('button', {
      type: 'button',
      class: 'rl-cc-open',
      'aria-label': m.label,
      onclick: () => { if (onOpen) onOpen(person); },
    },
      portraitNode(m.name, person?.dossier, 'rl-cc'),
      h('span', { class: 'rl-cc-text' },
        h('span', { class: 'rl-cc-name' }, m.name),
        m.side ? h('span', { class: 'rl-cc-side' }, m.side) : null,
        m.pitch ? h('span', { class: 'rl-cc-pitch' }, m.pitch) : null,
        m.tag ? h('span', { class: 'rl-cc-tag' }, m.tag) : null)));
}
