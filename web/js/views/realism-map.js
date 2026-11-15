// The realism map: forces, fronts and routes as the seat's own papers place them,
// drawn over Natural Earth coastlines, and the same marks as a list for keyboard
// and screen-reader use. Takes view.realism.map (realism_api.py SeatMap).

import { h, svg } from '../dom.js';
import {
  capitalLine, certaintyWord, landPath, mapBox, mapOrderLine, markKindWord, projection, sideLine, sightedLine, sortMarks,
  stanceWords, theatreAreas, whereLine,
} from '../realism-rules.js';

const r2 = (n) => Math.round(n * 100) / 100;

/** A detachment's mark, as a share of a whole force's. */
const DETACHED_SIZE = 0.7;

/** The marker for a force: shape says side, fill and line say certainty, a glyph says kind. */
function forceGlyph(mark, size) {
  const r = size / 2;
  const shape = mark.side === 'own'
    ? svg('rect', { x: -r * 1.4, y: -r, width: r * 2.8, height: r * 2, class: 'rl-mk-shape' })
    : svg('path', { d: `M0 ${-r * 1.4}L${r * 1.4} 0L0 ${r * 1.4}L${-r * 1.4} 0Z`, class: 'rl-mk-shape' });
  const q = r * 0.6;
  const inner = {
    fleet: svg('path', { d: `M${-q} 0H${q}M${-q} ${q / 2}Q0 ${q * 1.2} ${q} ${q / 2}`, class: 'rl-mk-glyph' }),
    army: svg('path', { d: `M${-q} ${-q / 1.5}L${q} ${q / 1.5}M${-q} ${q / 1.5}L${q} ${-q / 1.5}`, class: 'rl-mk-glyph' }),
    air: svg('path', { d: `M${-q} ${q / 2}L0 ${-q / 2}L${q} ${q / 2}`, class: 'rl-mk-glyph' }),
  }[mark.kind];
  const tick = mark.certainty === 'stale'
    ? svg('path', { d: `M${r * 1.2} ${-r * 1.6}l${r * 0.6} ${-r * 0.6}`, class: 'rl-mk-tick' })
    : null;
  return [shape, inner, tick];
}

/** A capital's marker: a five-pointed star, its colour the stance (a third cue: the words say it). */
function capitalGlyph(size) {
  const r = size * 0.8;
  const pts = Array.from({ length: 10 }, (_, i) => {
    const a = (Math.PI / 5) * i - Math.PI / 2;
    const k = (i & 1) ? r * 0.45 : r;
    return `${(Math.cos(a) * k).toFixed(2)},${(Math.sin(a) * k).toFixed(2)}`;
  });
  return svg('polygon', { points: pts.join(' '), class: 'rl-cap-shape' });
}

/** The war mark beside a capital: two crossed strokes in a ring. */
function warGlyph(x, y, size) {
  const q = size * 0.35;
  return svg('g', { class: 'rl-cap-war', transform: `translate(${x} ${y})` },
    svg('circle', { r: size * 0.55 }),
    svg('path', { d: `M${-q} ${-q}L${q} ${q}M${-q} ${q}L${q} ${-q}` }));
}

const stanceClass = (stance) => (Number.isInteger(stance?.step) ? ` rl-stance-${stance.step}` : '');

/** The engine names a detachment "<fleet's name> detachment <n>"; a page sights it by that name. */
const DETACHMENT = / detachment \d+$/;

/** A mark that a page names as a fleet's detachment. */
const detached = (mark) => DETACHMENT.test(mark.name);

/** What a mark is, in words: "Fleet", or "Fleet detachment" for a detachment. */
const whatWord = (mark) => (detached(mark) ? `${markKindWord(mark.kind)} detachment` : markKindWord(mark.kind));

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

  const marks = diplomatic ? capitalPins(map, at, size, opts) : sortMarks(map.marks).map((m) => {
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
      h('td', {}, whatWord(m)),
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
