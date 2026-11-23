// Tracks: a line of steps with the time between them drawn as length. The Court draws each path
// as one (`track`): a stop per decision step, a small mark per clerical step, each step as long
// as its days, an order in flight a marker on the step that holds it. The Sent part of the
// Orders sheet draws each of the seat's orders as four steps (`sentTracks`): filed; who holds
// it, or that it is held and who can allow it; when it lands; the result; a tap opens the
// order. Nothing here works out a day or a holder the view did not send, and nothing touches
// the page on import.

import { h, svg } from '../dom.js';
import { worldDate } from '../rules.js';
import { receiptLine } from './realism-acks.js';
import { NO_ORDERS, orderChip, orderGroups, orderLines } from './realism-orders.js';
import { chip, stepper } from './ui-kit.js';

/** A stop's least width and height: a full tap target. */
export const STOP_PX = 44;
/** A clerical step's mark: never a target, so narrower. */
export const MARK_PX = 24;
/** The fixed short gap a step with no time stated adds to its stop or mark. */
export const UNSTATED_PX = 12;
/** The space between two steps of a track. */
export const SEG_GAP_PX = 2;
/** What a sheet at 390 px takes on each side before a track starts: its padding and the path's. */
export const SHEET_PAD_PX = 24;

const days = (n) => `${n} ${n === 1 ? 'day' : 'days'}`;
const isStated = (n) => Number.isInteger(n) && n >= 0;
/** A step's days in words, or that none was stated. */
export const stated = (n) => (isStated(n) ? days(n) : 'no time stated');

/** The least width in px a track of `steps` takes: each stop or mark at its size, each fixed gap, the space between. */
export function trackMinWidth(steps) {
  const own = (s) => (s.kind === 'clerical' ? MARK_PX : STOP_PX) + (isStated(s.days) ? 0 : UNSTATED_PX);
  return steps.reduce((sum, s) => sum + own(s), 0) + SEG_GAP_PX * Math.max(steps.length - 1, 0);
}

/** How far along a step of `stepDays` an order held `heldDays` stands, 0 to 1; 0 with no time stated. */
export function along(heldDays, stepDays) {
  if (!isStated(stepDays) || stepDays === 0) return 0;
  return Math.min(Math.max((Number(heldDays) || 0) / stepDays, 0), 1);
}

function marker(m) {
  const el = h('span', { class: `rl-trk-marker${m.held ? ' held' : ''}`, 'data-order': m.id }, m.held ? lock() : null);
  el.style?.setProperty('--rl-trk-at', `${Math.round(m.at * 100)}%`);
  return el;
}

function segment(s) {
  const unstated = !isStated(s.days);
  const li = h('li', {
    class: `rl-trk-seg ${s.kind}${unstated ? ' unstated' : ''}`,
    'data-kind': s.kind, 'data-name': s.name, 'data-days': unstated ? null : String(s.days),
  },
  h('span', { class: 'rl-trk-bar', 'aria-hidden': 'true' }, s.markers.map(marker)),
  s.body,
  h('span', { class: 'rl-trk-days' }, s.note ?? stated(s.days)));
  if (!unstated) li.style?.setProperty('--rl-trk-grow', String(s.days));
  return li;
}

/**
 * A track labelled `label`: one segment per `{ name, kind: 'stop' | 'mark', days, body, markers }`
 * in order, each as long as its days beyond its least size (a step with no time stated a fixed
 * short gap), its days written under it (or its `note`), and each marker `{ id, at, held }` on its
 * bar `at` of the way along, a held one with its lock.
 */
export function track(label, segs) {
  return h('ol', { class: 'rl-trk', 'aria-label': label }, segs.map(segment));
}

// --- motion ---------------------------------------------------------------------------------
// Motion shows a change in the game since the board last drew it, once; under reduced motion
// the end state stands at once. What was drawn is kept here, by key, for the next draw.

/** How long a marker, a bloc's part or a count takes to reach its new place `[proposed]`. */
export const MOVE_MS = 600;
/** How long a mark that came due takes to mark itself `[proposed]`. */
export const MARK_MS = 900;
/** The flash a promise's mark plays once on the draw it came due. */
export const DUE_FLASH = [{ opacity: 1 }, { opacity: 0.2 }, { opacity: 1 }, { opacity: 0.2 }, { opacity: 1 }];

