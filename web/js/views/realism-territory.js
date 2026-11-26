// The territory map: in a game whose `map` block has `areas`, the board is drawn from the
// game's map file (the `map` action's shapes): land territories filled, sea zones outlined,
// every border stroked. The frame is a region's, worked out from its areas alone, and holds
// still whatever lights or lands; the view pans and zooms from 1 to 8 times within it, live
// under the finger, and the zoom buttons stop at 1, 2 and 4. Marks and tap targets keep a
// minimum size in pixels whatever the zoom. Every area is focusable and has a row in the list.
// One of the seat's own pieces can be carried by the finger to a lit area, as a tap picks it
// and a tap on the lit area puts it down. In the map-first room the controls sit over the map's
// corners, and the map can take the whole viewport.

import { h, svg } from '../dom.js';
import {
  LABEL_PX, MIN_MARK_PX, MIN_TAP_PX, SLIDE_MS, ZOOMS, borders, boxOf, certaintyWord, courseLine, frameRect, hiddenLabels,
  markArea, markKey, pipsOf, postureWord, regionChildren, regionFrames, regionTrail, shortDate, sideLine,
  sightedLine, slideFrom, sortMarks, stanceWords, capitalLine, territoryProjection, unitsPerPx, viewWindow, waitWords,
  whereLine, changedLine, fallingLine, frontLine, holderRelation, holderWords, isFront, yieldsLine,
} from '../realism-rules.js';
import { gestures } from '../map/gestures.js';
import { askedForFull, browserFull, clampZoom } from '../map/view.js';
import { areaAt } from '../map/hit.js';
import { trace } from '../map/projection.js';
import { drawOn, fillIn, underWay } from '../map/motion.js';
import { economyPips, hasYields } from './realism-economy.js';
import { capitalGlyph, forceGlyph, pipGlyph, stanceClass, warGlyph, whatWord } from './realism-map.js';
import { reportMarks, reportSheet, reportTables, reportsOf, ringsAndThreats, threatsSwitch, tokenMark } from './realism-reports.js';
import { battleLayer, battleTable } from './realism-battle.js';
import { bandOf } from './realism-home.js';
import { heldWords, lockMark, lockWords } from './realism-locks.js';

const r2 = (n) => Math.round(n * 100) / 100;

/** Each drawing's clip path needs an id of its own on the page. */
let clips = 0;

/** How far above its area's label point a piece is drawn (its pips and posture go under it), and the gap between pieces side by side, in pixels. */
const MARK_LIFT = 50;
const MARK_GAP = 44;

/** Where each mark last stood, by its key, so that a mark whose area changes slides there. */
const lastAt = new Map();

/**
 * What the last drawings showed, so that a course or an order just sent draws itself once and a
 * territory that changed hands fills: each own mark's course, each order, each area's holder.
 * Nothing is new to the first drawing after `forgetMarks`.
 */
const shown = { courses: new Map(), orders: new Map(), holders: new Map(), primed: false };

/** Forget where every mark stood and what the drawings showed (tests). */
export function forgetMarks() {
  lastAt.clear();
  shown.courses.clear();
  shown.orders.clear();
  shown.holders.clear();
  shown.primed = false;
}

/** Whether `value` under `key` in `memory` (a Map) is new since the last drawing; notes it. */
function changed(memory, key, value) {
  const was = memory.has(key) ? memory.get(key) : '';
  memory.set(key, value);
  return shown.primed && was !== value;
}

export { forgetFull } from '../map/view.js';

const reducedMotion = () => Boolean(globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches);

/** The glyph a piece's domain draws with. */
const GLYPH = Object.freeze({ land: 'army', sea: 'fleet', air: 'air', envoy: 'envoy' });

/** The seat's envoys: the only pieces the Diplomatic layer draws (DPL). */
const envoyMarks = (map) => (map.marks ?? []).filter((m) => m.piece?.domain === 'envoy');

export const areaKindWord = (area) => (area.kind === 'sea' ? 'Sea zone' : 'Land territory');

/** How each holder standing is patterned, so that a tint is never colour alone. */
const HOLD_PATTERNS = Object.freeze({
  own: { name: 'stripes', d: 'M0 3H8M0 7H8' },
  ally: { name: 'diagonal', d: 'M-1 9L9 -1M-1 5L5 -1M3 9L9 3' },
  enemy: { name: 'cross', d: 'M-1 9L9 -1M-1 5L5 -1M3 9L9 3M-1 -1L9 9M-1 3L5 9M3 -1L9 5' },
  neutral: { name: 'dots', d: 'M2 2h0.01M6 6h0.01', round: true },
});

/** The text twin of an area's holder: "held by Norra (yours)" for a held area, else ''. */
const heldBy = (a) => (a.holder ? `, held by ${holderWords(a)}` : '');

/** The pattern fills for the standings drawn, ids made from `tag`. */
function holdPatterns(standings, tag) {
  return [...standings].map((rel) => {
    const p = HOLD_PATTERNS[rel];
    return svg('pattern', { id: `${tag}-${rel}`, width: 8, height: 8, patternUnits: 'userSpaceOnUse', 'data-pattern': p.name },
      svg('rect', { width: 8, height: 8, class: `rl-hp-ground rl-hold-${rel}` }),
      svg('path', { d: p.d, class: `rl-hp-line rl-hold-${rel}${p.round ? ' rl-hp-dot' : ''}` }));
  });
}

/** The layers with something to draw, Military first: a layer with nothing yet is not offered. */
export function offeredLayers(map) {
  const out = [];
  if ((map.marks ?? []).length || (map.orders ?? []).length || reportsOf(map).length) out.push('military');
  if ((map.capitals ?? []).length || envoyMarks(map).length) out.push('diplomatic');
  return out;
}

/** The pixel box the map is likely drawn into, until the drawing is measured. */
function guessPx() {
  const w = Number(globalThis.innerWidth) || 1440;
  const hgt = Number(globalThis.innerHeight) || 900;
  if (w < 1024) return { width: Math.max(w - 24, 200), height: Math.max(hgt * 0.5, 200) };
  return { width: Math.max(w - 480, 320), height: Math.max(hgt - 160, 320) };
}

/** The SVG path of `rings` (vertex indices), each drawn by `line` (map coordinates to the drawing's points). */
function ringsPath(vertices, rings, line) {
  return rings.map((ring) => `M${line(ring.map((i) => vertices[i])).map((xy) => xy.join(' ')).join('L')}Z`).join('');
}

/** A group drawn at (x, y) in the drawing's units, its contents in pixels (`fit` scales it). */
function atPx(attrs, x, y, ...children) {
  return svg('g', { ...attrs, class: `${attrs.class} rl-tm-px`, 'data-x': r2(x), 'data-y': r2(y) }, ...children);
}

/** Focusable and pressable; `keys` maps any other key to what it does. */
const activate = (fn, keys = {}) => ({
  tabindex: 0,
  role: 'button',
  onclick: fn,
  onkeydown: (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn(); return; }
    if (keys[e.key]) { e.preventDefault(); keys[e.key](e); }
  },
});

const NEXT = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };

/** Arrow keys from a lit area or the picked piece: `step(dir)` for each. */
const arrows = (step) => Object.fromEntries(Object.entries(NEXT).map(([k, dir]) => [k, () => step(dir)]));

/**
 * Size every pixel-sized part of drawing `root` for `px` ({ width, height }, CSS pixels): marks
 * and labels keep their size whatever the window, and, when `labels` is true, a label that would
 * overlap one drawn before it is hidden (shown again on a tap of its area).
 */
