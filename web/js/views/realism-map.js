// The realism map: forces, fronts and routes as the seat's own papers place them,
// drawn over Natural Earth coastlines, and the same marks as a list for keyboard
// and screen-reader use. Takes view.realism.map (realism_api.py SeatMap).

import { h, svg } from '../dom.js';
import {
  MIN_MARK_PX, capitalLine, certaintyWord, landPath, mapBox, mapOrderLine, markKindWord, projection, sideLine, sightedLine,
  sortMarks, stanceWords, theatreAreas, whereLine,
} from '../realism-rules.js';

const r2 = (n) => Math.round(n * 100) / 100;

/** A detachment's mark, as a share of a whole force's. */
const DETACHED_SIZE = 0.7;

/**
 * The picture of each kind of piece, by the key the core's fixed list gives it [proposed]: one
 * filled outline in a box from -12 to 12, every part wound the same way (a hole the other way),
 * told apart by its outline alone.
 */
export const PICTURES = Object.freeze({
  // a soldier with his rifle at his side
  infantry: 'M0 -12A2.6 2.6 0 1 1 0 -6.8A2.6 2.6 0 1 1 0 -12ZM-4.5 -6H4.5L5.5 2H3L2.5 12H0.5L0 5L-0.5 12H-2.5L-3 2H-5.5Z'
    + 'M7 -12H8.4V4H7Z',
  // a tank from the side: tracks, turret, gun
  armour: 'M-8.5 2H8.5A3.5 3.5 0 0 1 8.5 9H-8.5A3.5 3.5 0 0 1 -8.5 2ZM-9 -0.5H9L11 2H-11ZM-6 -4.5H4L6 -0.5H-7ZM4 -3.3H12V-1.9H4Z',
  // a fort: battlements over an arched gate
  garrison: 'M-10 12V-6H-7V-10H-3V-6H-1V-10H1V-6H3V-10H7V-6H10V12H3V6A3 3 0 0 0 -3 6V12Z',
  // a horse's head
  cavalry: 'M-2 -12L1 -8C7 -7 10 -1 10 6V12H-6L-2 4C-5 4 -8 6 -10 4L-11 1L-4 -6L-4 -10Z',
  // a field gun: barrel, wheel round its hub, trail
  artillery: 'M-4 -1L9 -9L10.5 -6.5L-2.5 1.5ZM-8 5A6 6 0 1 1 4 5A6 6 0 1 1 -8 5ZM-4 5A2 2 0 1 0 0 5A2 2 0 1 0 -4 5Z'
    + 'M2 6L11 10V12L1 9Z',
  // a battleship: hull, tower, a turret fore and aft
  battle_fleet: 'M-12 3H12L9 9H-9ZM-4 -3H3V3H-4ZM-1.5 -9H0V-3H-1.5ZM5 0H9V3H5ZM9 0.6H12V1.8H9ZM-9 0H-5V3H-9ZM-12 0.6H-9V1.8H-12Z',
  // a carrier: the flat deck over the hull, the island to one side
  carrier: 'M-12 -1H12V1.5H-12ZM-10 1.5H10L8 8H-8ZM4 -7H7V-1H4ZM5 -10H6V-7H5Z',
  // a submarine: the long hull, its tower and periscope
  submarines: 'M-12 4C-12 0 -8 0 -6 0H8C11 0 12 2 12 4C12 6 11 8 8 8H-6C-8 8 -12 8 -12 4ZM-3 -5H3L4 0H-4ZM0 -10H1.2V-5H0Z',
  // a cargo ship: crates amidships, the bridge and funnel aft
  transports: 'M-12 2H12L10 9H-11ZM-9 -3H-4V2H-9ZM-3 -6H2V2H-3ZM5 -5H10V2H5ZM7 -9H9V-5H7Z',
  // a river gunboat: low hull, the house, one tall stack, one gun
  gunboat: 'M-11 4H11L8 9H-9ZM-6 -1H2V4H-6ZM-4 -10H-2V-1H-4ZM2 1H10V2.6H2Z',
  // an ironclad: the sloped casemate on a low hull, its stack
  ironclad: 'M-12 5H12L10 9H-10ZM-8 5L-4 -3H4L8 5ZM-1 -9H1.5V-3H-1Z',
  // a single-engined fighter from above
  fighters: 'M0 -12C1.2 -12 1.6 -10 1.6 -7V-3L11 0V3L1.6 2V7L5 9.5V11.5L0 10.5L-5 11.5V9.5L-1.6 7V2L-11 3V0L-1.6 -3V-7'
    + 'C-1.6 -10 -1.2 -12 0 -12Z',
  // a four-engined bomber from above: straight wings, the engines ahead of them
  bombers: 'M-1.6 -12H1.6V-4H12V0H1.6V7H6V10H-6V7H-1.6V0H-12V-4H-1.6ZM-9 -7H-7V-4H-9ZM-5 -7H-3V-4H-5ZM3 -7H5V-4H3Z'
    + 'M7 -7H9V-4H7Z',
  // a sealed letter: the envelope with its flap
  envoy: 'M-11 -7H11V7H-11ZM-9 -5L0 2L9 -5Z',
});