const drawn = new Map();

/** What was drawn under `key` the last time (undefined the first time); keeps `now` for the next. */
export function lastDrawn(key, now) {
  const was = drawn.get(key);
  drawn.set(key, now);
  return was;
}

/** Forgets every value kept between draws. */
export const forgetDrawn = () => drawn.clear();

/** Whether the seat's device asks for reduced motion. */
export const reducedMotion = () => Boolean(globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches);

/** Plays `frames` on `el` once; nothing under reduced motion or where the page cannot animate. */
export function play(el, frames, ms = MOVE_MS) {
  if (!el || reducedMotion() || typeof el.animate !== 'function') return null;
  return el.animate(frames, { duration: ms, easing: 'ease-in-out' });
}

/**
 * Writes `say(to)` into `el`; when `from` differs, it first runs from `say(from)` through the
 * numbers between, ending on `to`. Each of `from` and `to` is a list of numbers.
 */
export function runCount(el, from, to, say, ms = MOVE_MS) {
  el.textContent = say(to);
  if (!from || reducedMotion() || from.every((n, i) => n === to[i])) return;
  const frames = Math.max(1, Math.round(ms / 50));
  const at = (k) => to.map((n, i) => Math.round(from[i] + ((n - from[i]) * k) / frames));
  el.textContent = say(from);
  for (let k = 1; k <= frames; k += 1) setTimeout(() => { el.textContent = say(at(k)); }, (ms * k) / frames);
}

/** A held order's lock, drawn on its marker. */
const lock = () => svg('svg', { class: 'rl-trk-lock', viewBox: '0 0 10 12', width: 10, height: 12, 'aria-hidden': 'true', focusable: 'false' },
  svg('path', { d: 'M2.5 5V3.5a2.5 2.5 0 0 1 5 0V5' }), svg('rect', { x: 1, y: 5, width: 8, height: 6, rx: 1 }));

/**
 * Slides marker `m` from where it stood last drawn (`from`: `{ step, at }`) to where it stands,
 * once the page has laid the track out: the bars of the two steps give the distance.
 */
export function slideMarker(m, from, to) {
  if (!from || (from.step === to.step && from.at === to.at) || reducedMotion()) return;
  const next = globalThis.requestAnimationFrame ?? ((f) => setTimeout(f, 0));
  next(() => {
    const bars = m.closest('ol.rl-trk')?.querySelectorAll('.rl-trk-bar') ?? [];
    const was = bars[from.step];
    const now = bars[to.step];
    if (!was?.getBoundingClientRect || !now?.getBoundingClientRect) return;
    const a = was.getBoundingClientRect();
    const b = now.getBoundingClientRect();
    const dx = Math.round(a.left + from.at * a.width - (b.left + to.at * b.width));
    if (dx) play(m, [{ transform: `translateX(${dx}px)` }, { transform: 'none' }]);
  });
}

/**
 * Whether the thing kept as `key` came due on this draw: its day `due` is reached by `today`
 * and either the last draw saw it not yet due, or this is the first draw and today is its day.
 */
export function cameDue(key, due, today) {
  const now = Boolean(due && today && due <= today);
  const was = lastDrawn(`due:${key}`, now);
  return now && (was === false || (was === undefined && due === today));
}

// --- the Sent part ---------------------------------------------------------------------------

const KIT_TONE = { need: 'warn', moving: 'info', ok: 'ok', bad: 'danger', quiet: 'quiet' };

/** A record entry's four steps as `[state, words]`; `t` is its tracker order, if any. */
export function entrySteps(e, t) {
  const filed = ['done', `Filed ${e.filed}`];
  if (e.moving) {
    const holder = t?.decision_needed ? ['due', 'Needs you'] : ['now', `With ${e.holder ?? e.to ?? 'your staff'}`];
    return [filed, holder, ['next', e.due ? `Answer due ${e.due}` : 'On its way'], ['next', 'Result']];
  }
  const result = orderChip(e, t);
  return [filed, ['done', e.to ? `To ${e.to}` : 'Passed on'], ['done', e.settled ? `Settled ${e.settled}` : 'Settled'],
    [result.tone === 'bad' ? 'bad' : 'done', result.word]];
}

