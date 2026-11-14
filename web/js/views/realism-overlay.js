// The overlay while a wake runs (Train 2 unit V): a full-screen layer that holds the room
// and gives the player something to read: what is already known (your orders on their way,
// your own forces under way on a small map), then lines from the setting.

import { h } from '../dom.js';
import { mapDrawing } from './realism-map.js';

/** Three fixed, period-neutral lines for a world with no setting text. */
export const QUIET_LINES = Object.freeze([
  'Dispatches are being written.',
  'The wires are quiet for the moment.',
  'Each desk is waiting on its reports.',
]);

/** The delay rules in p5-overlay.css: one per slot, so no more lines than this are drawn. */
export const OVERLAY_SLOTS = 8;

/** The delay rules for moving marks in p5-overlay.css: no more orders than this move on the map. */
export const MAP_MOVES = 4;

/** Order lines shown; the rest are counted in one line. */
export const ORDER_LINES = 5;

const TITLE_ID = 'rl-ovl-title';
const LAND_URL = '/assets/land-110m.json';

const text = (v) => (typeof v === 'string' && v.trim() ? v : null);

/**
 * The setting's `facts`, then its dates as "<on>: <what>"; `QUIET_LINES` when both are empty.
 * More lines than slots: the window of `OVERLAY_SLOTS` that starts at `(turn * OVERLAY_SLOTS) % n`.
 */
export function overlayLines(setting, turn = 0) {
  const facts = Array.isArray(setting?.facts) ? setting.facts.map(text).filter(Boolean) : [];
  const dates = Array.isArray(setting?.dates)
    ? setting.dates.map((d) => [text(d?.on), text(d?.what)].filter(Boolean).join(': ')).filter(Boolean)
    : [];
  const lines = [...facts, ...dates];
  const all = lines.length ? lines : [...QUIET_LINES];
  const n = all.length;
  if (n <= OVERLAY_SLOTS) return all;
  const start = (((Number.isInteger(turn) ? turn : 0) * OVERLAY_SLOTS) % n + n) % n;
  return Array.from({ length: OVERLAY_SLOTS }, (_, i) => all[(start + i) % n]);
}

/** The seat's orders still on their way (the record's moving lines): "<asked> · to <name>". */
export function leavingLines(orders) {
  const moving = (Array.isArray(orders) ? orders : []).filter((o) => o?.moving && text(o.asked));
  const line = (o) => {
    if (text(o.to)) return `${o.asked} · to ${o.to}`;
    return text(o.holder) ? `${o.asked} · with ${o.holder}` : o.asked;
  };
  const shown = moving.slice(0, ORDER_LINES).map(line);
  const rest = moving.length - shown.length;
  return rest > 0 ? [...shown, `and ${rest} more`] : shown;
}

/** The part of the seat's map the overlay draws: own marks and orders under way; null if none. */
function ownMap(map) {
  if (!map || !Array.isArray(map.marks)) return null;
  const marks = map.marks.filter((m) => m.side === 'own' && m.places?.length);
  const orders = (map.orders ?? []).filter((o) => o.status === 'under_way');
  if (!marks.length && !orders.length) return null;
  return { places: map.places ?? [], marks, orders };
}

let land = null;
let landing = null;

/** The coastlines, fetched once; until they arrive (or if they never do) the map has none. */
function loadLand() {
  if (land || landing || typeof fetch !== 'function') return landing;
  landing = Promise.resolve()
    .then(() => fetch(LAND_URL))
    .then((r) => (r.ok ? r.json() : null))
    .then((json) => { if (Array.isArray(json?.rings)) land = json; })
    .catch(() => {})
    .finally(() => { landing = null; });
  return landing;
}

function drawn(map) {
  const pic = mapDrawing(map, land, { still: true, compact: true, label: 'Your own forces, and your orders under way' });
  [...pic.querySelectorAll('g.rl-mk-order')].slice(0, MAP_MOVES)
    .forEach((g, i) => g.classList.add('rl-ovl-go', `rl-ovl-go-${i + 1}`));
  return pic;
}

function mapFigure(seatMap) {
  const map = ownMap(seatMap);
  if (!map) return null;
  const fig = h('figure', { class: 'rl-ovl-map' }, drawn(map));
  if (!land) loadLand()?.then(() => { if (land && fig.isConnected) fig.replaceChildren(drawn(map)); });
  return fig;
}

/**
 * A layer `<div class="rl-ovl" role="alertdialog" aria-busy="true">` with `message`, what is
 * already known (`map`: the seat's map, of which only its own marks and orders under way are
 * drawn; `orders`: the record's lines, of which those still moving are listed), and the
 * lines, one shown at a time by a CSS animation only; a still map and a still first line
 * under reduced motion.
 */
export function wakeOverlay({ message, lines, map, orders }) {
  const items = (lines ?? []).map(text).filter(Boolean).slice(0, OVERLAY_SLOTS);
  const leaving = leavingLines(orders);
  return h('div', {
    class: 'rl-ovl',
    role: 'alertdialog',
    'aria-busy': 'true',
    'aria-modal': 'true',
    'aria-labelledby': TITLE_ID,
  },
  h('div', { class: 'rl-ovl-box' },
    h('h2', { id: TITLE_ID, class: 'rl-ovl-msg' }, message),
    mapFigure(map),
    leaving.length
      ? h('section', { class: 'rl-ovl-out', 'aria-label': 'Your orders on their way' },
        h('h3', {}, 'Your orders on their way'),
        h('ul', { class: 'rl-ovl-orders' }, leaving.map((line) => h('li', {}, line))))
      : null,
    items.length
      ? h('ul', { class: 'rl-ovl-lines' }, items.map((line) => h('li', { class: 'rl-ovl-line' }, line)))
      : null));
}
