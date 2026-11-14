// Where forces moved: What happened replays the marks that changed place between the seat's
// map before the run and its map after, as routes drawn with the map view's own drawing and a
// list beside them. Both maps are the seat's own (`view.realism.map`): only what its papers place.

import { h } from '../dom.js';
import { whereLine } from '../realism-rules.js';
import { mapView } from './realism-map.js';

const placeKey = (places) => (places ?? []).map((p) => p.name).join('|');

/**
 * The marks in both maps whose places differ, keyed by mark name, in the order of `after`:
 * `{ name, kind, side, side_name, certainty, from, to }`. A mark only in `after` (newly sighted)
 * or only in `before` (lost from sight) is not a move. Missing maps give none.
 */
export function movedMarks(before, after) {
  const was = new Map((before?.marks ?? []).map((m) => [m.name, m]));
  const out = [];
  for (const m of after?.marks ?? []) {
    const b = was.get(m.name);
    if (!b || placeKey(b.places) === placeKey(m.places)) continue;
    out.push({
      name: m.name, kind: m.kind, side: m.side, side_name: m.side_name, certainty: m.certainty,
      from: b.places, to: m.places,
    });
  }
  return out;
}

/**
 * The moves of the run this room started (`runFrom`: `{ wake, map }`, kept when the run began),
 * for the wake page right after it only; none for any other page or with no run kept.
 */
export function runMoves(runFrom, page, map) {
  if (!runFrom || !page || page.number !== runFrom.wake + 1) return [];
  return movedMarks(runFrom.map, map);
}

/** "US Atlantic Fleet: Norfolk to Argentia". */
export function moveLine(move) {
  return `${move.name}: ${whereLine({ places: move.from })} to ${whereLine({ places: move.to })}`;
}

/** The marks to draw: each move as a line from where it was to where it is, and a force's mark at its new place. */
function drawn(moves) {
  return moves.flatMap((m) => {
    const mark = { name: m.name, kind: m.kind, side: m.side, side_name: m.side_name, certainty: m.certainty };
    if (m.to.length > 1) return [{ ...mark, places: m.to }];
    return [{ ...mark, places: [m.from.at(-1), m.to[0]] }, { ...mark, places: m.to }];
  });
}

const LAND_URL = '/assets/land-110m.json';
let coast = null;
let landing = null;

/** The coastlines, fetched once; until they arrive (or if they never do) the map has none. */
function loadLand() {
  if (coast || landing || typeof fetch !== 'function') return landing;
  landing = Promise.resolve()
    .then(() => fetch(LAND_URL))
    .then((r) => (r.ok ? r.json() : null))
    .then((json) => { if (Array.isArray(json?.rings)) coast = json; })
    .catch(() => {})
    .finally(() => { landing = null; });
  return landing;
}

/** The map view's figure alone (no switches, key or detail), drawing `marks` over `places`. */
function figureOf(marks, places, land) {
  return mapView({ places, marks, orders: [] }, land, { mode: 'map', scope: 'reports' })
    .querySelector('figure.rl-map-figure');
}

/**
 * The block: "Where forces moved", the routes on a map (the map view's figure only, with the
 * places the seat's map has) and one line per move. The coastlines are `land`, else fetched
 * once and drawn in when they arrive. Null with no moves.
 */
export function movesBlock({ moves, places, land = null } = {}) {
  if (!moves?.length) return null;
  const marks = drawn(moves);
  const at = places ?? [];
  const figure = figureOf(marks, at, land ?? coast);
  if (!land && !coast) {
    loadLand()?.then(() => {
      if (coast && figure?.isConnected) figure.replaceWith(figureOf(marks, at, coast));
    });
  }
  return h('section', { class: 'rl-moves', 'aria-labelledby': 'rl-moves-h' },
    h('h3', { id: 'rl-moves-h' }, 'Where forces moved'),
    h('div', { class: 'rl-moves-body' },
      figure,
      h('ul', { class: 'rl-moves-list' }, moves.map((m) => h('li', { class: `rl-side-${m.side}` }, moveLine(m))))));
}
