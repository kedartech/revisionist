// The territory map: in a game whose `map` block has `areas`, the board is drawn from the
// game's map file (the `map` action's shapes): land territories filled, sea zones outlined,
// every border stroked. The frame is a region's, worked out from its areas alone, and holds
// still whatever lights or lands; zoom is 1, 2 or 4 times within it. Marks and tap targets keep
// a minimum size in pixels whatever the zoom. Every area is focusable and has a row in the list.

import { h, svg } from '../dom.js';
import {
  LABEL_PX, MIN_MARK_PX, MIN_TAP_PX, ZOOMS, borders, boxOf, certaintyWord, frameRect, hiddenLabels, pinchZoom,
  regionChildren, regionFrames, regionTrail, sideLine, sightedLine, sortMarks, stanceWords, capitalLine,
  territoryProjection, unitsPerPx, viewWindow, whereLine,
} from '../realism-rules.js';
import { capitalGlyph, forceGlyph, stanceClass, warGlyph, whatWord } from './realism-map.js';

const r2 = (n) => Math.round(n * 100) / 100;

/** Each drawing's clip path needs an id of its own on the page. */
let clips = 0;

/** How far above its area's label point a piece is drawn, and the gap between pieces side by side, in pixels. */
const MARK_LIFT = 26;
const MARK_GAP = 40;

/** The glyph a piece's domain draws with. */
const GLYPH = Object.freeze({ land: 'army', sea: 'fleet', air: 'air' });

export const areaKindWord = (area) => (area.kind === 'sea' ? 'Sea zone' : 'Land territory');

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

const activate = (fn) => ({
  tabindex: 0,
  role: 'button',
  onclick: fn,
  onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn(); } },
});

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
  return `${m.name}: ${markWhat(m)}, ${sideLine(m)}, ${certaintyWord(m.certainty)}${where ? `, ${where}` : ''}`;
}

/** Where a mark stands: an own piece at its area's label point, a reported one at its place. */
function markAt(m, labelAt, at) {
  if (m.piece?.area?.key && labelAt.has(m.piece.area.key)) return labelAt.get(m.piece.area.key);
  return m.places?.length === 1 ? at([m.places[0].lon, m.places[0].lat]) : null;
}