/** The picture key a mark carries, for its own piece's kind or as a report gives it; null when none the client draws. */
export function pictureOf(mark) {
  const key = mark.picture ?? mark.piece?.figures?.picture ?? null;
  return key && Object.hasOwn(PICTURES, key) ? key : null;
}

/** A kind's picture drawn for a mark of `size` px, centred on (0, 0). */
export function pictureGlyph(key, size) {
  return svg('path', { d: PICTURES[key], transform: `scale(${r2((size * 0.72) / 24)})`, class: 'rl-mk-pic', 'data-picture': key });
}

/** The marker for a force: shape says side, fill and line say certainty, a picture (else a glyph) says kind. */
export function forceGlyph(mark, size) {
  const r = size / 2;
  const shape = mark.side === 'own'
    ? svg('rect', { x: -r * 1.4, y: -r, width: r * 2.8, height: r * 2, class: 'rl-mk-shape' })
    : svg('path', { d: `M0 ${-r * 1.4}L${r * 1.4} 0L0 ${r * 1.4}L${-r * 1.4} 0Z`, class: 'rl-mk-shape' });
  const tick = mark.certainty === 'stale'
    ? svg('path', { d: `M${r * 1.2} ${-r * 1.6}l${r * 0.6} ${-r * 0.6}`, class: 'rl-mk-tick' })
    : null;
  const picture = pictureOf(mark);
  if (picture) return [shape, pictureGlyph(picture, size), tick];
  const q = r * 0.6;
  const inner = {
    fleet: svg('path', { d: `M${-q} 0H${q}M${-q} ${q / 2}Q0 ${q * 1.2} ${q} ${q / 2}`, class: 'rl-mk-glyph' }),
    army: svg('path', { d: `M${-q} ${-q / 1.5}L${q} ${q / 1.5}M${-q} ${q / 1.5}L${q} ${-q / 1.5}`, class: 'rl-mk-glyph' }),
    air: svg('path', { d: `M${-q} ${q / 2}L0 ${-q / 2}L${q} ${q / 2}`, class: 'rl-mk-glyph' }),
    // an envoy: a sealed letter
    envoy: svg('path', { d: `M${-q} ${-q / 1.5}H${q}V${q / 1.5}H${-q}ZM${-q} ${-q / 1.5}L0 ${q / 4}L${q} ${-q / 1.5}`, class: 'rl-mk-glyph rl-mk-envoy' }),
  }[mark.kind];
  return [shape, inner, tick];
}

/** The glyph of today for a piece's domain, where its mark names only a piece. */
const DOMAIN_GLYPH = Object.freeze({ land: 'army', sea: 'fleet', air: 'air', envoy: 'envoy' });

/**
 * A piece's mark as a list or a sheet draws it beside its name: at the map's own size, one to
 * one, hidden from a reader (the words beside it say what it is). Null for a front or a route.
 */
export function markSwatch(mark) {
  if (mark.kind === 'front' || mark.kind === 'route') return null;
  const half = MIN_MARK_PX * 0.75;
  const kind = DOMAIN_GLYPH[mark.piece?.domain] ?? mark.kind;
  return svg('svg', {
    viewBox: `${-half} ${-half} ${half * 2} ${half * 2}`, width: half * 2, height: half * 2, 'aria-hidden': 'true', focusable: 'false',
    class: `rl-mk rl-pc-swatch rl-side-${mark.side} rl-c-${mark.certainty}`,
  }, forceGlyph({ ...mark, kind }, MIN_MARK_PX));
}

/**
 * A piece's strength as a row of pips centred under its marker at `y`: `pips.filled` solid,
 * the rest of `pips.slots` hollow (`pipsOf`). The number is not drawn here.
 */
