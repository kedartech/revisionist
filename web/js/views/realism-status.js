// The status strip and the summary tiles over the room.
// Nothing here touches the page on import.

import { h } from '../dom.js';
import { worldDate, untilText } from '../rules.js';
import { commitBusy, commitLabel } from './realism-wake.js';
import { tile } from './ui-kit.js';

const SETTLED = new Set(['enacted', 'refused', 'lapsed', 'withdrawn']);

function countdown(deadline) {
  const left = untilText(deadline);
  if (!left) return null;
  return h('time', { class: 'rl-countdown', datetime: deadline },
    left === 'Due now' ? 'Closing now' : `${left} left`);
}

function doneBar(wake) {
  const bar = [];
  for (let i = 0; i < wake.humans; i += 1) bar.push(h('span', { class: i < wake.committed ? 'on' : '' }));
  return h('span', { class: 'rl-done-bar', role: 'img', 'aria-label': `${wake.committed} of ${wake.humans} players done` }, bar);
}

/**
 * `statusStrip(rv, ui, { act })`: the strip under the header: the world date and, in
 * multiplayer only, the countdown to the wake's deadline and the players-done bar (counts
 * only), with the primary "Done for today". `act` runs a room call, as the commit panel's does.
 */
export function statusStrip(rv, ui, { act }) {
  const wake = rv.wake ?? {};
  const multi = wake.humans > 1;
  const open = Boolean(wake.deadline);
  return h('div', { class: 'rl-strip', role: 'region', 'aria-label': 'Where the day stands' },
    h('span', { class: 'rl-date' }, worldDate(rv.clock?.world_date)),
    multi && open ? countdown(wake.deadline) : null,
    multi ? doneBar(wake) : null,
    open && !wake.you_committed
      ? h('button', { type: 'button', class: 'btn-1', onclick: () => act(commitBusy(wake), 'commit', {}) }, commitLabel(wake))
      : null,
    open && wake.you_committed
      ? h('span', { class: 'rl-committed', role: 'status', 'aria-live': 'polite' }, commitLabel(wake))
      : null);
}

/** `summaryTiles(rv, pick)`: Unread, Due, Orders under way, Threats; a tile click calls `pick({ tab })`. */
export function summaryTiles(rv, pick) {
  const orders = rv.orders?.orders ?? [];
  const due = (rv.agenda?.items ?? []).filter((i) => i.deadline).length + orders.filter((o) => o.decision_needed).length;
  const going = orders.filter((o) => !SETTLED.has(o.status)).length;
  const t = (n, label, tone, tab) => tile(n, label, null, tone, () => pick({ tab }));
  return h('div', { class: 'rl-tiles' },
    t(rv.documents?.unread ?? 0, 'Unread', 'info', 'papers'),
    t(due, 'Due', 'warn', 'desk'),
    t(going, 'Orders under way', 'ok', 'orders'),
    t((rv.threats ?? []).length, 'Threats', 'danger', 'orders'));
}