function marksLayer(map, labelAt, at, opts) {
  const placed = sortMarks(map.marks ?? []).map((m) => ({ m, xy: m.places?.length > 1 ? null : markAt(m, labelAt, at) }));
  const crowd = new Map();
  for (const p of placed) if (p.xy) crowd.set(p.xy.join(), [...(crowd.get(p.xy.join()) ?? []), p.m]);
  return placed.map(({ m, xy }) => {
    const where = m.piece?.area?.name ?? whereLine(m);
    const words = markLabel(m, where);
    const chosen = opts.selected === m.name;
    const look = `rl-mk rl-mk-${m.kind} rl-side-${m.side} rl-c-${m.certainty} rl-tm-mark${chosen ? ' selected' : ''}`;
    const common = opts.still ? { class: look } : {
      class: look, 'aria-label': words, 'aria-pressed': String(chosen), ...activate(() => opts.onSelect?.(m.name)),
    };
    if (m.places?.length > 1) {
      const points = m.places.map((p) => at([p.lon, p.lat]).join(',')).join(' ');
      return svg('g', common, svg('polyline', { points, class: 'rl-mk-hit' }), svg('polyline', { points, class: 'rl-mk-line' }), svg('title', {}, words));
    }
    if (!xy) return null;
    const here = crowd.get(xy.join());
    const dx = (here.indexOf(m) - (here.length - 1) / 2) * MARK_GAP;
    const glyph = { ...m, kind: m.piece ? GLYPH[m.piece.domain] : m.kind };
    return atPx(common, xy[0], xy[1], svg('g', { transform: `translate(${dx} ${m.piece ? -MARK_LIFT : 0})` },
      svg('rect', { x: -MIN_TAP_PX / 2, y: -MIN_TAP_PX / 2, width: MIN_TAP_PX, height: MIN_TAP_PX, class: 'rl-tm-hit' }),
      chosen ? svg('circle', { r: MIN_MARK_PX * 0.95, class: 'rl-mk-ring' }) : null,
      forceGlyph(glyph, MIN_MARK_PX)),
    svg('title', {}, words));
  });
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

function ordersLayer(map, labelAt, at) {
  const from = (o) => {
    const m = (map.marks ?? []).find((k) => k.name === o.mark);
    return m ? markAt(m, labelAt, at) : null;
  };
  return (map.orders ?? []).map((o) => {
    const [tx, ty] = at([o.to.lon, o.to.lat]);
    const f = from(o);
    return svg('g', { class: `rl-mk-order rl-o-${o.status}`, role: 'img', 'aria-label': `${o.force} to ${o.to.name}` },
      f ? svg('line', { x1: f[0], y1: f[1], x2: tx, y2: ty, class: 'rl-mk-arrow' }) : null,
      atPx({ class: 'rl-tm-goal' }, tx, ty, svg('circle', { r: MIN_MARK_PX * 0.6, class: 'rl-mk-goal' })));
  });
}

function targetsLayer(targets, at, onTarget) {
  return targets.map((t) => {
    const [x, y] = at([t.place.lon, t.place.lat]);
    const pick = () => onTarget?.(t.value);
    const said = [t.days, t.liftWords ?? t.lift].filter(Boolean);
    const words = `Send to ${t.place.name}${said.length ? `: ${said.join('. ')}` : ''}`;
    return atPx({
      class: `rl-map-target${t.refused ? ' refused' : ''}${t.chosen ? ' chosen' : ''}`, 'data-place': t.place.name,
      'aria-label': words, 'aria-pressed': String(t.chosen), 'aria-disabled': t.refused ? 'true' : null, ...activate(pick),
    }, x, y,
    svg('circle', { r: MIN_TAP_PX / 2, class: 'rl-target-ring' }),
    [t.days, t.lift].filter(Boolean).map((line, i) => svg('text', { x: MIN_TAP_PX / 2 + 2, y: 4 + i * LABEL_PX * 1.2, 'font-size': LABEL_PX, class: 'rl-target-note' }, line)),
    svg('title', {}, words));
  });
}

/**
 * The drawing of a territory map `map` (the seat's `map` block) from `shapes` (its map file).
 * `opts`: { frame (a region's key, '' or null for the whole map), zoom, centre, px, layer,
 * selected, onSelect, targets, onTarget, openCapital, onView, still, label }.
 */
export function territoryDrawing(map, shapes, opts = {}) {
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
  const borderKind = ([a, b]) => {
    if (b === null || !kinds.has(b)) return 'edge';
    const both = [kinds.get(a), kinds.get(b)];
    return both.every((k) => k === 'land') ? 'land' : both.every((k) => k === 'sea') ? 'sea' : 'coast';
  };
  clips += 1;
  const clip = `rl-tm-clip-${clips}`;
  const frameBox = { x: r2(win.x), y: r2(win.y), width: r2(win.w), height: r2(win.h) };
  root = svg('svg', {
    class: 'rl-map-svg rl-tm-svg', viewBox: `${r2(win.x)} ${r2(win.y)} ${r2(win.w)} ${r2(win.h)}`, preserveAspectRatio: 'xMidYMid meet',
    role: opts.still ? 'img' : 'group', 'aria-label': opts.label ?? 'Map of the board', 'data-frame': opts.frame ?? '',
  },
  svg('defs', {}, svg('clipPath', { id: clip }, svg('rect', frameBox))),
  svg('g', { class: 'rl-tm-frame', 'clip-path': `url(#${clip})` },
  svg('rect', { x: 0, y: 0, width: proj.width, height: proj.height, class: 'rl-map-sea' }),
  (shapes.backdrop ?? []).map((ring) => svg('path', { d: ringsPath(shapes.vertices, [ring], at), class: 'rl-tm-backdrop' })),
  areas.map((a) => svg('path', {
    d: ringsPath(shapes.vertices, shapes.areas[a.key].rings, at), class: `rl-area rl-area-${a.kind === 'sea' ? 'sea' : 'land'}`,
    'data-area': a.key, 'aria-label': `${a.name}: ${areaKindWord(a)}, ${regions.get(a.region) ?? a.region}`,
    ...(opts.still ? {} : activate(() => show(a.key))),
  })),
  borders(shapes).filter(({ between }) => kinds.has(between[0])).map(({ between, edges }) => svg('path', {
    d: edges.map(([p, q]) => `M${at(shapes.vertices[p]).join(' ')}L${at(shapes.vertices[q]).join(' ')}`).join(''),
    class: `rl-border rl-border-${borderKind(between)}`, 'data-between': between.filter(Boolean).join(' '),
  })),
  areas.map((a) => atPx({ class: 'rl-tm-label', 'data-area': a.key, 'data-text': a.name, 'aria-hidden': 'true' },
    ...labelAt.get(a.key), svg('text', { 'font-size': LABEL_PX, 'text-anchor': 'middle', dy: '0.35em' }, a.name))),
  diplomatic ? null : ordersLayer(map, labelAt, at),
  targetsLayer(targets, at, opts.onTarget),
  diplomatic ? capitalsLayer(map, at, opts) : marksLayer(map, labelAt, at, opts)));
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

function areaTable(map) {
  const names = new Map((map.areas ?? []).map((a) => [a.key, a.name]));
  const regions = new Map((map.regions ?? []).map((r) => [r.key, r.name]));
  return h('table', { class: 'rl-map-list rl-area-list' },
    h('caption', {}, 'Every area of the board'),
    h('thead', {}, h('tr', {}, ['Area', 'Kind', 'Region', 'Borders'].map((c) => h('th', { scope: 'col' }, c)))),
    h('tbody', {}, (map.areas ?? []).map((a) => h('tr', { 'data-area': a.key },
      h('th', { scope: 'row' }, a.name),
      h('td', {}, areaKindWord(a)),
      h('td', {}, regions.get(a.region) ?? a.region),
      h('td', {}, a.neighbours.map((n) => names.get(n) ?? n).join(', '))))));
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
      shapes ? territoryDrawing(map, shapes, { ...opts, layer, frame, zoom }) : h('p', { class: 'muted rl-tm-wait' }, opts.waiting ?? 'Drawing the map…'))];
  return h('section', { class: 'rl-map rl-tmap', 'aria-labelledby': 'rl-map-h' },
    h('h2', { id: 'rl-map-h' }, 'Map'),
    h('p', { class: 'muted' }, 'The board as the game\'s map draws it; your pieces and reports from your own papers.'),
    bar,
    body);
}