export function fit(root, px, labels = true) {
  const [x, y, w, hgt] = root.getAttribute('viewBox').split(' ').map(Number);
  const k = unitsPerPx({ x, y, w, h: hgt }, px);
  root.setAttribute('data-k', String(k));
  for (const g of root.querySelectorAll('.rl-tm-px')) {
    g.setAttribute('transform', `translate(${g.getAttribute('data-x')} ${g.getAttribute('data-y')}) scale(${k})`);
  }
  if (!labels) return k;
  const all = [...root.querySelectorAll('.rl-tm-label')];
  const hide = hiddenLabels(all.map((l) => ({
    key: l.getAttribute('data-area'), x: Number(l.getAttribute('data-x')), y: Number(l.getAttribute('data-y')), text: l.getAttribute('data-text'),
  })), k);
  for (const l of all) l.classList.toggle('hidden', hide.has(l.getAttribute('data-area')));
  return k;
}

/**
 * A piece carried over drawing `root` (`gestures`' carry hooks): it is drawn lifted where the
 * finger has taken it, and the lit area under the finger is marked. Dropped on a lit area it is
 * that area's target, as a tap on it is (`opts.onTarget`); anywhere else it slides back. Picking
 * it up is `opts.onSelect`, as a tap on it is. `over` holds the marks and lit areas (it rides
 * over the land while the view moves), `litAt(units)` finds the lit area under a point.
 */
function carrying(root, over, litAt, opts) {
  const all = (el, sel) => Array.from(el?.querySelectorAll(sel) ?? []);
  const grabbed = (key) => all(over, '[data-grab]').find((g) => g.getAttribute('data-grab') === key) ?? null;
  let shown = '';
  const mark = (key) => {
    for (const el of all(root, '.rl-area.rl-drop-over')) el.classList.remove('rl-drop-over');
    for (const el of all(over, '.rl-map-target.under')) el.classList.remove('under');
    if (key === null) return;
    all(over, '.rl-map-target').find((t) => t.getAttribute('data-area') === key)?.classList.add('under');
    all(root, '.rl-area').find((a) => a.getAttribute('data-area') === key)?.classList.add('rl-drop-over');
  };
  return {
    grab: (target) => target?.closest?.('[data-grab]')?.getAttribute('data-grab') ?? null,
    carries: (key) => grabbed(key) !== null,
    onLift: (key) => { if (opts.selected !== key) opts.onSelect?.(key); },
    onCarry(key, [dx, dy], units) {
      const g = grabbed(key);
      if (!g) return;
      g.classList.add('rl-tm-lifted');
      // drawn over everything, the lit rings too, while it is held
      if (g.parentNode?.parentNode === over && over.lastChild !== g.parentNode) over.append(g.parentNode);
      shown = `translate(${r2(dx)}px, ${r2(dy)}px)`;
      css(g.parentNode, { transform: shown });
      mark(units ? litAt(units)?.area ?? null : null);
    },
    onDrop(key, units) {
      const g = grabbed(key);
      const lit = units ? litAt(units) : null;
      mark(null);
      if (g) {
        g.classList.remove('rl-tm-lifted');
        css(g.parentNode, { transform: null });
        if (!lit && shown && !reducedMotion()) {
          g.parentNode.animate?.([{ transform: shown }, { transform: 'translate(0px, 0px)' }], { duration: SLIDE_MS, easing: 'ease-out' });
        }
      }
      shown = '';
      if (lit) opts.onTarget?.(lit.value);
    },
  };
}

const viewBoxOf = (win) => `${r2(win.x)} ${r2(win.y)} ${r2(win.w)} ${r2(win.h)}`;

/** Inline style through the CSS object model: the page's CSP refuses a `style` attribute. */
function css(el, props) {
  for (const [k, v] of Object.entries(props)) {
    if (v === null) el.style?.removeProperty(k);
    else el.style?.setProperty(k, v);
  }
}

/**
 * What a gesture on drawing `root` draws in each frame (`gestures`' `onLive`). The land keeps
 * its drawing and is moved as one picture, by a transform the browser applies without drawing
 * the land again; the marks and labels move into a layer of their own over it, drawn at the
 * view as it now is and at their pixel size. When the gesture ends they go back and the drawing
 * shows the new view. A drawing not on a page is drawn at the view itself in each frame.
 */
function liveLayer(root, px) {
  let b = null;
  let rest = null;
  let layer = null;
  let over = null;
  let had = null;
  return (win, { labels, end }) => {
    if (end) {
      if (layer) {
        root.querySelector('g.rl-tm-frame')?.append(over);
        layer.remove();
      }
      css(root, { transform: null, 'transform-origin': null });
      root.classList.remove('rl-tm-moving');
      root.setAttribute('viewBox', viewBoxOf(win));
      fit(root, b ?? px, true);
      had?.focus();
      b = null; rest = null; layer = null; over = null; had = null;
      return;
    }
    if (!b) {
      const m = root.getBoundingClientRect?.();
      b = m?.width ? m : { left: 0, top: 0, width: px.width, height: px.height };
      const [x, y, w, h] = root.getAttribute('viewBox').split(' ').map(Number);
      rest = { x, y, w, h };
      over = root.querySelector('g.rl-tm-over');
      const parent = root.parentNode;
      if (parent && over) {
        const pb = parent.getBoundingClientRect?.() ?? { left: b.left, top: b.top };
        const active = globalThis.document?.activeElement;
        had = active?.closest?.('g.rl-tm-over') === over ? active : null;
        layer = svg('svg', { class: 'rl-tm-live', 'aria-hidden': 'true', preserveAspectRatio: 'xMidYMid meet' }, over);
        css(layer, { left: `${r2(b.left - pb.left)}px`, top: `${r2(b.top - pb.top)}px`, width: `${r2(b.width)}px`, height: `${r2(b.height)}px` });
        root.after(layer);
        root.classList.add('rl-tm-moving');
      }
    }
    if (!layer) {
      root.setAttribute('viewBox', viewBoxOf(win));
      fit(root, b, labels);
      return;
    }
    const k0 = unitsPerPx(rest, b);
    const k = unitsPerPx(win, b);
    const s = k0 / k;
    const off = (r, kk) => [(b.width - r.w / kk) / 2, (b.height - r.h / kk) / 2];
    const [o0, o] = [off(rest, k0), off(win, k)];
    const tx = o[0] + (rest.x - win.x) / k - s * o0[0];
    const ty = o[1] + (rest.y - win.y) / k - s * o0[1];
    css(root, { transform: `translate(${r2(tx)}px, ${r2(ty)}px) scale(${Math.round(s * 1e4) / 1e4})`, 'transform-origin': '0 0' });
    layer.setAttribute('viewBox', viewBoxOf(win));
    fit(layer, b, labels);
  };
}

/** What a mark is: an own piece's kind as the world names it, "Piece" for another side's piece (a page does not name its kind), else the mark's kind. */
const markWhat = (m) => m.piece?.kind ?? (m.kind === 'piece' ? 'Piece' : whatWord(m));

/** Where a mark stands, in words: an own piece's area, the area a page places it in, else its places. */
const markWhere = (m) => m.piece?.area?.name ?? m.area?.name ?? whereLine(m);

/** The seat's held orders on mark `m`, as the drawing's `held` option gives them (none in a still drawing). */
const heldOf = (m, opts) => opts.held?.(m) ?? [];