export function pipGlyph(pips, size, y) {
  const side = Math.max(size / 5, 4);
  const gap = side * 0.4;
  const width = pips.slots * side + (pips.slots - 1) * gap;
  return svg('g', { class: 'rl-tm-pips', 'data-filled': pips.filled, 'data-slots': pips.slots },
    Array.from({ length: pips.slots }, (_, i) => svg('rect', {
      x: r2(-width / 2 + i * (side + gap)), y: r2(y), width: r2(side), height: r2(side),
      class: i < pips.filled ? 'rl-pip' : 'rl-pip rl-pip-empty',
    })));
}

/** A capital's marker: a five-pointed star, its colour the stance (a third cue: the words say it). */
export function capitalGlyph(size) {
  const r = size * 0.8;
  const pts = Array.from({ length: 10 }, (_, i) => {
    const a = (Math.PI / 5) * i - Math.PI / 2;
    const k = (i & 1) ? r * 0.45 : r;
    return `${(Math.cos(a) * k).toFixed(2)},${(Math.sin(a) * k).toFixed(2)}`;
  });
  return svg('polygon', { points: pts.join(' '), class: 'rl-cap-shape' });
}

/** The war mark beside a capital: two crossed strokes in a ring. */
export function warGlyph(x, y, size) {
  const q = size * 0.35;
  return svg('g', { class: 'rl-cap-war', transform: `translate(${x} ${y})` },
    svg('circle', { r: size * 0.55 }),
    svg('path', { d: `M${-q} ${-q}L${q} ${q}M${-q} ${q}L${q} ${-q}` }));
}

export const stanceClass = (stance) => (Number.isInteger(stance?.step) ? ` rl-stance-${stance.step}` : '');

/** The engine names a detachment "<fleet's name> detachment <n>"; a page sights it by that name. */
const DETACHMENT = / detachment \d+$/;

/** A mark that a page names as a fleet's detachment. */
const detached = (mark) => DETACHMENT.test(mark.name);

/** What a mark is, in words: "Fleet", or "Fleet detachment" for a detachment. */
export const whatWord = (mark) => (detached(mark) ? `${markKindWord(mark.kind)} detachment` : markKindWord(mark.kind));

function label(mark) {
  return `${mark.name}: ${whatWord(mark)}, ${sideLine(mark)}, ${certaintyWord(mark.certainty)}, ${whereLine(mark)}`;
}

/** A capital as a box-fitting mark: its place. */
const capitalMarks = (map) => (map.capitals ?? []).map((c) => ({ places: [c.place] }));

/** Each theatre as a labelled rounded box around its places in the drawing (`theatreAreas`). */
function theatreOutlines(places, at, size) {
  const pad = size * 1.4;
  return theatreAreas(places).map((area) => svg('g', { class: 'rl-theatre-area', 'data-theatre': area.name },
    area.parts.map((b) => {
      const [x0, y0] = at({ lon: b.west, lat: b.north });
      const [x1, y1] = at({ lon: b.east, lat: b.south });
      return svg('rect', { x: x0 - pad, y: y0 - pad, width: x1 - x0 + pad * 2, height: y1 - y0 + pad * 2, rx: pad * 0.6 });
    }),
    (() => {
      const [x, y] = at({ lon: area.parts[0].west, lat: area.parts[0].north });
      return svg('text', { x: x - pad + size * 0.3, y: y - pad - size * 0.3, 'font-size': size * 0.65 }, area.name);
    })()));
}

/** The diplomatic layer's marks: each capital with its leader, the stance word and step, and a war mark. */
function capitalPins(map, at, size, opts) {
  return (map.capitals ?? []).map((c) => {
    const [x, y] = at(c.place);
    const words = capitalLine(c);
    const open = opts.still ? null : opts.openCapital?.(c) ?? null;
    const common = open ? {
      tabindex: 0,
      role: 'button',
      onclick: open,
      onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } },
    } : { role: 'img' };
    return svg('g', {
      ...common, class: `rl-cap${stanceClass(c.stance)}${c.at_war ? ' at-war' : ''}`, 'data-leader': c.name,
      'aria-label': words, transform: `translate(${x} ${y})`,
    },
    capitalGlyph(size),
    c.at_war ? warGlyph(size * 0.95, -size * 0.85, size) : null,
    svg('text', { x: size * 1.1, y: size * 0.3, 'font-size': size * 0.75, class: 'rl-mk-name' }, c.name),
    svg('text', { x: size * 1.1, y: size * 1.25, 'font-size': size * 0.65, class: 'rl-cap-stance' }, stanceWords(c.stance)),
    c.at_war ? svg('text', { x: size * 1.1, y: size * 2.1, 'font-size': size * 0.65, class: 'rl-cap-stance' }, 'At war') : null,
    svg('title', {}, words));
  });
}

