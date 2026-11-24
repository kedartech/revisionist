// The room's four marks (VIZ): a bar (a value against a limit), a meter (a band of five steps), a
// track (time left against a span) and pips (a small count). Each is an image with a name that
// says its number and the number drawn on it; the drawing itself is hidden from a reader. A mark
// draws only the values it is handed: the caller passes what the seat's view sent, and the mark
// works out nothing but its length. A tone is a class (c-marks.css): `own`, `due`, `hostile` or
// neutral; a hostile bar's fill is hatched as well, so no mark rests on colour alone.
// Nothing here touches the page on import.

import { h, svg } from '../dom.js';

/** A number as the room writes it: whole, or to two places at most. */
export const markNum = (n) => (Number.isInteger(n) ? String(n) : String(Number(Number(n).toFixed(2))));

const share = (value, limit) => {
  const v = Number(value);
  const of = Number(limit);
  if (!(of > 0) || !Number.isFinite(v)) return 0;
  return Number(Math.min(100, Math.max(0, (100 * v) / of)).toFixed(2));
};

function shell(kind, { name, words, tone, extra }, ...children) {
  if (!name) throw new Error('a mark needs a name that says its number');
  return h('span', {
    class: `rl-mark rl-mark-${kind}${tone ? ` rl-mark-${tone}` : ''}${extra ? ` ${extra}` : ''}`,
    role: 'img', 'aria-label': words,
  }, ...children);
}

const numSpan = (text) => h('span', { class: 'rl-mark-num', 'aria-hidden': 'true' }, text);

let hatchN = 0;

/**
 * The drawing of a bar or a track: a track and its fill in a 100-long box, so no length is a style.
 * A hostile fill is hatched by a pattern of its own, so it never rests on colour alone.
 */
function drawing(pct, column, hostile = false) {
  const box = column ? '0 0 8 100' : '0 0 100 8';
  const fill = column
    ? { x: 0, y: Number((100 - pct).toFixed(2)), width: 8, height: pct }
    : { x: 0, y: 0, width: pct, height: 8 };
  let defs = null;
  if (hostile) {
    hatchN += 1;
    const id = `rl-mark-hatch-${hatchN}`;
    defs = svg('defs', {}, svg('pattern', { id, width: 3, height: 3, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' },
      svg('rect', { class: 'rl-mark-hatch-bg', width: 3, height: 3 }),
      svg('line', { class: 'rl-mark-hatch', x1: 0, y1: 0, x2: 0, y2: 3 })));
    fill.fill = `url(#${id})`;
  }
  return svg('svg', { class: 'rl-mark-draw', viewBox: box, preserveAspectRatio: 'none', 'aria-hidden': 'true', focusable: 'false' },
    defs,
    svg('rect', { class: 'rl-mark-track', x: 0, y: 0, width: column ? 8 : 100, height: column ? 100 : 8 }),
    svg('rect', { class: 'rl-mark-fill', 'data-share': String(pct), ...fill }));
}

/**
 * `bar({ value, limit, name, unit, tone, column, num, words, label })`: `value` against `limit`,
 * named "<name>: <value> of <limit> <unit>" unless `words` names it. `column` stands it upright,
 * filled from its foot. `num: false` leaves the number to the words the caller sets beside it;
 * `label` is the number drawn on the mark when it is not `value` itself.
 */
export function bar({ value, limit, name, unit = '', tone = null, column = false, num = true, words = null, label = null, extra = null }) {
  const said = words ?? `${name}: ${markNum(value)} of ${markNum(limit)}${unit ? ` ${unit}` : ''}`;
  return shell('bar', { name, words: said, tone, extra: [column ? 'rl-mark-col' : null, extra].filter(Boolean).join(' ') },
    drawing(share(value, limit), column, tone === 'hostile'),
    num ? numSpan(label ?? markNum(value)) : null);
}

/** `meter({ step, of, name, word })`: a band as `of` steps (five), its own and those under it on. */
export function meter({ step, of = 5, name, word = null, tone = null }) {
  const n = Math.max(0, Math.min(of, Math.round(Number(step) || 0)));
  return shell('meter', { name, words: `${name}: ${word ? `${word}, ` : ''}${n} of ${of}`, tone },
    h('span', { class: 'rl-mark-steps', 'aria-hidden': 'true' },
      Array.from({ length: of }, (_, i) => h('span', { class: `rl-mark-step${i < n ? ' on' : ''}` }))),
    numSpan(String(n)));
}

/**
 * `track({ left, span, name, unit })`: time left against the span the view sent, so of two tracks
 * on one span the nearer end is the shorter. Named "<name>: 6 days left of 24".
 */
export function track({ left, span, name, unit = 'days', tone = null }) {
  const one = unit.replace(/s$/, '');
  const n = Number(left);
  const words = `${name}: ${markNum(n)} ${n === 1 ? one : unit} left of ${markNum(span)}`;
  return shell('track', { name, words, tone },
    drawing(share(n, span), false, tone === 'hostile'),
    numSpan(`${markNum(n)} ${n === 1 ? one : unit}`));
}

/** `pips({ count, of, name })`: a small count as `of` pips, as many on as `count`. */
export function pips({ count, of, name, tone = null }) {
  const n = Math.max(0, Math.min(of, Math.round(Number(count) || 0)));
  return shell('pips', { name, words: `${name}: ${n} of ${of}`, tone },
    h('span', { class: 'rl-mark-dots', 'aria-hidden': 'true' },
      Array.from({ length: of }, (_, i) => h('span', { class: `rl-mark-pip${i < n ? ' on' : ''}` }))),
    numSpan(String(n)));
}