function markLabel(m, where, held = [], tag = null) {
  const p = m.piece;
  const said = [
    `${m.name}: ${markWhat(m)}, ${sideLine(m)}, ${certaintyWord(m.certainty)}${where ? `, ${where}` : ''}`,
    p?.posture ? postureWord(p.posture) : null,
    p?.under_way ? courseLine(p.under_way) : null,
    tag,
    p?.waiting ? `Order ${waitWords(p.waiting)}` : null,
    ...held.map(heldWords),
  ];
  return said.filter(Boolean).join('; ');
}

/**
 * Where a mark stands: an own piece under way on its step, at the share of the step's days gone
 * by `today`; any other own piece at its area's label point, a reported one at the label point
 * of the area its page names, else at its one place.
 */
function markAt(m, labelAt, at, today = null) {
  const way = underWay(m, labelAt, today);
  if (way) return way.at;
  if (m.piece?.area?.key && labelAt.has(m.piece.area.key)) return labelAt.get(m.piece.area.key);
  if (m.area?.key && labelAt.has(m.area.key)) return labelAt.get(m.area.key);
  return m.places?.length === 1 ? at([m.places[0].lon, m.places[0].lat]) : null;
}

/**
 * `child`, drawn at `xy`, in a group that slides it there from `from` over SLIDE_MS; with no
 * `from`, or under reduced motion, it stands there at once. An own piece travels linearly, so
 * that it reads as a rate; another side's sighting keeps its eased slide.
 */
function sliding(child, xy, from, own = false) {
  const g = svg('g', { class: 'rl-tm-slide' }, child);
  if (!from || reducedMotion()) return g;
  g.setAttribute('data-slide-from', from.join(' '));
  g.animate?.([
    { transform: `translate(${r2(from[0] - xy[0])}px, ${r2(from[1] - xy[1])}px)` }, { transform: 'translate(0px, 0px)' },
  ], { duration: SLIDE_MS, easing: own ? 'linear' : 'ease-in-out' });
  return g;
}

/** The marker of mark `m`, centred on (0, 0): an own piece with its pips under it, its posture as a word, its step's tag when it is under way, and its strength in figures only when it is picked. */
function markBody(m, chosen, tag = null) {
  const pips = pipsOf(m.piece);
  const r = MIN_MARK_PX / 2;
  const below = r + 3;
  const pip = Math.max(MIN_MARK_PX / 4, 4);
  const posture = postureWord(m.piece?.posture);
  const pipsWide = pips ? (pips.slots * pip * 1.4 - pip * 0.4) / 2 : 0;
  return [
    svg('rect', { x: -MIN_TAP_PX / 2, y: -MIN_TAP_PX / 2, width: MIN_TAP_PX, height: MIN_TAP_PX, class: 'rl-tm-hit' }),
    chosen ? svg('circle', { r: MIN_MARK_PX * 0.95, class: 'rl-mk-ring' }) : null,
    forceGlyph({ ...m, kind: m.piece ? GLYPH[m.piece.domain] : m.kind }, MIN_MARK_PX),
    pips ? pipGlyph(pips, pip * 5, below) : null,
    pips && chosen
      ? svg('text', { x: r2(pipsWide + 3), y: r2(below + pip), 'font-size': LABEL_PX, class: 'rl-pip-num' }, String(pips.filled))
      : null,
    posture
      ? svg('text', { y: r2(below + (pips ? pip : 0) + LABEL_PX), 'text-anchor': 'middle', 'font-size': LABEL_PX * 0.9, class: 'rl-mk-posture' }, posture)
      : null,
    tag
      ? svg('text', { y: r2(below + (pips ? pip : 0) + LABEL_PX * (posture ? 2.1 : 1)), 'text-anchor': 'middle', 'font-size': LABEL_PX * 0.9, class: 'rl-tm-tag' }, tag)
      : null,
  ];
}

/** Whether the seat may carry mark `m` to a lit area: its own piece (one its forms name), not under way. */
const carriable = (m) => m.side === 'own' && Boolean(m.piece) && !m.piece.under_way;

const markLook = (m, chosen) => `rl-mk rl-mk-${m.kind} rl-side-${m.side} rl-c-${m.certainty} rl-tm-mark${chosen ? ' selected' : ''}`;

/** One mark at `xy`, `dx` pixels from it (a fanned stack's place for it); `tag` says how far along its step it is. */
function oneMark(m, xy, dx, from, opts, extra = {}, tag = null) {
  const held = heldOf(m, opts);
  const words = markLabel(m, markWhere(m), held, tag);
  const chosen = opts.selected === m.name;
  const keys = chosen && opts.nav ? arrows((dir) => opts.nav.step(null, dir)) : {};
  const common = opts.still ? { class: markLook(m, chosen) } : {
    class: markLook(m, chosen), 'aria-label': words, 'aria-pressed': String(chosen), ...activate(() => opts.onSelect?.(m.name), keys), ...extra,
    'data-grab': carriable(m) ? m.name : null,
  };
  return sliding(atPx({ ...common, 'data-key': markKey(m) }, xy[0], xy[1],
    svg('g', { transform: `translate(${dx} ${m.piece ? -MARK_LIFT : 0})` }, markBody(m, chosen, tag),
      // a held order on this piece: the padlock, and who can allow it as text (LKM)
      held.length ? svg('g', { class: 'rl-tm-held' }, lockMark(held[0].who, MIN_MARK_PX / 2 + 2, -MIN_MARK_PX / 2, LABEL_PX * 0.9)) : null),
    svg('title', {}, words)), xy, from, m.side === 'own');
}

/**
 * Two or more marks in one place, closed: one marker (the one that has just moved there, else
 * the first) over the edges of the rest, and the count. Activating it is `opts.onFan(key)`.
 */
function closedStack(here, key, xy, froms, opts) {
  const top = here.find((m) => froms.get(m)) ?? here[0];
  const where = markWhere(top);
  const held = here.filter((m) => heldOf(m, opts).length).map((m) => m.name);
  const words = `${here.length} pieces in ${where}: ${here.map((m) => m.name).join(', ')}${held.length ? `; held order on ${held.join(', ')}` : ''}`;
  const lift = here.some((m) => m.piece) ? -MARK_LIFT : 0;
  const r = MIN_MARK_PX / 2;
  const fan = () => opts.onFan?.(key);
  const attrs = opts.still ? { class: 'rl-tm-stack' } : {
    class: 'rl-tm-stack', 'aria-label': `${words}. Open the stack`, 'aria-expanded': 'false', ...activate(fan),
  };
  return svg('g', { ...attrs, 'data-stack': key, 'data-count': here.length },
    atPx({ class: `rl-tm-stack-base rl-side-${top.side}` }, xy[0], xy[1], svg('g', { transform: `translate(0 ${lift})` },
      svg('rect', { x: -MIN_TAP_PX / 2, y: -MIN_TAP_PX / 2, width: MIN_TAP_PX, height: MIN_TAP_PX, class: 'rl-tm-hit' }),
      [2, 1].map((n) => svg('rect', { x: -r * 1.4 + n * 3, y: -r - n * 3, width: r * 2.8, height: r * 2, class: 'rl-tm-stack-edge' })))),
    sliding(atPx({ class: markLook(top, false).replace(' rl-tm-mark', ' rl-tm-stack-top') }, xy[0], xy[1], svg('g', { transform: `translate(0 ${lift})` },
      forceGlyph({ ...top, kind: top.piece ? GLYPH[top.piece.domain] : top.kind }, MIN_MARK_PX))), xy, froms.get(top), top.side === 'own'),
    atPx({ class: 'rl-tm-count' }, xy[0], xy[1], svg('g', { transform: `translate(${r * 1.4 + 4} ${lift - r - 4})` },
      svg('circle', { r: 9 }), svg('text', { 'text-anchor': 'middle', dy: '0.35em', 'font-size': LABEL_PX }, String(here.length)))),
    // a held order on a piece in the stack: the padlock alone, opposite the count (LKM)
    held.length ? atPx({ class: 'rl-tm-held' }, xy[0], xy[1], lockMark(null, -(r * 1.4 + 4), lift - r - 4, LABEL_PX * 0.9)) : null,
    svg('title', {}, words));
}