/**
 * The places an open movement form offers (`opts.targets`), each a ring with its days and, for
 * a lift, the tonnage line and a sea leg from `from`. A click or Enter on one is
 * `opts.onTarget(value)` (which refuses a refused place); a refused one is marked
 * `aria-disabled`. The chosen one is pressed.
 */
function targetRings(targets, at, size, onTarget) {
  return targets.map((t) => {
    const [x, y] = at(t.place);
    const pick = () => onTarget?.(t.value);
    const note = [t.days, t.lift].filter(Boolean);
    const said = [t.days, t.liftWords ?? t.lift].filter(Boolean);
    const words = `Send to ${t.place.name}${said.length ? `: ${said.join('. ')}` : ''}`;
    const [fx, fy] = t.lift && t.from ? at(t.from) : [x, y];
    return svg('g', {
      class: `rl-map-target${t.refused ? ' refused' : ''}${t.chosen ? ' chosen' : ''}`, 'data-place': t.place.name,
      tabindex: 0, role: 'button', 'aria-label': words,
      'aria-pressed': String(t.chosen), 'aria-disabled': t.refused ? 'true' : null,
      onclick: pick,
      onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } },
    },
    fx !== x || fy !== y ? svg('path', { d: `M${r2(fx)} ${r2(fy)}L${r2(x)} ${r2(y)}`, class: 'rl-map-sealeg' }) : null,
    svg('g', { transform: `translate(${x} ${y})` },
      svg('circle', { r: size * 0.75, class: 'rl-target-ring' }),
      note.map((line, i) => svg('text', { x: size / 3, y: size * (1.1 + i * 0.8), 'font-size': size * 0.6, class: 'rl-target-note' }, line))),
    svg('title', {}, words));
  });
}

/**
 * The drawing: sea, land, the places the marks name, then lines under forces. `opts.still`
 * draws a picture only: no mark takes focus or a click (the wake overlay holds the room).
 * `opts.compact`: drawn small, so marks and names are drawn larger for the width.
 * `opts.theatres`: each theatre drawn as a labelled box around its places. `opts.layer`
 * 'diplomatic': the capitals in place of forces and orders (`opts.openCapital(capital)` gives
 * what a pick on one opens, or null when nothing does). `opts.targets`: the places an open
 * movement form offers, lit and taken into the box (`targetRings`).
 */
