// Pieces under way, drawn on their way. An own piece on a step is drawn between the area it left
// and the area it is entering, at the share of the step's days gone, worked from the two days the
// reply sends (the day the step began and the day it falls due) and today; nothing else moves it.
// Travel is linear in time so that it reads as a rate. A course just sent draws itself once, a
// territory that changes hands fills evenly, and the playback can place any own mark at a share
// of a step and run a clock of world days. Under reduced motion nothing moves: each piece stands
// where its days put it.

/** How long a course just sent takes to draw itself from the piece to its goal. [proposed] */
export const COURSE_DRAW_MS = 600;
/** How long a territory that changed hands takes to fill with its new holder's tone. */
export const FILL_MS = 600;

const DAY_MS = 86_400_000;
const dayOf = (iso) => (typeof iso === 'string' ? Date.parse(`${iso.slice(0, 10)}T00:00:00Z`) / DAY_MS : Number.NaN);
const r2 = (n) => Math.round(n * 100) / 100;

/**
 * How far along its step a piece under way is on `today`: { gone, days, share }, the whole days
 * since the step began (never past its days), the step's days and their ratio. Null when the
 * course lacks either day, `today` is not given, or the step takes no days.
 */
export function stepShare(course, today) {
  const began = dayOf(course?.step_began);
  const due = dayOf(course?.step_due);
  const now = dayOf(today);
  const days = due - began;
  if (![began, due, now].every(Number.isFinite) || !(days > 0)) return null;
  const gone = Math.min(days, Math.max(0, now - began));
  return { gone, days, share: gone / days };
}

/** The point `share` of the way from `a` to `b`, in a straight line. */
export const between = (a, b, share) => [r2(a[0] + (b[0] - a[0]) * share), r2(a[1] + (b[1] - a[1]) * share)];

/** A step under way as its tag says it: "day 3 of 5 into Smolensk"; the first day is day 1. */
export const stepTag = ({ gone, days }, name) => `day ${Math.max(1, gone)} of ${days} into ${name}`;

/**
 * Where mark `m` is drawn while under way, from `labelAt` (area key to point) and `today`:
 * { from, to, at, gone, days, share, tag }, or null for a mark that is not the seat's own piece
 * on a step both of whose areas are drawn. Another side's mark is never drawn in transit.
 */
export function underWay(m, labelAt, today) {
  if (m?.side !== 'own' || !m.piece) return null;
  const course = m.piece.under_way;
  const step = course?.path?.[0];
  const from = labelAt.get(m.piece.area?.key);
  const to = labelAt.get(step?.key);
  const where = from && to ? stepShare(course, today) : null;
  if (!where) return null;
  return { from, to, at: between(from, to, where.share), ...where, tag: stepTag(where, step.name) };
}

/** The first `share` of the line through `points`, by length. */
export function partOf(points, share) {
  if (points.length < 2 || share >= 1) return points.map((p) => [...p]);
  const legs = points.slice(1).map((p, i) => Math.hypot(p[0] - points[i][0], p[1] - points[i][1]));
  let left = Math.max(0, share) * legs.reduce((a, b) => a + b, 0);
  const out = [[...points[0]]];
  for (let i = 0; i < legs.length; i += 1) {
    if (left >= legs[i]) { out.push([...points[i + 1]]); left -= legs[i]; continue; }
    out.push(between(points[i], points[i + 1], legs[i] ? left / legs[i] : 0));
    break;
  }
  return out;
}

const clockOf = (opts) => ({
  now: opts.now ?? (() => globalThis.performance?.now?.() ?? Date.now()),
  frame: opts.frame ?? (typeof globalThis.requestAnimationFrame === 'function' ? (cb) => globalThis.requestAnimationFrame(cb) : null),
});

/**
 * Run `each(share)` from 0 to 1 over `ms`, linearly, one call a frame (`opts.now`, `opts.frame`:
 * the clock, a page's by default). With `opts.still`, or no frames to run on, it is called once at 1.
 */
export function run(ms, each, opts = {}) {
  const { now, frame } = clockOf(opts);
  if (opts.still || !frame) { each(1); return { stop() {} }; }
  const t0 = now();
  let stopped = false;
  const tick = () => {
    if (stopped) return;
    const share = Math.min(1, (now() - t0) / ms);
    each(share);
    if (share < 1) frame(tick);
  };
  each(0);
  frame(tick);
  return { stop() { stopped = true; } };
}

const pointsOf = (el) => (el.getAttribute('points') ?? '').trim().split(/\s+/).filter(Boolean).map((p) => p.split(',').map(Number));

/** Polyline or line `el` draws itself from its first point to its last over COURSE_DRAW_MS. */
export function drawOn(el, opts = {}) {
  if (!el.hasAttribute('points')) {
    const [x1, y1, x2, y2] = ['x1', 'y1', 'x2', 'y2'].map((a) => Number(el.getAttribute(a)));
    return run(COURSE_DRAW_MS, (share) => {
      const [x, y] = between([x1, y1], [x2, y2], share);
      el.setAttribute('x2', String(x));
      el.setAttribute('y2', String(y));
    }, opts);
  }
  const points = pointsOf(el);
  return run(COURSE_DRAW_MS, (share) => {
    el.setAttribute('points', partOf(points, share).map((p) => p.join(',')).join(' '));
  }, opts);
}

/** Element `el` (a held territory's tone) fills evenly from nothing over FILL_MS. */
export function fillIn(el, opts = {}) {
  return run(FILL_MS, (share) => {
    if (share >= 1) el.removeAttribute('fill-opacity');
    else el.setAttribute('fill-opacity', String(r2(share)));
  }, opts);
}

/**
 * A clock of world days for the playback: `onDay(day)` in every frame with the world days gone
 * (a fraction, linear in time), from 0 to `days` at `msPerDay`, then `onEnd()`. With `opts.still`
 * it is called once at `days`. `stop()` ends it where it stands.
 */
export function worldClock({ days, msPerDay, onDay, onEnd }, opts = {}) {
  return run(Math.max(0, days) * msPerDay, (share) => {
    onDay?.(r2(share * days));
    if (share >= 1) onEnd?.();
  }, opts);
}

/**
 * Place own mark `key` on drawing `root` `share` of the way from area `from` to area `to` (the
 * area labels' points). Returns the point, or null when the mark or either area is not drawn.
 */
export function placeMark(root, key, from, to, share) {
  const areaPoint = (k) => {
    const l = [...root.querySelectorAll('.rl-tm-label')].find((g) => g.getAttribute('data-area') === k);
    return l ? [Number(l.getAttribute('data-x')), Number(l.getAttribute('data-y'))] : null;
  };
  const mark = [...root.querySelectorAll('.rl-tm-mark')].find((g) => g.getAttribute('data-key') === key && g.classList.contains('rl-side-own'));
  const [a, b] = [areaPoint(from), areaPoint(to)];
  if (!mark || !a || !b) return null;
  const at = between(a, b, Math.min(1, Math.max(0, share)));
  const k = Number(root.getAttribute('data-k')) || 1;
  mark.setAttribute('data-x', String(at[0]));
  mark.setAttribute('data-y', String(at[1]));
  mark.setAttribute('transform', `translate(${at[0]} ${at[1]}) scale(${k})`);
  return at;
}