/** The control that closes a fanned stack, beside its last marker. */
function fanCloser(here, key, xy, opts) {
  const dx = ((here.length - 1) / 2) * MARK_GAP + MARK_GAP * 0.75;
  const lift = here.some((m) => m.piece) ? -MARK_LIFT : 0;
  return atPx({
    class: 'rl-tm-count rl-tm-fanclose', 'data-stack': key, 'aria-expanded': 'true',
    'aria-label': `Close the stack of ${here.length}`, ...activate(() => opts.onFan?.(null)),
  }, xy[0], xy[1], svg('g', { transform: `translate(${dx} ${lift})` },
    svg('rect', { x: -MIN_TAP_PX / 2, y: -MIN_TAP_PX / 2, width: MIN_TAP_PX, height: MIN_TAP_PX, class: 'rl-tm-hit' }),
    svg('circle', { r: 9 }), svg('path', { d: 'M-4 -4L4 4M4 -4L-4 4', class: 'rl-tm-x' })));
}

function marksLayer(map, labelAt, at, opts) {
  const marks = sortMarks(map.marks ?? []);
  const lines = marks.filter((m) => m.places?.length > 1).map((m) => {
    const words = markLabel(m, whereLine(m));
    const common = opts.still ? { class: markLook(m, false) } : {
      class: markLook(m, opts.selected === m.name), 'aria-label': words, 'aria-pressed': String(opts.selected === m.name), ...activate(() => opts.onSelect?.(m.name)),
    };
    const points = m.places.map((p) => at([p.lon, p.lat]).join(',')).join(' ');
    return svg('g', common, svg('polyline', { points, class: 'rl-mk-hit' }), svg('polyline', { points, class: 'rl-mk-line' }), svg('title', {}, words));
  });
  const tags = new Map(marks.map((m) => [m, underWay(m, labelAt, opts.today)?.tag ?? null]));
  const crowd = new Map();
  for (const m of marks) {
    const xy = m.places?.length > 1 ? null : markAt(m, labelAt, at, opts.today);
    if (xy) crowd.set(xy.join(), { xy, here: [...(crowd.get(xy.join())?.here ?? []), m] });
  }
  const out = [lines];
  for (const { xy, here } of crowd.values()) {
    const froms = new Map(here.map((m) => [m, opts.still ? null : slideFrom(lastAt, markKey(m), markArea(m), xy)]));
    if (here.length === 1) {
      out.push(oneMark(here[0], xy, 0, froms.get(here[0]), opts, {}, tags.get(here[0])));
      continue;
    }
    const key = markArea(here[0]) ?? xy.join();
    const fanned = !opts.still && (opts.fanned === key || here.some((m) => m.name === opts.selected));
    if (!fanned) {
      out.push(closedStack(here, key, xy, froms, opts));
      continue;
    }
    const close = { 'data-stack': key, onkeyup: (e) => { if (e.key === 'Escape') opts.onFan?.(null); } };
    here.forEach((m, i) => out.push(oneMark(m, xy, (i - (here.length - 1) / 2) * MARK_GAP, froms.get(m), opts, close, tags.get(m))));
    out.push(fanCloser(here, key, xy, opts));
  }
  return out;
}

function capitalsLayer(map, at, opts) {
  return (map.capitals ?? []).map((c) => {
    const [x, y] = at([c.place.lon, c.place.lat]);
    const words = capitalLine(c);
    const open = opts.still ? null : opts.openCapital?.(c) ?? null;
    return atPx({
      ...(open ? activate(open) : { role: 'img' }),
      class: `rl-cap${stanceClass(c.stance)}${c.at_war ? ' at-war' : ''}`, 'data-leader': c.name, 'aria-label': words,
    }, x, y,
    svg('rect', { x: -MIN_TAP_PX / 2, y: -MIN_TAP_PX / 2, width: MIN_TAP_PX, height: MIN_TAP_PX, class: 'rl-tm-hit' }),
    capitalGlyph(MIN_MARK_PX * 0.75),
    c.at_war ? warGlyph(MIN_MARK_PX * 0.7, -MIN_MARK_PX * 0.6, MIN_MARK_PX * 0.75) : null,
    svg('text', { x: MIN_MARK_PX * 0.8, y: 4, 'font-size': LABEL_PX, class: 'rl-mk-name' }, c.name),
    svg('text', { x: MIN_MARK_PX * 0.8, y: 4 + LABEL_PX * 1.2, 'font-size': LABEL_PX * 0.9, class: 'rl-cap-stance' }, stanceWords(c.stance)),
    svg('title', {}, words));
  });
}

/** Where an order's goal is drawn: the area it names, by name, else its place. */
function goalAt(to, areaAt, at) {
  return areaAt.get(to.name) ?? (Number.isFinite(to.lon) && Number.isFinite(to.lat) ? at([to.lon, to.lat]) : null);
}

/**
 * The seat's own orders: an arrow to each goal, which draws itself once when the order is new
 * (`moving`: the clock, null when nothing moves); for a piece whose order is still with a holder,
 * a ghost of the piece at the goal, dashed, with whom it is with and until when.
 */
function ordersLayer(map, labelAt, areaAt, at, today, moving, sent) {
  const marks = map.marks ?? [];
  return (map.orders ?? []).map((o) => {
    const goal = goalAt(o.to, areaAt, at);
    if (!goal) return null;
    const m = marks.find((k) => k.name === o.mark);
    const f = m ? markAt(m, labelAt, at, today) : null;
    const arrow = f ? svg('line', { x1: f[0], y1: f[1], x2: goal[0], y2: goal[1], class: 'rl-mk-arrow' }) : null;
    if (arrow && sent.has(o.order)) drawOn(arrow, moving);
    const wait = m?.piece?.waiting?.order === o.order ? m.piece.waiting : null;
    const words = wait ? `${o.force} to ${o.to.name}: ${waitWords(wait)}` : `${o.force} to ${o.to.name}`;
    return svg('g', { class: `rl-mk-order rl-o-${o.status}`, role: 'img', 'aria-label': words, 'data-order': o.order },
      arrow,
      wait
        ? atPx({ class: `rl-tm-ghost rl-side-${m.side}` }, goal[0], goal[1], svg('g', { transform: `translate(0 ${-MARK_LIFT})` },
          forceGlyph({ ...m, kind: GLYPH[m.piece.domain] ?? m.kind, certainty: 'reported' }, MIN_MARK_PX),
          svg('text', { y: r2(-MIN_MARK_PX / 2 - 6), 'text-anchor': 'middle', 'font-size': LABEL_PX * 0.9, class: 'rl-tm-ghost-note' }, waitWords(wait))))
        : atPx({ class: 'rl-tm-goal' }, goal[0], goal[1], svg('circle', { r: MIN_MARK_PX * 0.6, class: 'rl-mk-goal' })));
  });
}

/**
 * Each own piece under way: its path still to go, dashed, from where it stands through each
 * area's label point, and the day it arrives; the part of its step already travelled, fainter.
 * A course new since the last drawing draws itself once (`moving`: the clock, null when nothing moves).
 */