export function mapDrawing(map, land, opts = {}) {
  const diplomatic = opts.layer === 'diplomatic';
  const targets = diplomatic || opts.still ? [] : opts.targets ?? [];
  const lit = targets.length ? { ...map, marks: [...map.marks, { places: targets.map((t) => t.place) }] } : map;
  const fit = mapBox(diplomatic ? { places: map.places, marks: capitalMarks(map), orders: [] } : lit, opts.scope);
  // names are drawn east of their marks: room for them at the larger compact size
  const box = opts.compact ? { ...fit, east: Math.min(fit.east + (fit.east - fit.west) * 0.3, 180) } : fit;
  const proj = projection(box);
  const size = proj.width / (opts.compact ? 26 : 55);
  const orders = diplomatic ? [] : map.orders ?? [];
  const named = diplomatic
    ? new Set((map.capitals ?? []).map((c) => c.place.name))
    : new Set([...map.marks.flatMap((m) => m.places.map((p) => p.name)), ...orders.map((o) => o.to.name), ...targets.map((t) => t.place.name)]);
  const inBox = (p) => p.lon >= box.west && p.lon <= box.east && p.lat >= box.south && p.lat <= box.north;
  const at = (p) => [proj.x(p.lon), proj.y(p.lat)];

  const places = map.places.filter(inBox).map((p) => {
    const [x, y] = at(p);
    return svg('g', { class: `rl-map-place${named.has(p.name) ? ' named' : ''}`, 'data-place': p.name },
      svg('circle', { cx: x, cy: y, r: size / 6 }),
      named.has(p.name) ? svg('text', { x: x + size / 3, y: y - size / 3, 'font-size': size * 0.7 }, p.name) : null);
  });

  const marks = diplomatic ? capitalPins(map, at, size, opts) : sortMarks(map.marks.filter((m) => m.places.length)).map((m) => {
    const select = () => opts.onSelect?.(m.name);
    const look = `rl-mk rl-mk-${m.kind}${detached(m) ? ' rl-mk-detached' : ''} rl-side-${m.side} rl-c-${m.certainty}${opts.selected === m.name ? ' selected' : ''}`;
    const common = opts.still ? { class: look } : {
      class: look,
      tabindex: 0,
      role: 'button',
      'aria-label': label(m),
      'aria-pressed': String(opts.selected === m.name),
      onclick: select,
      onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(); } },
    };
    if (m.places.length > 1) {
      const points = m.places.map((p) => at(p).join(',')).join(' ');
      return svg('g', common,
        svg('polyline', { points, class: 'rl-mk-hit' }),
        svg('polyline', { points, class: 'rl-mk-line' }),
        svg('title', {}, label(m)));
    }
    const [x, y] = at(m.places[0]);
    return svg('g', { ...common, transform: `translate(${x} ${y})` },
      opts.selected === m.name ? svg('circle', { r: size * 1.3, class: 'rl-mk-ring' }) : null,
      forceGlyph(m, detached(m) ? size * DETACHED_SIZE : size),
      svg('text', { x: size * 1.1, y: size * 1.4, 'font-size': size * 0.75, class: 'rl-mk-name' }, m.name),
      svg('title', {}, label(m)));
  });

  // the seat's own movement orders: a dashed arrow from where the force was last
  // reported to where it was sent, or a ring at the destination when no page placed it
  const arrows = orders.map((o) => {
    const from = map.marks.find((m) => m.name === o.mark)?.places[0];
    const [tx, ty] = at(o.to);
    const words = mapOrderLine(o);
    return svg('g', { class: `rl-mk-order rl-o-${o.status}`, role: 'img', 'aria-label': words },
      from ? svg('line', { x1: at(from)[0], y1: at(from)[1], x2: tx, y2: ty, class: 'rl-mk-arrow', 'marker-end': 'url(#rl-arrowhead)' }) : null,
      svg('circle', { cx: tx, cy: ty, r: size * 0.8, class: 'rl-mk-goal' }),
      svg('text', { x: tx + size, y: ty + size * 1.6, 'font-size': size * 0.7, class: 'rl-mk-name' },
        o.status === 'awaiting' ? `Ordered: ${o.force}` : `Under way: ${o.force}`),
      svg('title', {}, words));
  });

  return svg('svg', {
    class: 'rl-map-svg', viewBox: `0 0 ${proj.width} ${proj.height}`, preserveAspectRatio: 'xMidYMid meet',
    role: opts.still ? 'img' : 'group', 'aria-label': opts.label ?? 'Map of what your papers report',
  },
  svg('rect', { x: 0, y: 0, width: proj.width, height: proj.height, class: 'rl-map-sea' }),
  land ? svg('path', { d: landPath(land.rings, box, proj), class: 'rl-map-land' }) : null,
  opts.theatres ? theatreOutlines(map.places.filter(inBox), at, size) : null,
  svg('defs', {}, svg('marker', {
    id: 'rl-arrowhead', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: 'auto-start-reverse',
  }, svg('path', { d: 'M0 0L10 5L0 10Z', class: 'rl-mk-arrowhead' }))),
  places,
  arrows,
  targetRings(targets.filter((t) => inBox(t.place)), at, size, opts.onTarget),
  marks);
}

function legendSwatch(kind, side, certainty) {
  const mark = { kind, side, certainty };
  return svg('svg', { viewBox: '-14 -14 28 28', width: 22, height: 22, 'aria-hidden': 'true', focusable: 'false', class: `rl-mk rl-side-${side} rl-c-${certainty}` },
    forceGlyph(mark, 12));
}

function legendLine(kind) {
  return svg('svg', { viewBox: '0 0 28 12', width: 28, height: 12, 'aria-hidden': 'true', focusable: 'false', class: `rl-mk rl-mk-${kind} rl-c-reported` },
    svg('polyline', { points: '2,6 26,6', class: 'rl-mk-line' }));
}