/** A held order's four steps: filed, held with who can allow it, sent only when allowed, no result yet. */
export function heldSteps(l) {
  return [['done', `Filed ${worldDate(l.held)}`], ['held', `Held: ${l.who} can allow it, ${l.asked ? 'asked' : 'not asked'}`],
    ['next', 'Sent when allowed'], ['next', 'Result']];
}

function orderItem({ id, ask, steps, open, onToggle, body }) {
  return h('li', { class: 'rl-oc-card rl-sent-order', 'data-order': id },
    h('button', { type: 'button', class: 'rl-sent-head', 'aria-expanded': String(open), onclick: () => onToggle?.(id) },
      h('span', { class: 'rl-sent-ask' }, ask),
      h('span', { class: 'rl-sent-track' },
        steps.map(([state, text]) => h('span', { class: 'rl-sent-step', 'data-state': state }, text)))),
    open ? h('div', { class: 'rl-sent-body' }, body()) : null);
}

/**
 * The Sent part: the seat's orders as tracks, what waits on the seat first (open, with
 * `stepForm(trackerOrder)` under it), then the moving, then the held (`held`, the locks block's
 * own held orders), then a folded "Finished (n)". `record` is view.realism.record, `tracker`
 * view.realism.orders. A tap on an order calls `onToggle(id)`; the order `opened` is drawn open,
 * with its lines, its paper (`onOpen({ id })`) and its steps.
 */
export function sentTracks(record, tracker, held = [], { stepForm, onOpen, opened = null, onToggle } = {}) {
  const head = h('h2', { id: 'rl-oc-h' }, 'Your orders');
  if (!(record?.orders ?? []).length && !held.length) {
    return h('section', { class: 'rl-oc rl-sent', 'aria-labelledby': 'rl-oc-h' }, head, h('p', { class: 'rl-oc-empty' }, NO_ORDERS));
  }
  const trackerOrder = (e) => (tracker?.orders ?? []).find((o) => o.id === e.track) ?? null;
  const entry = (e, need = false) => {
    const t = trackerOrder(e);
    const status = orderChip(e, t);
    return orderItem({
      id: e.id, ask: e.asked, steps: entrySteps(e, t), open: need || opened === e.id, onToggle,
      body: () => [chip(status.word, KIT_TONE[status.tone]), orderLines(e).map((line) => h('p', { class: 'rl-oc-line' }, line)),
        receiptLine(e.receipt, onOpen), t ? stepper(t.steps, t.at_step) : null, need && t ? stepForm?.(t) : null],
    });
  };
  const heldItem = (l) => orderItem({
    id: l.id, ask: l.words, steps: heldSteps(l), open: opened === l.id, onToggle,
    body: () => [h('p', { class: 'rl-oc-line' }, l.reason), h('p', { class: 'rl-oc-line' }, `Held ${worldDate(l.held)}`),
      h('p', { class: 'rl-oc-line' }, l.asked ? 'Asked' : 'Not asked')],
  });
  const { need, moving, finished } = orderGroups(record, tracker);
  const active = [...need.map((e) => entry(e, true)), ...moving.map((e) => entry(e)), ...held.map(heldItem)];
  return h('section', { class: 'rl-oc rl-sent', 'aria-labelledby': 'rl-oc-h' },
    head,
    active.length ? h('ul', { class: 'rl-sent-list', role: 'list' }, active) : null,
    finished.length ? h('details', { class: 'rl-sent-done', open: finished.some((e) => e.id === opened) },
      h('summary', {}, `Finished (${finished.length})`),
      h('ul', { class: 'rl-sent-list', role: 'list' }, finished.map((e) => entry(e)))) : null,
    h('p', { class: 'hint rl-sent-hint' }, 'Each order is one track: filed, who holds it, when it lands, what came of it. Tap one to open it.'));
}