function coursesLayer(map, labelAt, at, today, moving, sent) {
  return (map.marks ?? []).filter((m) => m.piece?.under_way?.path?.length).map((m) => {
    const from = markAt(m, labelAt, at, today);
    const way = underWay(m, labelAt, today);
    const steps = m.piece.under_way.path.map((a) => labelAt.get(a.key)).filter(Boolean);
    if (!from || !steps.length) return null;
    const end = steps.at(-1);
    const due = m.piece.under_way.arrives ?? m.piece.under_way.step_due;
    const path = svg('polyline', { points: [from, ...steps].map((xy) => xy.join(',')).join(' '), class: 'rl-mk-arrow rl-tm-path' });
    if (sent.has(markKey(m))) drawOn(path, moving);
    return svg('g', { class: `rl-tm-course rl-side-${m.side}`, role: 'img', 'aria-label': `${m.name}: ${courseLine(m.piece.under_way)}`, 'data-key': markKey(m) },
      way ? svg('polyline', { points: [way.from, way.at].map((xy) => xy.join(',')).join(' '), class: 'rl-tm-gone' }) : null,
      path,
      atPx({ class: 'rl-tm-goal' }, end[0], end[1], svg('circle', { r: MIN_MARK_PX * 0.6, class: 'rl-mk-goal' }),
        due ? svg('text', { y: r2(-MIN_MARK_PX * 0.6 - 4), 'text-anchor': 'middle', 'font-size': LABEL_PX, class: 'rl-target-note rl-tm-due' }, shortDate(due)) : null));
  });
}

/** The dated mark of an area that changed hands, and the line of a capital marked to fall, each under the area's label. */
function holdMarks(areas, labelAt) {
  return areas.filter((a) => a.held_since || a.falling).map((a) => {
    const [x, y] = labelAt.get(a.key);
    const taken = a.held_since ? changedLine(a) : '';
    const falls = a.falling ? fallingLine(a) : '';
    return [
      taken ? atPx({ class: 'rl-tm-held', 'data-area': a.key, role: 'img', 'aria-label': `${a.name}: ${taken}` }, x, y,
        svg('path', { d: 'M-4 0L0 -4L4 0L0 4Z', class: 'rl-held-glyph', transform: `translate(-30 ${LABEL_PX + 8})` }),
        svg('text', { x: -22, y: LABEL_PX + 12, 'font-size': LABEL_PX * 0.9, class: 'rl-hold-note' }, `Taken ${shortDate(a.held_since)}`)) : null,
      falls ? atPx({ class: 'rl-tm-fall', 'data-area': a.key, role: 'img', 'aria-label': `${a.name}: ${falls}` }, x, y,
        warGlyph(-30, LABEL_PX * 2 + 10, MIN_MARK_PX * 0.7),
        svg('text', { x: -18, y: LABEL_PX * 2 + 14, 'font-size': LABEL_PX * 0.9, class: 'rl-hold-note rl-fall-note' }, `Falls after ${shortDate(a.falling)}`)) : null,
    ];
  });
}

function targetsLayer(targets, at, onTarget, nav) {
  return targets.map((t, i) => {
    const [x, y] = at([t.place.lon, t.place.lat]);
    const pick = () => onTarget?.(t.value);
    const said = [t.days, t.liftWords ?? t.lift, t.lock ? lockWords({ who: t.lock }) : null].filter(Boolean);
    const words = t.words ?? `Send to ${t.place.name}${said.length ? `: ${said.join('. ')}` : ''}`;
    const keys = nav ? arrows((dir) => nav.step(i, dir)) : {};
    // Escape on keyup, as the fan's: the keyup of the same press then lands here, not on the piece
    const back = nav ? { onkeyup: (e) => { if (e.key === 'Escape') { e.preventDefault(); nav.back(); } } } : {};
    return atPx({
      class: `rl-map-target${t.refused ? ' refused' : ''}${t.chosen ? ' chosen' : ''}${t.lock ? ' locked' : ''}`, 'data-place': t.place.name, 'data-area': t.area ?? null,
      'aria-label': words, 'aria-pressed': String(t.chosen), 'aria-disabled': t.refused ? 'true' : null, ...activate(pick, keys), ...back,
    }, x, y,
    svg('circle', { r: MIN_TAP_PX / 2, class: 'rl-target-ring' }),
    [t.days, t.lift].filter(Boolean).map((line, i) => svg('text', { x: MIN_TAP_PX / 2 + 2, y: 4 + i * LABEL_PX * 1.2, 'font-size': LABEL_PX, class: 'rl-target-note' }, line)),
    // a move the server's check locks: the padlock, and who can allow it as text (LKM)
    t.lock ? lockMark(t.lock, -LABEL_PX * 0.4, -(MIN_TAP_PX / 2 + LABEL_PX * 0.6), LABEL_PX) : null,
    svg('title', {}, words));
  });
}

/**
 * The path of a move about to be sent (`route`: { from, steps: [{ key, name, days }] }), from the
 * piece's area through each step's label point, each step with its days.
 */
function routeLayer(route, labelAt) {
  const from = labelAt.get(route?.from);
  const steps = (route?.steps ?? []).filter((s) => labelAt.has(s.key));
  if (!from || !steps.length) return null;
  const said = steps.map((s) => `${s.name}, ${daysWord(s.days)}`).join('; ');
  const points = [from, ...steps.map((s) => labelAt.get(s.key))];
  // each step's days at the middle of its leg, clear of the lit ring and its note at the goal
  return svg('g', { class: 'rl-pup-path', role: 'img', 'aria-label': `Path: ${said}` },
    svg('polyline', { points: points.map((xy) => xy.join(',')).join(' '), class: 'rl-mk-arrow rl-pup-line' }),
    steps.map((s, i) => {
      const [x0, y0] = points[i];
      const [x1, y1] = points[i + 1];
      return [
        atPx({ class: 'rl-pup-stop' }, x1, y1, svg('circle', { r: 5, class: 'rl-pup-dot' })),
        atPx({ class: 'rl-pup-stop' }, (x0 + x1) / 2, (y0 + y1) / 2,
          svg('text', { y: -8, 'text-anchor': 'middle', 'font-size': LABEL_PX, class: 'rl-pup-step' }, daysWord(s.days))),
      ];
    }));
}

const daysWord = (n) => (n === 1 ? '1 day' : `${n} days`);

/**
 * The coastline's land inside the map's box, as one even-odd path drawn under the areas, for a
 * longitude-latitude map that has a backdrop; null for any other map, or before the coastline is here.
 * A ring is shifted a turn of longitude either way when that brings it into the box.
 */
function notInPlay(shapes, coast, box, line) {
  if (shapes.coords !== 'lonlat' || !(shapes.backdrop ?? []).length || !Array.isArray(coast?.rings)) return null;
  const d = [];
  for (const ring of coast.rings) {
    const lons = ring.map(([lon]) => lon);
    const lats = ring.map(([, lat]) => lat);
    if (Math.max(...lats) < box.south || Math.min(...lats) > box.north) continue;
    for (const turn of [-360, 0, 360]) {
      if (Math.max(...lons) + turn < box.west || Math.min(...lons) + turn > box.east) continue;
      d.push(`M${line(ring.map(([lon, lat]) => [lon + turn, lat])).map((xy) => xy.join(' ')).join('L')}Z`);
    }
  }
  return d.length ? svg('path', { d: d.join(''), class: 'rl-tm-notland', 'aria-hidden': 'true' }) : null;
}