const theatreSwatch = () => svg('svg', { viewBox: '0 0 28 16', width: 28, height: 16, 'aria-hidden': 'true', focusable: 'false', class: 'rl-theatre-key' },
  svg('rect', { x: 1, y: 1, width: 26, height: 14, rx: 4 }));

/** The diplomatic layer's key. */
function capitalLegend(theatres) {
  const item = (swatch, words) => h('li', {}, swatch, h('span', {}, words));
  return h('ul', { class: 'rl-legend', 'aria-label': 'Key' },
    item(svg('svg', { viewBox: '-14 -14 28 28', width: 22, height: 22, 'aria-hidden': 'true', focusable: 'false', class: 'rl-cap-key' }, capitalGlyph(14)),
      'A leader set against you, at their capital, with their stance toward you as your staff read it'),
    item(svg('svg', { viewBox: '-14 -14 28 28', width: 22, height: 22, 'aria-hidden': 'true', focusable: 'false' }, warGlyph(0, 0, 20)),
      'At war with you'),
    theatres ? item(theatreSwatch(), 'Theatre: the places it groups') : null);
}

/** The key; a line for detachments once the map shows one. */
function legend(map, theatres = false) {
  const item = (swatch, words) => h('li', {}, swatch, h('span', {}, words));
  const small = () => svg('svg', { viewBox: '-14 -14 28 28', width: 22, height: 22, 'aria-hidden': 'true', focusable: 'false', class: 'rl-mk rl-mk-detached rl-side-own rl-c-reported' },
    forceGlyph({ kind: 'fleet', side: 'own', certainty: 'reported' }, 12 * DETACHED_SIZE));
  return h('ul', { class: 'rl-legend', 'aria-label': 'Key' },
    item(legendSwatch('army', 'own', 'reported'), 'Yours'),
    item(legendSwatch('army', 'other', 'reported'), 'Foreign'),
    item(legendSwatch('fleet', 'own', 'known'), 'Known: your own side, lately reported'),
    item(legendSwatch('fleet', 'own', 'reported'), 'Reported: as a page has it, true or not'),
    item(legendSwatch('fleet', 'own', 'stale'), 'Stale: the latest page is over two weeks old'),
    item(svg('svg', { viewBox: '0 0 28 12', width: 28, height: 12, 'aria-hidden': 'true', focusable: 'false', class: 'rl-mk-order' },
      svg('polyline', { points: '2,6 26,6', class: 'rl-mk-arrow' })), 'Your order to move, until a page reports it there'),
    item(legendLine('front'), 'Front'),
    item(legendLine('route'), 'Convoy route'),
    map.marks.some(detached) ? item(small(), 'Detachment: part of a fleet sent off on its own') : null,
    theatres ? item(theatreSwatch(), 'Theatre: the places it groups') : null);
}

/** The capitals as a table, each with a button that opens its leader's card where one opens. */
function capitalTable(map, openCapital) {
  return h('table', { class: 'rl-map-list' },
    h('caption', {}, 'Every leader set against you who has a capital on your map'),
    h('thead', {}, h('tr', {}, ['Leader', 'Capital', 'Stance toward you', 'At war', ''].map((c) => h('th', { scope: 'col' }, c)))),
    h('tbody', {}, (map.capitals ?? []).map((c) => {
      const open = openCapital?.(c) ?? null;
      return h('tr', {},
        h('th', { scope: 'row' }, c.name),
        h('td', {}, c.place.name),
        h('td', {}, stanceWords(c.stance)),
        h('td', {}, c.at_war ? 'At war' : 'Not at war'),
        h('td', {}, open ? h('button', { type: 'button', class: 'rl-find', onclick: open }, 'Open the card') : null));
    })));
}

function detail(mark, onOpen) {
  return h('section', { class: 'rl-map-detail', 'aria-labelledby': 'rl-map-detail-h' },
    h('h3', { id: 'rl-map-detail-h' }, mark.name),
    h('dl', {},
      h('dt', {}, 'What'), h('dd', {}, whatWord(mark)),
      h('dt', {}, 'Side'), h('dd', {}, sideLine(mark)),
      h('dt', {}, 'Certainty'), h('dd', {}, certaintyWord(mark.certainty)),
      h('dt', {}, 'Where'), h('dd', {}, whereLine(mark))),
    h('p', { class: 'muted' }, sightedLine(mark)),
    h('button', { type: 'button', class: 'rl-submit', onclick: () => onOpen?.({ id: mark.document }) }, 'Open the page'));
}

