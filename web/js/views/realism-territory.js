// The territory map: in a game whose `map` block has `areas`, the board is drawn from the
// game's map file (the `map` action's shapes): land territories filled, sea zones outlined,
// every border stroked. The frame is a region's, worked out from its areas alone, and holds
// still whatever lights or lands; zoom is 1, 2 or 4 times within it. Marks and tap targets keep
// a minimum size in pixels whatever the zoom. Every area is focusable and has a row in the list.

import { h, svg } from '../dom.js';
import {
  LABEL_PX, MIN_MARK_PX, MIN_TAP_PX, SLIDE_MS, ZOOMS, borders, boxOf, certaintyWord, courseLine, frameRect, hiddenLabels,
  markArea, markKey, pinchZoom, pipsOf, postureWord, regionChildren, regionFrames, regionTrail, shortDate, sideLine,
  sightedLine, slideFrom, sortMarks, stanceWords, capitalLine, territoryProjection, unitsPerPx, viewWindow, waitWords,
  whereLine, changedLine, fallingLine, frontLine, holderRelation, holderWords, isFront, yieldsLine,
} from '../realism-rules.js';
import { capitalGlyph, forceGlyph, pipGlyph, stanceClass, warGlyph, whatWord } from './realism-map.js';

const r2 = (n) => Math.round(n * 100) / 100;

/** Each drawing's clip path needs an id of its own on the page. */
let clips = 0;

/** How far above its area's label point a piece is drawn (its pips and posture go under it), and the gap between pieces side by side, in pixels. */
const MARK_LIFT = 50;
const MARK_GAP = 44;

/** Where each mark last stood, by its key, so that a mark whose area changes slides there. */
const lastAt = new Map();

/** Forget where every mark stood (tests). */
export function forgetMarks() { lastAt.clear(); }

const reducedMotion = () => Boolean(globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches);

/** The glyph a piece's domain draws with. */
const GLYPH = Object.freeze({ land: 'army', sea: 'fleet', air: 'air' });

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
  if ((map.marks ?? []).length || (map.orders ?? []).length) out.push('military');
  if ((map.capitals ?? []).length) out.push('diplomatic');
  return out;
}

/** The pixel box the map is likely drawn into, until the drawing is measured. */
function guessPx() {
  const w = Number(globalThis.innerWidth) || 1440;
  const hgt = Number(globalThis.innerHeight) || 900;
  if (w < 1024) return { width: Math.max(w - 24, 200), height: Math.max(hgt * 0.5, 200) };
  return { width: Math.max(w - 480, 320), height: Math.max(hgt - 160, 320) };
}

