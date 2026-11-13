// The room's panel switches: the phone's bottom tab bar and the tablet's side switch.
// Nothing here touches the page on import.

import { h } from '../dom.js';

const TABS = [
  { tab: 'papers', label: 'Papers' },
  { tab: 'desk', label: 'Desk' },
  { tab: 'orders', label: 'Orders' },
  { tab: 'messages', label: 'Messages' },
];

function countFor(rv, tab) {
  if (tab === 'papers') return Number(rv?.documents?.unread) || 0;
  if (tab === 'orders') return (rv?.orders?.orders || []).filter((o) => o.decision_needed).length;
  return 0;
}

/**
 * `tabBar(rv, ui, pick)`: the phone's bottom tab bar: Papers, Desk, Orders and Messages, each
 * with its count; a tap calls `pick({ tab })`, and Messages opens the messenger.
 */
export function tabBar(rv, ui, pick) {
  return h('nav', { class: 'rl-tabbar', 'aria-label': 'Room panels' },
    ...TABS.map(({ tab, label }) => {
      const n = countFor(rv, tab);
      return h('button', {
        type: 'button',
        class: 'rl-tab',
        'aria-current': ui.tab === tab ? 'page' : null,
        onclick: () => pick({ tab }),
      }, label, ...(n > 0 ? [' ', h('span', { class: 'badge tone-warn rl-tab-count' }, String(n))] : []));
    }));
}

/** `sideSwitch(ui, pick)`: the tablet's switch beside the desk, Papers or Your orders; a click calls `pick({ side })`. */
export function sideSwitch(ui, pick) {
  const one = (side, label) => h('button', {
    type: 'button',
    class: 'rl-btn',
    'aria-pressed': ui.side === side ? 'true' : 'false',
    onclick: () => pick({ side }),
  }, label);
  return h('div', { class: 'rl-sideswitch', role: 'group', 'aria-label': 'Side panel' },
    one('papers', 'Papers'), one('orders', 'Your orders'));
}
