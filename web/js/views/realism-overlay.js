// The overlay while a wake runs (Train 2 unit V): a full-screen layer that holds the room
// and gives the player something to read: what is already known (your orders on their way,
// your own forces under way on a small map), then lines from the setting. While it runs it
// plays the seat's own orders in the order they were filed, each as a step: an order on a
// path as its token on a small copy of that path, a move as its mark on the map; then the
// stakes; then the lines. Every step is timed by the stylesheet alone.

import { h } from '../dom.js';
import { mapDrawing } from './realism-map.js';
import { stakesStrip } from './realism-stakes.js';

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

/** Order lines shown, and orders played; the rest are counted in one line. */
export const ORDER_LINES = 5;

/** How long each step of the playback is on screen: the step delay rules in p5-overlay.css. */
export const STEP_SECONDS = 4;

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

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December'];

/** "18 October 1941" as 19411018, for ordering; null for anything else. */
function dayKey(words) {
  const m = typeof words === 'string' ? words.match(/^(\d{1,2}) ([A-Z][a-z]+) (\d{4})$/) : null;
  const month = m ? MONTHS.indexOf(m[2]) : -1;
  return month < 0 ? null : Number(m[3]) * 10000 + (month + 1) * 100 + Number(m[1]);
}

/** Each of the seat's orders in flight on the court, by order id: its path, square and token. */
function courtTokens(court) {
  const at = new Map();
  for (const path of Array.isArray(court?.paths) ? court.paths : []) {
    for (const step of path.steps ?? []) {
      for (const tok of step.orders ?? []) if (!at.has(tok.id)) at.set(tok.id, { path, step, tok });
    }
  }
  return at;
}

/**
 * What the wake plays: the record's lines in the order they were filed (the record lists
 * newest first; one day keeps filing order), each that is still moving or is a move under way
 * on the map. `steps`: at most `ORDER_LINES`, each `{ kind, order }` plus, for kind 'path', the
 * court's `path`, `step` and `tok`; for kind 'move', the map order `move` and `drawn`, its place
 * among the map's orders under way. A move the map does not animate (past `MAP_MOVES`) is not
 * played. `rest`: how many were not played.
 */
export function playback(orders, map, court) {
  const tokens = courtTokens(court);
  const moves = (map?.orders ?? []).filter((o) => o.status === 'under_way');
  const lines = (Array.isArray(orders) ? [...orders] : []).filter((o) => text(o?.asked)).reverse();
  const filed = lines.map((o, i) => ({ o, i, key: dayKey(o.filed) }))
    .sort((a, b) => (a.key ?? Infinity) - (b.key ?? Infinity) || a.i - b.i)
    .map((x) => x.o);
  const steps = [];
  let rest = 0;
  for (const order of filed) {
    const drawn = order.track ? moves.findIndex((m) => m.order === order.track) : -1;
    let step = null;
    if (order.moving && tokens.has(order.track)) step = { kind: 'path', order, ...tokens.get(order.track) };
    else if (drawn >= 0) step = drawn < MAP_MOVES ? { kind: 'move', order, move: moves[drawn], drawn } : null;
    else if (order.moving) step = { kind: 'line', order };
    else continue;
    if (step && steps.length < ORDER_LINES) steps.push(step);
    else rest += 1;
  }
  return { steps, rest };
}

const days = (n) => (Number.isInteger(n) ? ` of about ${n}` : '; no time stated');

/** A small copy of `path`: a square per decision step, a small mark per clerical one, the token on its holder. */
function pathCopy(path, held, tok) {
  return h('ol', { class: 'rl-ovl-path', 'aria-label': path.name },
    (path.steps ?? []).map((st) => {
      const here = st === held;
      if (st.kind === 'clerical') return h('li', { class: `rl-ovl-clerk${here ? ' holds' : ''}`, 'aria-label': st.name });
      return h('li', { class: `rl-ovl-sq${here ? ' holds' : ''}${st.you ? ' you' : ''}` },
        h('span', { class: 'rl-ovl-who' }, st.you ? 'You' : st.name),
        here ? h('span', { class: 'rl-ovl-tok' }, `day ${tok.held_days + 1}${days(st.days)}`) : null);
    }));
}

function stepBody(s) {
  const o = s.order;
  if (s.kind === 'path') return [pathCopy(s.path, s.step, s.tok)];
  if (s.kind === 'move') return [h('p', { class: 'rl-ovl-how' }, `On the map: ${s.move.force}, under way to ${s.move.to.name}`)];
  const whom = text(o.to) ? `To ${o.to}` : text(o.holder) ? `With ${o.holder}` : null;
  return [
    whom ? h('p', { class: 'rl-ovl-how' }, whom) : null,
    text(o.due) ? h('p', { class: 'rl-ovl-how' }, `Answer due ${o.due}`) : null,
  ];
}