function ringsPath(vertices, rings, at) {
  return rings.map((ring) => `M${ring.map((i) => at(vertices[i]).join(' ')).join('L')}Z`).join('');
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
 * and labels keep their size whatever the window, and a label that would overlap one drawn
 * before it is hidden (shown again on a tap of its area).
 */
export function fit(root, px) {
  const [x, y, w, hgt] = root.getAttribute('viewBox').split(' ').map(Number);
  const k = unitsPerPx({ x, y, w, h: hgt }, px);
  root.setAttribute('data-k', String(k));
  for (const g of root.querySelectorAll('.rl-tm-px')) {
    g.setAttribute('transform', `translate(${g.getAttribute('data-x')} ${g.getAttribute('data-y')}) scale(${k})`);
  }
  const labels = [...root.querySelectorAll('.rl-tm-label')];
  const hide = hiddenLabels(labels.map((l) => ({
    key: l.getAttribute('data-area'), x: Number(l.getAttribute('data-x')), y: Number(l.getAttribute('data-y')), text: l.getAttribute('data-text'),
  })), k);
  for (const l of labels) l.classList.toggle('hidden', hide.has(l.getAttribute('data-area')));
  return k;
}

/**
 * Pinch and drag on drawing `root`: a pinch picks the zoom step nearest its spread, around its
 * middle; a drag at a zoom past 1 moves the window. Each is told once, when the gesture ends,
 * as `onView({ zoom, centre })`.
 */
function gestures(root, win, opts, px) {
  const down = new Map();
  let start = null;
  const box = () => root.getBoundingClientRect?.() ?? { left: 0, top: 0, width: px.width, height: px.height };
  const toUnits = (cx, cy) => {
    const b = box();
    const k = unitsPerPx(win, b);
    const ox = (b.width - win.w / k) / 2; const oy = (b.height - win.h / k) / 2;
    return [win.x + (cx - b.left - ox) * k, win.y + (cy - b.top - oy) * k];
  };
  const spread = () => {
    const [a, b] = [...down.values()];
    return { d: Math.hypot(a.x - b.x, a.y - b.y), mid: [(a.x + b.x) / 2, (a.y + b.y) / 2] };
  };
  const zoom = opts.zoom ?? 1;
  const centre = opts.centre ?? [win.x + win.w / 2, win.y + win.h / 2];
  root.addEventListener('pointerdown', (e) => {
    down.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (down.size === 2) start = { kind: 'pinch', ...spread() };
    else if (down.size === 1) start = { kind: 'drag', x: e.clientX, y: e.clientY };
  });
  root.addEventListener('pointermove', (e) => {
    if (down.has(e.pointerId)) down.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (start?.kind === 'pinch' && down.size === 2) start.now = spread();
  });
  const end = (e) => {
    const was = start;
    const at = down.get(e.pointerId) ?? { x: e.clientX, y: e.clientY };
    down.delete(e.pointerId);
    if (!was || down.size) return;
    start = null;
    if (was.kind === 'pinch' && was.now && was.d > 0) {
      opts.onView?.({ zoom: pinchZoom(zoom, was.now.d / was.d), centre: toUnits(...was.now.mid) });
    } else if (was.kind === 'drag' && zoom > 1 && Math.hypot(at.x - was.x, at.y - was.y) > 8) {
      const k = unitsPerPx(win, box());
      opts.onView?.({ zoom, centre: [centre[0] - (at.x - was.x) * k, centre[1] - (at.y - was.y) * k] });
    }
  };
  root.addEventListener('pointerup', end);
  root.addEventListener('pointercancel', end);
}

/** What a mark is: an own piece's kind as the world names it, else the mark's kind. */
const markWhat = (m) => m.piece?.kind ?? whatWord(m);

function markLabel(m, where) {
  const p = m.piece;
  const said = [
    `${m.name}: ${markWhat(m)}, ${sideLine(m)}, ${certaintyWord(m.certainty)}${where ? `, ${where}` : ''}`,
    p?.posture ? postureWord(p.posture) : null,
    p?.under_way ? courseLine(p.under_way) : null,
    p?.waiting ? `Order ${waitWords(p.waiting)}` : null,
  ];
  return said.filter(Boolean).join('; ');
}

/** Where a mark stands: an own piece at its area's label point, a reported one at its place. */
function markAt(m, labelAt, at) {
  if (m.piece?.area?.key && labelAt.has(m.piece.area.key)) return labelAt.get(m.piece.area.key);
  return m.places?.length === 1 ? at([m.places[0].lon, m.places[0].lat]) : null;
}

/**
 * `child`, drawn at `xy`, in a group that slides it there from `from` over SLIDE_MS; with no
 * `from`, or under reduced motion, it stands there at once.
 */
function sliding(child, xy, from) {
  const g = svg('g', { class: 'rl-tm-slide' }, child);
  if (!from || reducedMotion()) return g;
  g.setAttribute('data-slide-from', from.join(' '));
  g.animate?.([
    { transform: `translate(${r2(from[0] - xy[0])}px, ${r2(from[1] - xy[1])}px)` }, { transform: 'translate(0px, 0px)' },
  ], { duration: SLIDE_MS, easing: 'ease-in-out' });
  return g;
}

/** The marker of mark `m`, centred on (0, 0): an own piece with its pips under it, its posture as a word, and its strength in figures only when it is picked. */
function markBody(m, chosen) {
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
  ];
}

const markLook = (m, chosen) => `rl-mk rl-mk-${m.kind} rl-side-${m.side} rl-c-${m.certainty} rl-tm-mark${chosen ? ' selected' : ''}`;