/**
 * The drawing of a territory map `map` (the seat's `map` block) from `shapes` (its map file).
 * `opts`: { frame (a region's key, '' or null for the whole map), zoom, centre, px, layer,
 * selected, onSelect, fanned (the stack shown fanned out, by its area), onFan, targets, onTarget, openCapital,
 * coast (the coastline file's rings: land not in play), onView, still, label, route (a move's path: `routeLayer`), today, report (the picked report's key), onReport,
 * threats (the threats switch), token ({ intel, at, label }: an intelligence token put down), battles (`battleMarksOf`),
 * battle (the open battle's area), onBattle(mark) }. Arrow keys on the picked piece or a
 * lit area move focus along the lit areas; Escape on a lit area goes back to the piece.
 */
export function territoryDrawing(map, shapes, givenOpts = {}) {
  const nav = {
    step(i, dir) {
      const lit = root?.querySelectorAll('.rl-map-target') ?? [];
      if (!lit.length) return;
      const at = i === null ? (dir > 0 ? 0 : lit.length - 1) : (i + dir + lit.length) % lit.length;
      lit[at].focus();
    },
    back() { root?.querySelector('.rl-tm-mark[aria-pressed="true"]')?.focus(); },
  };
  const opts = { ...givenOpts, nav: givenOpts.still ? null : nav };
  const box = boxOf(map.box ?? shapes.box);
  const proj = territoryProjection(map.coords ?? shapes.coords, box);
  const frames = regionFrames(map, shapes);
  const rect = frameRect(frames.get(opts.frame ?? '') ?? frames.get(''), proj);
  const win = viewWindow(rect, opts.zoom ?? 1, opts.centre ?? null);
  const at = (xy) => proj.point(xy).map(r2);
  const line = (pts) => trace(proj, pts).map(([x, y]) => [r2(x), r2(y)]);
  const areas = (map.areas ?? []).filter((a) => shapes.areas?.[a.key]);
  const kinds = new Map(areas.map((a) => [a.key, a.kind]));
  const regions = new Map((map.regions ?? []).map((r) => [r.key, r.name]));
  const labelAt = new Map(areas.map((a) => [a.key, at(shapes.areas[a.key].label)]));
  let root = null;
  const show = (key) => root?.querySelector(`.rl-tm-label[data-area="${key}"]`)?.classList.toggle('shown');
  const economy = opts.layer === 'economy';
  const diplomatic = opts.layer === 'diplomatic';
  // the clock a course draws itself and a territory fills by (`opts.clock`, the page's own when not
  // given); none on a still drawing or under reduced motion
  const moving = opts.still || reducedMotion() ? null : { ...opts.clock };
  // what was sent since the last drawing, whichever layer that drawing showed: each course, each order
  const sent = new Set(moving ? [
    ...(map.marks ?? []).filter((m) => changed(shown.courses, markKey(m), (m.piece?.under_way?.path ?? []).map((a) => a.key).join(' '))).map(markKey),
    ...(map.orders ?? []).filter((o) => changed(shown.orders, o.order, o.to?.name ?? '')).map((o) => o.order),
  ] : []);
  // on the Diplomatic layer the lit areas are a picked envoy's moves (the theatre picks envoys only)
  const targets = economy || opts.still ? [] : opts.targets ?? [];
  const front = ([a, b]) => b !== null && isFront(byKey.get(a), byKey.get(b));
  const borderKind = ([a, b]) => {
    if (b === null || !kinds.has(b)) return 'edge';
    const both = [kinds.get(a), kinds.get(b)];
    return both.every((k) => k === 'land') ? 'land' : both.every((k) => k === 'sea') ? 'sea' : 'coast';
  };
  clips += 1;
  const clip = `rl-tm-clip-${clips}`;
  const tag = `rl-hp-${clips}`;
  const byKey = new Map((map.areas ?? []).map((a) => [a.key, a]));
  const held = areas.filter((a) => a.kind === 'land' && a.holder && HOLD_PATTERNS[holderRelation(a)]);
  // a territory that changed hands since the last drawing fills evenly with its new holder's tone
  const taken = new Set(moving ? areas.filter((a) => changed(shown.holders, a.key, a.holder ? `${a.holder.name} ${a.holder.relation}` : '')).map((a) => a.key) : []);
  // the frame, not the window: land past the window shows while the view moves, none past the frame
  const frameBox = { x: r2(rect.x), y: r2(rect.y), width: r2(rect.w), height: r2(rect.h) };
  root = svg('svg', {
    class: 'rl-map-svg rl-tm-svg', viewBox: viewBoxOf(win), preserveAspectRatio: 'xMidYMid meet',
    role: opts.still ? 'img' : 'group', 'aria-label': opts.label ?? 'Map of the board', 'data-frame': opts.frame ?? '',
    tabindex: opts.still ? null : 0,
  },
  svg('defs', {}, svg('clipPath', { id: clip }, svg('rect', frameBox)), holdPatterns(new Set(held.map(holderRelation)), tag)),
  svg('g', { class: 'rl-tm-frame', 'clip-path': `url(#${clip})` },
  proj.step
    ? svg('path', { d: `M${line([[box.west, box.north], [box.east, box.north], [box.east, box.south], [box.west, box.south], [box.west, box.north]]).map((xy) => xy.join(' ')).join('L')}Z`, class: 'rl-map-sea' })
    : svg('rect', { x: 0, y: 0, width: proj.width, height: proj.height, class: 'rl-map-sea' }),
  notInPlay(shapes, opts.coast, box, line),
  (shapes.backdrop ?? []).map((ring) => svg('path', { d: ringsPath(shapes.vertices, [ring], line), class: 'rl-tm-backdrop' })),
  areas.map((a) => svg('path', {
    d: ringsPath(shapes.vertices, shapes.areas[a.key].rings, line), class: `rl-area rl-area-${a.kind === 'sea' ? 'sea' : 'land'}`,
    'data-area': a.key, 'aria-label': `${a.name}: ${areaKindWord(a)}, ${regions.get(a.region) ?? a.region}${heldBy(a)}`,
    ...(opts.still ? {} : activate(() => { show(a.key); opts.onArea?.(a.key); })),
  })),
  held.map((a) => svg('path', {
    d: ringsPath(shapes.vertices, shapes.areas[a.key].rings, line), class: `rl-hold rl-hold-${holderRelation(a)}`,
    'data-area': a.key, fill: `url(#${tag}-${holderRelation(a)})`, 'aria-hidden': 'true',
  })).map((path) => (taken.has(path.getAttribute('data-area')) ? (fillIn(path, moving), path) : path)),
  borders(shapes).filter(({ between }) => kinds.has(between[0])).map(({ between, edges }) => svg('path', {
    d: edges.map(([p, q]) => `M${line([shapes.vertices[p], shapes.vertices[q]]).map((xy) => xy.join(' ')).join('L')}`).join(''),
    class: `rl-border rl-border-${borderKind(between)}${front(between) ? ' rl-border-front' : ''}`,
    'data-between': between.filter(Boolean).join(' '), 'data-front': front(between) ? 'true' : null,
  })),
  // what a gesture draws over the moving land, at its pixel size: labels, marks and lit areas
  svg('g', { class: 'rl-tm-over' },
  areas.map((a) => atPx({ class: 'rl-tm-label', 'data-area': a.key, 'data-text': a.name, 'aria-hidden': 'true' },
    ...labelAt.get(a.key), svg('text', { 'font-size': LABEL_PX, 'text-anchor': 'middle', dy: '0.35em' }, a.name))),
  holdMarks(areas, labelAt),
  economy ? null : coursesLayer(diplomatic ? { ...map, marks: envoyMarks(map) } : map, labelAt, at, opts.today, moving, sent),
  diplomatic || economy ? null : ordersLayer(map, labelAt, new Map(areas.map((a) => [a.name, labelAt.get(a.key)])), at, opts.today, moving, sent),
  diplomatic || economy ? null : routeLayer(opts.route, labelAt),
  diplomatic || economy ? null : ringsAndThreats({
    map, shapes, at, opts, areaPath: (key) => ringsPath(shapes.vertices, shapes.areas[key].rings, line),
  }),
  economy ? economyPips(areas, labelAt, (attrs, x, y) => atPx(attrs, x, y))
    : diplomatic ? [capitalsLayer(map, at, opts), marksLayer({ ...map, marks: envoyMarks(map) }, labelAt, at, opts)]
      : marksLayer(map, labelAt, at, opts),
  diplomatic || economy ? null : reportMarks({ map, labelAt, atPx, activate, opts }),
  diplomatic || economy || !opts.token ? null : tokenMark(opts.token, labelAt.get(opts.token.at), atPx),
  diplomatic || economy ? null : battleLayer({ battles: opts.battles, labelAt, atPx, activate, opts }),
  // drawn last, over every mark: a lit area under a stack stays clickable
  targetsLayer(targets, at, opts.onTarget, opts.nav))));
  if (moving) shown.primed = true;
  const px = opts.px ?? guessPx();
  fit(root, px);
  const onTap = (xy) => {
    const key = areaAt(shapes, proj, xy, areas.map((a) => a.key));
    if (key) { show(key); opts.onArea?.(key); }
  };
  // a piece is dropped on the lit area under the finger: the area the server lit, not its ring alone
  const litAt = (xy) => {
    const key = areaAt(shapes, proj, xy, targets.filter((t) => t.area && shapes.areas?.[t.area]).map((t) => t.area));
    return key ? targets.find((t) => t.area === key) : null;
  };
  const carry = carrying(root, root.querySelector('g.rl-tm-over'), litAt, opts);
  if (!opts.still) gestures(root, rect, { ...opts, ...carry, onTap, onLive: liveLayer(root, px), reduced: reducedMotion }, px);
  if (typeof globalThis.ResizeObserver === 'function') {
    new globalThis.ResizeObserver(([e]) => { if (e?.contentRect?.width) fit(root, e.contentRect); }).observe(root);
  }
  return root;
}

