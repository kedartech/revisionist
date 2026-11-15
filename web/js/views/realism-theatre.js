// The Theatre board: the seat's map, drawn from its own papers (view.realism.map). For now
// it is the map view as the room has it; picking a mark makes it the board's selected piece.
// Nothing here touches the page on import.

import { h } from '../dom.js';
import { mapDrawing, mapView } from './realism-map.js';

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

/**
 * `theatreBoard(rv, ui, { pick, act })`: the map for the board's main area. A mark picked on
 * the map or found from the list is `pick({ piece: { kind: 'force', name } })`; the Map or
 * List and the scope switches are `pick({ theatre })`. The piece's details are in the board's
 * side panel, so the map view's own detail block is left out.
 */
export function theatreBoard(rv, ui, { pick } = {}) {
  const map = rv.map;
  if (!map) {
    return h('section', { class: 'rl-map' },
      h('h2', {}, 'Map'), h('p', { class: 'muted' }, 'No page has placed anything yet.'));
  }
  const theatre = ui.theatre ?? { mode: 'map', scope: 'reports' };
  const opts = {
    ...theatre,
    selected: ui.piece?.kind === 'force' ? ui.piece.name : null,
    onMode: (mode) => pick?.({ theatre: { ...theatre, mode } }),
    onScope: (scope) => pick?.({ theatre: { ...theatre, scope } }),
    onSelect: (name, mode) => pick?.({ piece: { kind: 'force', name }, ...(mode ? { theatre: { ...theatre, mode } } : {}) }),
  };
  const view = mapView(map, coast, opts);
  view.querySelector('.rl-map-detail')?.remove();
  if (!coast && theatre.mode === 'map') {
    loadLand()?.then(() => {
      const fig = view.querySelector('figure.rl-map-figure');
      if (coast && fig?.isConnected) fig.replaceChildren(mapDrawing(map, coast, opts));
    });
  }
  return view;
}
