// The Court board: the seat's own people along the paths its orders travel. Not built yet:
// the board says so. Nothing here touches the page on import.

import { h } from '../dom.js';

/** `courtBoard(rv, ui, { pick, act })`: the Court, for the board's main area. */
export function courtBoard() {
  return h('section', { class: 'rl-court', 'aria-labelledby': 'rl-court-h' },
    h('h2', { id: 'rl-court-h' }, 'Court'),
    h('p', { class: 'muted' }, 'The court is not built yet. Your people and their orders are on the Desk view.'));
}