const toggle = (value, word, current, on, extra = {}) => h('button', {
  type: 'button', class: 'rl-filter', 'aria-pressed': String(current === value), onclick: () => on?.(value), ...extra,
}, word);

/** A set of toggles folded into one control (a phone's): `items` as [value, word], `current` chosen. */
const fold = (label, items, current, on, more = '') => h('select', { class: `rl-tm-fold${more}`, 'aria-label': label, onchange: (e) => on?.(e.target.value) },
  items.map(([value, word]) => h('option', { value, selected: value === current }, word)));

/** The regions the picker offers: the frame's key, the regions down to it, and the regions under it. */
function regionsOf(map, frames, frame) {
  const trail = regionTrail(map.regions, frame);
  const here = trail.at(-1)?.key ?? '';
  return { here, trail, under: regionChildren(map.regions, here).filter((r) => frames.has(r.key)) };
}

/** The region picker: the whole map, the regions down to the frame, and the regions under it. */
function regionPicker(map, frames, frame, onFrame, wide = '') {
  const { here, trail, under } = regionsOf(map, frames, frame);
  return h('div', { class: `rl-filters rl-tm-regions${wide}`, role: 'group', 'aria-label': 'Region' },
    toggle('', 'Whole map', here, onFrame),
    trail.map((r) => toggle(r.key, r.name, here, onFrame)),
    under.length ? h('span', { class: 'rl-tm-under', 'aria-hidden': 'true' }, '›') : null,
    under.map((r) => toggle(r.key, r.name, here, onFrame)));
}

/** The region picker as one control. */
function regionFold(map, frames, frame, onFrame) {
  const { here, trail, under } = regionsOf(map, frames, frame);
  return fold('Region', [['', 'Whole map'], ...[...trail, ...under].map((r) => [r.key, r.name])], here, onFrame, ' rl-tm-fold-region');
}

/** Whether the map is in the room's full screen: the room marks its root (`opts.onFull`). */
const isFull = (el) => Boolean(el?.closest?.('.rl-full'));

/** What takes the keyboard in the map the room draws next: 'full' (the control) or 'map' (the drawing). */
let refocus = null;

/** `fn()`, after which the next drawing of the map puts the keyboard on `what`. */
function keepFocus(what, fn) {
  refocus = what;
  fn();
  queueMicrotask(() => { refocus = null; });
}

/** Into the room's full screen from `el`'s map, or out of it; the browser's own is asked for as well. */
function askFull(el, opts, what) {
  const on = !isFull(el);
  browserFull(on);
  keepFocus(what, () => opts.onFull?.(on));
}

/** The Full screen control; in full screen it reads Leave full screen. */
function fullControl(opts) {
  const btn = h('button', { type: 'button', class: 'rl-filter rl-tm-full', onclick: () => askFull(btn, opts, 'full') },
    svg('svg', { class: 'rl-tm-full-glyph', viewBox: '0 0 16 16', width: 16, height: 16, 'aria-hidden': 'true', focusable: 'false' },
      svg('path', { d: 'M1 5V1h4M11 1h4v4M15 11v4h-4M5 15H1v-4' })),
    h('span', { class: 'rl-tm-full-in' }, 'Full screen'),
    h('span', { class: 'rl-tm-full-out' }, 'Leave full screen'));
  return btn;
}

/**
 * The keys the map takes in the map-first room: F on the drawing goes into full screen or out of
 * it; Escape with an area's or a report's sheet open closes that sheet, and full screen stays.
 */
function overlayKeys(section, opts, sheet) {
  return (e) => {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === 'Escape' && sheet) {
      e.preventDefault();
      keepFocus('map', sheet === 'area' ? () => opts.onArea?.(null) : () => opts.onReport?.(null));
    } else if ((e.key === 'f' || e.key === 'F') && e.target?.closest?.('figure.rl-map-figure')) {
      e.preventDefault();
      askFull(section, opts, 'map');
    }
  };
}

/**
 * Once the map is in the page: the keyboard goes where the last step into or out of full screen
 * left it, and a browser full screen the map asked for is given back when the room has drawn
 * the map out of full screen itself (its Escape).
 */
function afterDrawn(section) {
  const had = askedForFull();
  const what = refocus;
  queueMicrotask(() => {
    if (section.isConnected === false) return;
    if (had && !isFull(section)) browserFull(false);
    const el = what === 'full' ? section.querySelector('button.rl-tm-full') : what === 'map' ? section.querySelector('svg.rl-tm-svg') : null;
    el?.focus();
  });
}

/** An area's holder, and what is said of it, as one cell. */
function holderCell(a, areas) {
  const said = [holderWords(a), changedLine(a), fallingLine(a), frontLine(a, areas)].filter(Boolean);
  return a.kind === 'sea' ? '' : said.map((t, i) => (i ? `. ${t}` : t)).join('');
}