/** One mark at `xy`, `dx` pixels from it (a fanned stack's place for it). */
function oneMark(m, xy, dx, from, opts, extra = {}) {
  const words = markLabel(m, m.piece?.area?.name ?? whereLine(m));
  const chosen = opts.selected === m.name;
  const keys = chosen && opts.nav ? arrows((dir) => opts.nav.step(null, dir)) : {};
  const common = opts.still ? { class: markLook(m, chosen) } : {
    class: markLook(m, chosen), 'aria-label': words, 'aria-pressed': String(chosen), ...activate(() => opts.onSelect?.(m.name), keys), ...extra,
  };
  return sliding(atPx({ ...common, 'data-key': markKey(m) }, xy[0], xy[1],
    svg('g', { transform: `translate(${dx} ${m.piece ? -MARK_LIFT : 0})` }, markBody(m, chosen)),
    svg('title', {}, words)), xy, from);
}

/**
 * Two or more marks in one place, closed: one marker (the one that has just moved there, else
 * the first) over the edges of the rest, and the count. Activating it is `opts.onFan(key)`.
 */
function closedStack(here, key, xy, froms, opts) {
  const top = here.find((m) => froms.get(m)) ?? here[0];
  const where = top.piece?.area?.name ?? whereLine(top);
  const words = `${here.length} pieces in ${where}: ${here.map((m) => m.name).join(', ')}`;
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
      forceGlyph({ ...top, kind: top.piece ? GLYPH[top.piece.domain] : top.kind }, MIN_MARK_PX))), xy, froms.get(top)),
    atPx({ class: 'rl-tm-count' }, xy[0], xy[1], svg('g', { transform: `translate(${r * 1.4 + 4} ${lift - r - 4})` },
      svg('circle', { r: 9 }), svg('text', { 'text-anchor': 'middle', dy: '0.35em', 'font-size': LABEL_PX }, String(here.length)))),
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
  const crowd = new Map();
  for (const m of marks) {
    const xy = m.places?.length > 1 ? null : markAt(m, labelAt, at);
    if (xy) crowd.set(xy.join(), { xy, here: [...(crowd.get(xy.join())?.here ?? []), m] });
  }
  const out = [lines];
  for (const { xy, here } of crowd.values()) {
    const froms = new Map(here.map((m) => [m, opts.still ? null : slideFrom(lastAt, markKey(m), markArea(m), xy)]));
    if (here.length === 1) {
      out.push(oneMark(here[0], xy, 0, froms.get(here[0]), opts));
      continue;
    }
    const key = markArea(here[0]) ?? xy.join();
    const fanned = !opts.still && (opts.fanned === key || here.some((m) => m.name === opts.selected));
    if (!fanned) {
      out.push(closedStack(here, key, xy, froms, opts));
      continue;
    }
    const close = { 'data-stack': key, onkeyup: (e) => { if (e.key === 'Escape') opts.onFan?.(null); } };
    here.forEach((m, i) => out.push(oneMark(m, xy, (i - (here.length - 1) / 2) * MARK_GAP, froms.get(m), opts, close)));
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
 * The seat's own orders: an arrow to each goal; for a piece whose order is still with a holder,
 * a ghost of the piece at the goal, dashed, with whom it is with and until when.
 */
function ordersLayer(map, labelAt, areaAt, at) {
  const marks = map.marks ?? [];
  return (map.orders ?? []).map((o) => {
    const goal = goalAt(o.to, areaAt, at);
    if (!goal) return null;
    const m = marks.find((k) => k.name === o.mark);
    const f = m ? markAt(m, labelAt, at) : null;
    const wait = m?.piece?.waiting?.order === o.order ? m.piece.waiting : null;
    const words = wait ? `${o.force} to ${o.to.name}: ${waitWords(wait)}` : `${o.force} to ${o.to.name}`;
    return svg('g', { class: `rl-mk-order rl-o-${o.status}`, role: 'img', 'aria-label': words, 'data-order': o.order },
      f ? svg('line', { x1: f[0], y1: f[1], x2: goal[0], y2: goal[1], class: 'rl-mk-arrow' }) : null,
      wait
        ? atPx({ class: `rl-tm-ghost rl-side-${m.side}` }, goal[0], goal[1], svg('g', { transform: `translate(0 ${-MARK_LIFT})` },
          forceGlyph({ ...m, kind: GLYPH[m.piece.domain] ?? m.kind, certainty: 'reported' }, MIN_MARK_PX),
          svg('text', { y: r2(-MIN_MARK_PX / 2 - 6), 'text-anchor': 'middle', 'font-size': LABEL_PX * 0.9, class: 'rl-tm-ghost-note' }, waitWords(wait))))
        : atPx({ class: 'rl-tm-goal' }, goal[0], goal[1], svg('circle', { r: MIN_MARK_PX * 0.6, class: 'rl-mk-goal' })));
  });
}

/** Each own piece under way: its path still to go, dashed, through each area's label point, and the day it arrives. */
function coursesLayer(map, labelAt, at) {
  return (map.marks ?? []).filter((m) => m.piece?.under_way?.path?.length).map((m) => {
    const from = markAt(m, labelAt, at);
    const steps = m.piece.under_way.path.map((a) => labelAt.get(a.key)).filter(Boolean);
    if (!from || !steps.length) return null;
    const end = steps.at(-1);
    const due = m.piece.under_way.arrives ?? m.piece.under_way.step_due;
    return svg('g', { class: `rl-tm-course rl-side-${m.side}`, role: 'img', 'aria-label': `${m.name}: ${courseLine(m.piece.under_way)}`, 'data-key': markKey(m) },
      svg('polyline', { points: [from, ...steps].map((xy) => xy.join(',')).join(' '), class: 'rl-mk-arrow rl-tm-path' }),
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
    const said = [t.days, t.liftWords ?? t.lift].filter(Boolean);
    const words = `Send to ${t.place.name}${said.length ? `: ${said.join('. ')}` : ''}`;
    const keys = nav ? arrows((dir) => nav.step(i, dir)) : {};
    // Escape on keyup, as the fan's: the keyup of the same press then lands here, not on the piece
    const back = nav ? { onkeyup: (e) => { if (e.key === 'Escape') { e.preventDefault(); nav.back(); } } } : {};
    return atPx({
      class: `rl-map-target${t.refused ? ' refused' : ''}${t.chosen ? ' chosen' : ''}`, 'data-place': t.place.name, 'data-area': t.area ?? null,
      'aria-label': words, 'aria-pressed': String(t.chosen), 'aria-disabled': t.refused ? 'true' : null, ...activate(pick, keys), ...back,
    }, x, y,
    svg('circle', { r: MIN_TAP_PX / 2, class: 'rl-target-ring' }),
    [t.days, t.lift].filter(Boolean).map((line, i) => svg('text', { x: MIN_TAP_PX / 2 + 2, y: 4 + i * LABEL_PX * 1.2, 'font-size': LABEL_PX, class: 'rl-target-note' }, line)),
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
 * The drawing of a territory map `map` (the seat's `map` block) from `shapes` (its map file).
 * `opts`: { frame (a region's key, '' or null for the whole map), zoom, centre, px, layer,
 * selected, onSelect, fanned (the stack shown fanned out, by its area), onFan, targets, onTarget, openCapital,
 * onView, still, label, route (a move's path: `routeLayer`) }. Arrow keys on the picked piece or a
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
  const win = viewWindow(frameRect(frames.get(opts.frame ?? '') ?? frames.get(''), proj), opts.zoom ?? 1, opts.centre ?? null);
  const at = ([x, y]) => [r2(proj.x(x)), r2(proj.y(y))];
  const areas = (map.areas ?? []).filter((a) => shapes.areas?.[a.key]);
  const kinds = new Map(areas.map((a) => [a.key, a.kind]));
  const regions = new Map((map.regions ?? []).map((r) => [r.key, r.name]));
  const labelAt = new Map(areas.map((a) => [a.key, at(shapes.areas[a.key].label)]));
  let root = null;
  const show = (key) => root?.querySelector(`.rl-tm-label[data-area="${key}"]`)?.classList.toggle('shown');
  const diplomatic = opts.layer === 'diplomatic';
  const targets = diplomatic || opts.still ? [] : opts.targets ?? [];
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
  const frameBox = { x: r2(win.x), y: r2(win.y), width: r2(win.w), height: r2(win.h) };
  root = svg('svg', {
    class: 'rl-map-svg rl-tm-svg', viewBox: `${r2(win.x)} ${r2(win.y)} ${r2(win.w)} ${r2(win.h)}`, preserveAspectRatio: 'xMidYMid meet',
    role: opts.still ? 'img' : 'group', 'aria-label': opts.label ?? 'Map of the board', 'data-frame': opts.frame ?? '',
  },
  svg('defs', {}, svg('clipPath', { id: clip }, svg('rect', frameBox)), holdPatterns(new Set(held.map(holderRelation)), tag)),
  svg('g', { class: 'rl-tm-frame', 'clip-path': `url(#${clip})` },
  svg('rect', { x: 0, y: 0, width: proj.width, height: proj.height, class: 'rl-map-sea' }),
  (shapes.backdrop ?? []).map((ring) => svg('path', { d: ringsPath(shapes.vertices, [ring], at), class: 'rl-tm-backdrop' })),
  areas.map((a) => svg('path', {
    d: ringsPath(shapes.vertices, shapes.areas[a.key].rings, at), class: `rl-area rl-area-${a.kind === 'sea' ? 'sea' : 'land'}`,
    'data-area': a.key, 'aria-label': `${a.name}: ${areaKindWord(a)}, ${regions.get(a.region) ?? a.region}${heldBy(a)}`,
    ...(opts.still ? {} : activate(() => { show(a.key); opts.onArea?.(a.key); })),
  })),
  held.map((a) => svg('path', {
    d: ringsPath(shapes.vertices, shapes.areas[a.key].rings, at), class: `rl-hold rl-hold-${holderRelation(a)}`,
    'data-area': a.key, fill: `url(#${tag}-${holderRelation(a)})`, 'aria-hidden': 'true',
  })),
  borders(shapes).filter(({ between }) => kinds.has(between[0])).map(({ between, edges }) => svg('path', {
    d: edges.map(([p, q]) => `M${at(shapes.vertices[p]).join(' ')}L${at(shapes.vertices[q]).join(' ')}`).join(''),
    class: `rl-border rl-border-${borderKind(between)}${front(between) ? ' rl-border-front' : ''}`,
    'data-between': between.filter(Boolean).join(' '), 'data-front': front(between) ? 'true' : null,
  })),
  areas.map((a) => atPx({ class: 'rl-tm-label', 'data-area': a.key, 'data-text': a.name, 'aria-hidden': 'true' },
    ...labelAt.get(a.key), svg('text', { 'font-size': LABEL_PX, 'text-anchor': 'middle', dy: '0.35em' }, a.name))),
  holdMarks(areas, labelAt),
  diplomatic ? null : coursesLayer(map, labelAt, at),
  diplomatic ? null : ordersLayer(map, labelAt, new Map(areas.map((a) => [a.name, labelAt.get(a.key)])), at),
  diplomatic ? null : routeLayer(opts.route, labelAt),
  diplomatic ? capitalsLayer(map, at, opts) : marksLayer(map, labelAt, at, opts),
  // drawn last, over every mark: a lit area under a stack stays clickable
  targetsLayer(targets, at, opts.onTarget, opts.nav)));
  const px = opts.px ?? guessPx();
  fit(root, px);
  if (!opts.still) gestures(root, win, opts, px);
  if (typeof globalThis.ResizeObserver === 'function') {
    new globalThis.ResizeObserver(([e]) => { if (e?.contentRect?.width) fit(root, e.contentRect); }).observe(root);
  }
  return root;
}

const toggle = (value, word, current, on, extra = {}) => h('button', {
  type: 'button', class: 'rl-filter', 'aria-pressed': String(current === value), onclick: () => on?.(value), ...extra,
}, word);

/** The region picker: the whole map, the regions down to the frame, and the regions under it. */
function regionPicker(map, frames, frame, onFrame) {
  const trail = regionTrail(map.regions, frame);
  const here = trail.at(-1)?.key ?? '';
  const under = regionChildren(map.regions, here).filter((r) => frames.has(r.key));
  return h('div', { class: 'rl-filters rl-tm-regions', role: 'group', 'aria-label': 'Region' },
    toggle('', 'Whole map', here, onFrame),
    trail.map((r) => toggle(r.key, r.name, here, onFrame)),
    under.length ? h('span', { class: 'rl-tm-under', 'aria-hidden': 'true' }, '›') : null,
    under.map((r) => toggle(r.key, r.name, here, onFrame)));
}

/** An area's holder, and what is said of it, as one cell. */
function holderCell(a, areas) {
  const said = [holderWords(a), changedLine(a), fallingLine(a), frontLine(a, areas)].filter(Boolean);
  return a.kind === 'sea' ? '' : said.map((t, i) => (i ? `. ${t}` : t)).join('');
}

/** The sheet of one area: its holder, since when and its printed yields. `null` for a key the map does not have. */
function areaSheet(map, key, onArea) {
  const a = (map.areas ?? []).find((x) => x.key === key);
  if (!a) return null;
  const land = a.kind === 'land';
  const since = a.held_since
    ? `${shortDate(a.held_since)}${a.taken_from ? `, taken from ${a.taken_from.name}` : ''}`
    : 'The same holder since the game began';
  const rows = land ? [['Holder', holderWords(a)], ['Held since', a.holder ? since : 'Not held'], ['Printed yields', yieldsLine(a.yields)]] : [];
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
      h('td', {}, m.piece?.area?.name ?? whereLine(m)),
      h('td', {}, m.document ? sightedLine(m) : ''),
      h('td', {}, h('button', { type: 'button', class: 'rl-find', onclick: () => onFind(m.name) }, 'Find on map'))))));
}

/**
 * The territory board: switches, then the drawing (`shapes` null: `opts.waiting` in its place)
 * or the list. `opts`: { mode, layer, frame, zoom, ...territoryDrawing's, onMode, onLayer, onFrame }.
 */
export function territoryView(map, shapes, opts = {}) {
  const mode = opts.mode === 'list' ? 'list' : 'map';
  const offered = offeredLayers(map);
  const layer = offered.includes(opts.layer) ? opts.layer : offered[0] ?? 'military';
  const frames = shapes ? regionFrames(map, shapes) : null;
  const frame = frames?.has(opts.frame ?? '') ? opts.frame ?? '' : '';
  const zoom = ZOOMS.includes(opts.zoom) ? opts.zoom : 1;
  const words = { military: 'Military', diplomatic: 'Diplomatic' };
  const bar = h('div', { class: 'rl-bar' },
    offered.length > 1
      ? h('div', { class: 'rl-filters', role: 'group', 'aria-label': 'Layer' }, offered.map((l) => toggle(l, words[l], layer, opts.onLayer)))
      : null,
    h('div', { class: 'rl-filters', role: 'group', 'aria-label': 'Show as' },
      toggle('map', 'Map', mode, opts.onMode), toggle('list', 'List', mode, opts.onMode)),
    mode === 'map' && frames ? regionPicker(map, frames, frame, opts.onFrame) : null,
    mode === 'map' && frames
      ? h('div', { class: 'rl-filters rl-tm-zoom', role: 'group', 'aria-label': 'Zoom' },
        ZOOMS.map((z) => toggle(z, `${z}×`, zoom, (v) => opts.onView?.({ zoom: v, centre: opts.centre ?? null }), { 'aria-label': `Zoom ${z} times` })))
      : null);
  const find = (name) => opts.onSelect?.(name, 'map');
  const body = mode === 'list'
    ? [areaTable(map), (map.marks ?? []).length ? markTable(map, find) : null]
    : [h('figure', { class: 'rl-map-figure' },
      shapes ? territoryDrawing(map, shapes, { ...opts, layer, frame, zoom }) : h('p', { class: 'muted rl-tm-wait' }, opts.waiting ?? 'Drawing the map…')),
      opts.area ? areaSheet(map, opts.area, opts.onArea) : null];
  return h('section', { class: 'rl-map rl-tmap', 'aria-labelledby': 'rl-map-h' },
    h('h2', { id: 'rl-map-h' }, 'Map'),
    h('p', { class: 'muted' }, 'The board as the game\'s map draws it; your pieces and reports from your own papers.'),
    bar,
    body);
}