function table(map, onFind) {
  return h('table', { class: 'rl-map-list' },
    h('caption', {}, 'Every mark on your map, as your papers have it'),
    h('thead', {}, h('tr', {}, ['Name', 'What', 'Side', 'Certainty', 'Where', 'Source', ''].map((c) => h('th', { scope: 'col' }, c)))),
    h('tbody', {}, sortMarks(map.marks).map((m) => h('tr', { class: `rl-c-${m.certainty}` },
      h('th', { scope: 'row' }, m.name),
      h('td', {}, markSwatch(m), whatWord(m)),
      h('td', {}, sideLine(m)),
      h('td', {}, certaintyWord(m.certainty)),
      h('td', {}, whereLine(m)),
      h('td', {}, sightedLine(m)),
      h('td', {}, h('button', { type: 'button', class: 'rl-find', onclick: () => onFind(m.name) }, 'Find on map'))))));
}

/**
 * `opts` is { mode: 'map'|'list', scope: 'reports'|'world', selected, onMode, onScope, onSelect(name, mode?), onOpen }.
 * With `onLayer`, a Military or Diplomatic switch picks `opts.layer`; on Diplomatic the map and
 * the list show the capitals (`openCapital`, as `mapDrawing`). `theatres` draws the theatres.
 */
export function mapView(map, land, opts = {}) {
  const { mode = 'map', scope = 'reports' } = opts;
  const diplomatic = opts.layer === 'diplomatic';
  const toggle = (value, word, current, on) => h('button', {
    type: 'button', class: 'rl-filter', 'aria-pressed': String(current === value), onclick: () => on?.(value),
  }, word);
  const bar = h('div', { class: 'rl-bar' },
    opts.onLayer
      ? h('div', { class: 'rl-filters', role: 'group', 'aria-label': 'Layer' },
        toggle('military', 'Military', diplomatic ? 'diplomatic' : 'military', opts.onLayer),
        toggle('diplomatic', 'Diplomatic', diplomatic ? 'diplomatic' : 'military', opts.onLayer))
      : null,
    h('div', { class: 'rl-filters', role: 'group', 'aria-label': 'Show as' },
      toggle('map', 'Map', mode, opts.onMode), toggle('list', 'List', mode, opts.onMode)),
    mode === 'map'
      ? h('div', { class: 'rl-filters', role: 'group', 'aria-label': 'How much of the world' },
        toggle('reports', 'Your reports', scope, opts.onScope), toggle('world', 'The world', scope, opts.onScope))
      : null);
  const selected = map.marks.find((m) => m.name === opts.selected) ?? null;
  const orders = diplomatic ? [] : map.orders ?? [];
  const capitals = map.capitals ?? [];
  const empty = diplomatic
    ? (capitals.length ? null : h('p', { class: 'muted' }, 'No leader set against you has a capital on your map yet.'))
    : (!map.marks.length && !orders.length ? h('p', { class: 'muted' }, 'No page has placed anything yet.') : null);
  const ordered = orders.length
    ? h('section', { class: 'rl-map-orders', 'aria-labelledby': 'rl-map-orders-h' },
      h('h3', { id: 'rl-map-orders-h' }, 'Your movement orders'),
      h('ul', {}, orders.map((o) => h('li', {}, mapOrderLine(o)))),
      h('p', { class: 'muted' }, 'A force is drawn where it was last reported; it moves on the map when a new page places it.'))
    : null;
  const find = (name) => opts.onSelect?.(name, 'map');
  const keyed = Boolean(opts.theatres) && map.places.some((p) => p.theatre);
  return h('section', { class: 'rl-map', 'aria-labelledby': 'rl-map-h' },
    h('h2', { id: 'rl-map-h' }, 'Map'),
    h('p', { class: 'muted' }, 'Drawn only from your own papers, as of when each was written.'),
    bar,
    empty,
    mode === 'list'
      ? (diplomatic
        ? [capitals.length ? capitalTable(map, opts.openCapital) : null]
        : [map.marks.length ? table(map, find) : null, ordered])
      : [h('figure', { class: 'rl-map-figure' }, mapDrawing(map, land, { ...opts, scope })),
        diplomatic ? capitalLegend(keyed) : legend(map, keyed),
        selected && !diplomatic ? detail(selected, opts.onOpen) : null, ordered]);
}