/** The sheet of one area: its holder, since when and its printed yields. `null` for a key the map does not have. */
function areaSheet(map, key, onArea, standings) {
  const a = (map.areas ?? []).find((x) => x.key === key);
  if (!a) return null;
  const land = a.kind === 'land';
  const since = a.held_since
    ? `${shortDate(a.held_since)}${a.taken_from ? `, taken from ${a.taken_from.name}` : ''}`
    : 'The same holder since the game began';
  const rows = land ? [['Holder', holderWords(a)], ['Held since', a.holder ? since : 'Not held'], ['Printed yields', yieldsLine(a.yields)]] : [];
  const band = land && a.holder ? bandOf(standings, a.holder.key) : undefined;
  if (band !== undefined) rows.push([`${a.holder.name} at home`, band ? band.charAt(0).toUpperCase() + band.slice(1) : 'No reading']);
  const notes = [fallingLine(a), land ? frontLine(a, map.areas) : ''].filter(Boolean);
  return h('section', { class: 'rl-area-sheet', 'aria-labelledby': 'rl-area-sheet-h', 'data-area': a.key },
    h('h3', { id: 'rl-area-sheet-h' }, a.name),
    h('p', { class: 'muted' }, `${areaKindWord(a)}`),
    rows.length ? h('dl', {}, rows.map(([k, v]) => [h('dt', {}, k), h('dd', {}, v)])) : null,
    notes.map((t) => h('p', { class: 'rl-hold-line' }, t)),
    h('button', { type: 'button', class: 'rl-find', onclick: () => onArea?.(null) }, 'Close'));
}

function areaTable(map) {
  const names = new Map((map.areas ?? []).map((a) => [a.key, a.name]));
  const regions = new Map((map.regions ?? []).map((r) => [r.key, r.name]));
  return h('table', { class: 'rl-map-list rl-area-list' },
    h('caption', {}, 'Every area of the board'),
    h('thead', {}, h('tr', {}, ['Area', 'Kind', 'Region', 'Borders', 'Holder'].map((c) => h('th', { scope: 'col' }, c)))),
    h('tbody', {}, (map.areas ?? []).map((a) => h('tr', { 'data-area': a.key },
      h('th', { scope: 'row' }, a.name),
      h('td', {}, areaKindWord(a)),
      h('td', {}, regions.get(a.region) ?? a.region),
      h('td', {}, a.neighbours.map((n) => names.get(n) ?? n).join(', ')),
      h('td', {}, holderCell(a, map.areas))))));
}

function markTable(map, onFind) {
  return h('table', { class: 'rl-map-list' },
    h('caption', {}, 'Every mark on your map'),
    h('thead', {}, h('tr', {}, ['Name', 'What', 'Side', 'Where', 'Source', ''].map((c) => h('th', { scope: 'col' }, c)))),
    h('tbody', {}, sortMarks(map.marks).map((m) => h('tr', { class: `rl-c-${m.certainty}` },
      h('th', { scope: 'row' }, m.name),
      h('td', {}, markWhat(m)),
      h('td', {}, sideLine(m)),
      h('td', {}, markWhere(m)),
      h('td', {}, m.document ? sightedLine(m) : ''),
      h('td', {}, h('button', { type: 'button', class: 'rl-find', onclick: () => onFind(m.name) }, 'Find on map'))))));
}

/**
 * The territory board: switches, then the drawing (`shapes` null: `opts.waiting` in its place)
 * or the list. `opts`: { mode, layer, frame, zoom, ...territoryDrawing's, onMode, onLayer, onFrame,
 * overlay (the map-first room: the switches over the map's corners), onFull(on) (the room's full screen) }.
 */
export function territoryView(map, shapes, opts = {}) {
  const mode = opts.mode === 'list' ? 'list' : 'map';
  const offered = offeredLayers(map);
  // the economy layer comes last, and never becomes the board's first view
  const first = offered[0] ?? 'military';
  if (hasYields(map)) offered.push(...(offered.length ? [] : ['military']), 'economy');
  const layer = offered.includes(opts.layer) ? opts.layer : first;
  const frames = shapes ? regionFrames(map, shapes) : null;
  const frame = frames?.has(opts.frame ?? '') ? opts.frame ?? '' : '';
  const zoom = clampZoom(opts.zoom ?? 1);
  const words = { military: 'Military', diplomatic: 'Diplomatic', economy: 'Economy' };
  const over = Boolean(opts.overlay);
  const wide = over ? ' rl-tm-wide' : '';
  const layers = offered.length > 1
    ? [h('div', { class: `rl-filters${wide}`, role: 'group', 'aria-label': 'Layer' }, offered.map((l) => toggle(l, words[l], layer, opts.onLayer))),
      over ? fold('Layer', offered.map((l) => [l, words[l]]), layer, opts.onLayer) : null]
    : [];
  const threats = mode === 'map' && layer === 'military' ? threatsSwitch(map, opts.threats, opts.onThreats) : null;
  const showAs = h('div', { class: 'rl-filters', role: 'group', 'aria-label': 'Show as' },
    toggle('map', 'Map', mode, opts.onMode), toggle('list', 'List', mode, opts.onMode));
  const regions = mode === 'map' && frames
    ? [regionPicker(map, frames, frame, opts.onFrame, wide), over ? regionFold(map, frames, frame, opts.onFrame) : null]
    : [];
  const zooms = mode === 'map' && frames
    ? h('div', { class: 'rl-filters rl-tm-zoom', role: 'group', 'aria-label': 'Zoom' },
      ZOOMS.map((z) => toggle(z, `${z}×`, zoom, (v) => opts.onView?.({ zoom: v, centre: opts.centre ?? null }), { 'aria-label': `Zoom ${z} times` })))
    : null;
  const full = over ? fullControl(opts) : null;
  const find = (name) => opts.onSelect?.(name, 'map');
  const area = mode === 'map' && opts.area ? areaSheet(map, opts.area, opts.onArea, opts.standings) : null;
  const report = mode === 'map' && layer === 'military' && opts.report ? reportSheet(map, opts.report, opts) : null;
  const figure = mode === 'map' ? h('figure', { class: 'rl-map-figure' },
    shapes ? territoryDrawing(map, shapes, { ...opts, layer, frame, zoom }) : h('p', { class: 'muted rl-tm-wait' }, opts.waiting ?? 'Drawing the map…')) : null;
  const body = mode === 'list'
    ? [areaTable(map), (map.marks ?? []).length ? markTable(map, find) : null, reportTables(map, opts), battleTable(opts.battles, opts.onBattle)]
    : over
      ? [h('div', { class: 'rl-tm-stage' },
        h('div', { class: 'rl-tm-corner rl-tm-top' },
          h('div', { class: 'rl-tm-tools rl-tm-tools-start' }, layers, threats, regions),
          h('div', { class: 'rl-tm-tools rl-tm-tools-end' }, showAs, full)),
        zooms ? h('div', { class: 'rl-tm-corner rl-tm-zoomcorner' }, zooms) : null,
        figure, area, report)]
      : [figure, area, report];
  const bar = mode === 'map' && over ? null : h('div', { class: 'rl-bar' }, layers, threats, showAs, regions, zooms, full);
  // the Diplomatic layer's key (realism-diplomacy.js): nations, capitals, public pacts and envoys
  const key = layer === 'diplomatic' ? (typeof opts.diplomacy === 'function' ? opts.diplomacy() : opts.diplomacy) : null;
  const section = h('section', { class: `rl-map rl-tmap${over ? ' rl-tm-overlay' : ''}`, 'aria-labelledby': 'rl-map-h' },
    h('h2', { id: 'rl-map-h', class: over ? 'sr-only' : null }, 'Map'),
    over ? null : h('p', { class: 'muted' }, 'The board as the game\'s map draws it; your pieces and reports from your own papers.'),
    bar,
    body,
    key ?? null);
  if (over) {
    section.addEventListener('keydown', overlayKeys(section, opts, area ? 'area' : report ? 'report' : null));
    afterDrawn(section);
  }
  return section;
}