/** The playback: one step per order played, then the stakes; null when there is nothing to play. */
function reel(played, stakes) {
  const strip = stakesStrip(stakes);
  const n = played.steps.length + (strip ? 1 : 0);
  if (!n) return null;
  const cls = (i) => `rl-ovl-step rl-ovl-step-${i + 1}${i === n - 1 ? ' rl-ovl-last' : ''}`;
  const items = played.steps.map((s, i) => h('li', { class: cls(i), 'data-kind': s.kind },
    h('p', { class: 'rl-ovl-cap' }, s.order.asked), ...stepBody(s)));
  if (strip) items.push(h('li', { class: cls(n - 1), 'data-kind': 'stakes' }, strip));
  const more = played.rest;
  return h('section', { class: 'rl-ovl-play', 'aria-label': 'Your orders as filed, then what is at stake' },
    h('ol', { class: 'rl-ovl-reel' }, items),
    more > 0 ? h('p', { class: 'rl-ovl-more' }, `and ${more} more ${more === 1 ? 'order' : 'orders'}`) : null);
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

/** `at`: the playback step of each animated order, by its place among the orders drawn. */
function drawn(map, at) {
  const pic = mapDrawing(map, land, { still: true, compact: true, label: 'Your own forces, and your orders under way' });
  [...pic.querySelectorAll('g.rl-mk-order')].slice(0, MAP_MOVES).forEach((g, i) => {
    g.classList.add('rl-ovl-go', `rl-ovl-go-${i + 1}`);
    if (at.has(i)) g.classList.add(`rl-ovl-at-${at.get(i)}`);
  });
  return pic;
}

function mapFigure(seatMap, played) {
  const map = ownMap(seatMap);
  if (!map) return null;
  const at = new Map(played.steps.flatMap((s, i) => (s.kind === 'move' ? [[s.drawn, i + 1]] : [])));
  const fig = h('figure', { class: 'rl-ovl-map' }, drawn(map, at));
  if (!land) loadLand()?.then(() => { if (land && fig.isConnected) fig.replaceChildren(drawn(map, at)); });
  return fig;
}

function box({ message, lines, map, orders }, { court, stakes }) {
  const items = (lines ?? []).map(text).filter(Boolean).slice(0, OVERLAY_SLOTS);
  const leaving = leavingLines(orders);
  const played = playback(orders, map, court);
  const play = reel(played, stakes);
  const wait = play ? play.querySelectorAll('li.rl-ovl-step').length : 0;
  return h('div', { class: 'rl-ovl-box' },
    h('h2', { id: TITLE_ID, class: 'rl-ovl-msg' }, message),
    mapFigure(map, played),
    play,
    leaving.length
      ? h('section', { class: 'rl-ovl-out', 'aria-label': 'Your orders on their way' },
        h('h3', {}, 'Your orders on their way'),
        h('ul', { class: 'rl-ovl-orders' }, leaving.map((line) => h('li', {}, line))))
      : null,
    items.length
      ? h('ul', { class: `rl-ovl-lines${wait ? ` rl-ovl-wait-${wait}` : ''}` }, items.map((line) => h('li', { class: 'rl-ovl-line' }, line)))
      : null);
}

const built = new WeakMap();

/**
 * A layer `<div class="rl-ovl" role="alertdialog" aria-busy="true">` with `message`, what is
 * already known (`map`: the seat's map, of which only its own marks and orders under way are
 * drawn; `orders`: the record's lines, of which those still moving are listed), and the
 * lines, one shown at a time by a CSS animation only; a still map and a still first line
 * under reduced motion.
 */
export function wakeOverlay(args) {
  const layer = h('div', {
    class: 'rl-ovl',
    role: 'alertdialog',
    'aria-busy': 'true',
    'aria-modal': 'true',
    'aria-labelledby': TITLE_ID,
  }, box(args, {}));
  built.set(layer, args);
  return layer;
}

/**
 * `withPlayback(wakeOverlay(...), { court, stakes })`: the same layer, its box drawn again with
 * the playback before the lines (the room's court and stakes feed it); the lines wait until
 * it has played. Under reduced motion every step stands on screen as a still frame. A layer
 * `wakeOverlay` did not make comes back as it is.
 */
export function withPlayback(layer, { court, stakes } = {}) {
  const args = built.get(layer);
  if (args) layer.replaceChildren(box(args, { court, stakes }));
  return layer;
}
