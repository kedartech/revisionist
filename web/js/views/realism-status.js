// The status strip and the summary tiles over the room, and the map-first room's one bar.
// Nothing here touches the page on import.

import { h, icon, svg } from '../dom.js';
import { worldDate, untilText } from '../rules.js';
import { comeBackLine, commitBusy, commitLabel, deadlineWords } from './realism-wake.js';
import { economyStrip } from './realism-economy.js';
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
 * only), with the primary "Done for today", then the "when you come back" line on its own
 * row. `act` runs a room call, as the commit panel's does.
 */
export function statusStrip(rv, ui, { act }) {
  const wake = rv.wake ?? {};
  const multi = wake.humans > 1;
  const open = Boolean(wake.deadline);
  const comeBack = comeBackLine(rv);
  const filed = (rv.record?.orders ?? []).filter((o) => o.wake === wake.wake).length;
  return h('div', { class: 'rl-strip', role: 'region', 'aria-label': 'Where the day stands' },
    h('span', { class: 'rl-date' }, worldDate(rv.clock?.world_date)),
    h('span', { class: 'rl-filed-count' }, `${filed} ${filed === 1 ? 'order' : 'orders'} filed this wake.`),
    multi && open ? countdown(wake.deadline) : null,
    multi ? doneBar(wake) : null,
    open && !wake.you_committed
      ? h('button', { type: 'button', class: 'btn-1', onclick: () => act(commitBusy(wake), 'commit', {}) }, commitLabel(wake))
      : null,
    open && wake.you_committed
      ? h('span', { class: 'rl-committed', role: 'status', 'aria-live': 'polite' }, commitLabel(wake))
      : null,
    comeBack ? h('p', { class: 'rl-comeback' }, comeBack) : null,
    economyStrip(rv, { act }));
}

/**
 * `summaryTiles(rv, pick)`: Unread, Due, Orders under way, Threats; a tile click calls `pick({ tab })`.
 * Due counts the dated agenda items, the ones the desk lists when the tile opens it; orders that
 * need a decision are counted on the Orders tab badge.
 */
export function summaryTiles(rv, pick) {
  const orders = rv.orders?.orders ?? [];
  const due = (rv.agenda?.items ?? []).filter((i) => i.deadline).length;
  const going = orders.filter((o) => !SETTLED.has(o.status)).length;
  const t = (n, label, tone, tab) => tile(n, label, null, tone, () => pick({ tab }));
  return h('div', { class: 'rl-tiles' },
    t(rv.documents?.unread ?? 0, 'Unread', 'info', 'papers'),
    t(due, 'Due', 'warn', 'desk'),
    t(going, 'Orders under way', 'ok', 'orders'),
    t((rv.threats ?? []).length, 'Threats', 'danger', 'orders'));
}

const AIM_WORD = { met: 'Met', at_risk: 'At risk', failed: 'Failed' };
/** Each status's drawing in a 16 px box: a ring with a tick, half filled, or crossed. */
const AIM_SHAPES = {
  met: [['path', { d: 'M4.5 8.5l2.5 2.5 4.5-5', fill: 'none' }]],
  at_risk: [['path', { d: 'M8 1.5a6.5 6.5 0 0 1 0 13z', fill: 'currentColor', stroke: 'none' }]],
  failed: [['path', { d: 'M5.2 5.2l5.6 5.6M10.8 5.2l-5.6 5.6', fill: 'none' }]],
};

/** An aim's status drawn as a shape, so it never rests on colour alone. */
function aimShape(status) {
  const known = status in AIM_SHAPES ? status : null;
  return svg('svg', {
    width: 16, height: 16, viewBox: '0 0 16 16', 'aria-hidden': 'true', focusable: 'false', 'data-shape': known ?? 'open',
    stroke: 'currentColor', 'stroke-width': 1.6,
  }, svg('circle', { cx: 8, cy: 8, r: 6.5, fill: 'none' }),
  (AIM_SHAPES[known] ?? []).map(([tag, attrs]) => svg(tag, attrs)));
}

/**
 * `aimMarks(aims, { open, onOpen })`: the seat's first three aims as marks on the bar, each a
 * button named for its number, status and words; a press calls `onOpen(aim)`. Null with no aim.
 */
export function aimMarks(aims, { open = false, onOpen } = {}) {
  const shown = (Array.isArray(aims) ? aims : []).slice(0, 3);
  if (!shown.length) return null;
  return h('div', { class: 'rl-aimmarks', role: 'group', 'aria-label': 'Your aims' },
    h('span', { class: 'rl-aimmarks-word', 'aria-hidden': 'true' }, 'Aims'),
    shown.map((aim, i) => h('button', {
      type: 'button', class: `rl-aimmark rl-aim-${aim.status}`, 'data-status': aim.status, 'aria-expanded': String(open),
      'aria-controls': open ? 'rl-over' : null,
      'aria-label': `Aim ${aim.aim ?? i + 1}: ${AIM_WORD[aim.status] ?? 'Open'}. ${aim.text}`,
      onclick: () => onOpen?.(aim),
    }, aimShape(aim.status))));
}

/** The wake's clock: how long until it closes, and in multiplayer the players done. */
function barClock(wake) {
  const open = Boolean(wake.deadline);
  const multi = wake.humans > 1;
  if (!open && !multi) return null;
  const closes = deadlineWords(wake.deadline);
  return h('div', { class: 'rl-bar-clock', title: closes ?? null },
    open ? [icon('clock', 14), countdown(wake.deadline)] : null,
    closes ? h('span', { class: 'rl-bar-closes' }, closes) : null,
    multi ? doneBar(wake) : null);
}

/**
 * `roomBar(rv, { tabs, menu, aims, nations, act })`: everything the map-first room draws above the
 * map, in one bar: the world date, the wake's clock with the players done, the aim marks
 * (`aims`, from `aimMarks`), one Nations control (`nations`: `{ open, onOpen }`, or null when
 * there are no nations' figures to show), the sheet tabs (`tabs`), Done for today or that the
 * seat is done, and the game menu's button (`menu`).
 */
export function roomBar(rv, { tabs = null, menu = null, aims = null, nations = null, act }) {
  const wake = rv.wake ?? {};
  const open = Boolean(wake.deadline);
  return h('div', { class: 'rl-roombar', role: 'region', 'aria-label': 'Where the day stands' },
    h('div', { class: 'rl-bar-day' },
      h('span', { class: 'rl-bar-date rl-date' }, worldDate(rv.clock?.world_date)),
      barClock(wake)),
    aims,
    nations ? h('button', {
      type: 'button', class: 'rl-btn rl-nations-btn', 'aria-expanded': String(Boolean(nations.open)),
      'aria-controls': nations.open ? 'rl-over' : null, onclick: () => nations.onOpen?.(),
    }, 'Nations') : null,
    tabs,
    h('div', { class: 'rl-bar-end' },
      open && !wake.you_committed
        ? h('button', { type: 'button', class: 'btn-1 rl-bar-done', onclick: () => act(commitBusy(wake), 'commit', {}) }, commitLabel(wake))
        : null,
      open && wake.you_committed
        ? h('span', { class: 'rl-committed', role: 'status', 'aria-live': 'polite' }, commitLabel(wake))
        : null,
      menu));
}
