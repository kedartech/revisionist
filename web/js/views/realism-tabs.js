// The room's panel switches (unit U2 builds them). Contract stub: both return an empty node
// so the room draws while the unit is out. Nothing here touches the page on import.

import { h } from '../dom.js';

/**
 * `tabBar(rv, ui, pick)`: the phone's bottom tab bar: Papers, Desk, Orders and Messages, each
 * with its count; a tap calls `pick({ tab })`, and Messages opens the messenger.
 */
export function tabBar() {
  return h('nav', { class: 'rl-tabbar' });
}

/** `sideSwitch(ui, pick)`: the tablet's switch beside the desk, Papers or Your orders; a click calls `pick({ side })`. */
export function sideSwitch() {
  return h('div', { class: 'rl-sideswitch' });
}
