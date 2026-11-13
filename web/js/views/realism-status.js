// The status strip and the summary tiles over the room (unit U1 builds them). Contract stub:
// both return an empty node so the room draws while the unit is out.
// Nothing here touches the page on import.

import { h } from '../dom.js';

/**
 * `statusStrip(rv, ui, { act })`: the strip under the header: the world date and, in
 * multiplayer only, the countdown to the wake's deadline and the players-done bar (counts
 * only), with the primary "Done for today". `act` runs a room call, as the commit panel's does.
 */
export function statusStrip() {
  return h('div', { class: 'rl-strip' });
}

/** `summaryTiles(rv, pick)`: Unread, Due, Orders under way, Threats; a tile click calls `pick({ tab })`. */
export function summaryTiles() {
  return h('div', { class: 'rl-tiles' });
}
