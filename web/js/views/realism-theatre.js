// The Theatre board: the seat's map, drawn from its own papers (view.realism.map), filling the
// board. Each theatre is a labelled box around its places. A layer switch shows the forces
// (Military) or the capitals of the leaders set against the seat (Diplomatic). A picked force
// of the seat's shows the forms that can move it; a picked capital opens its leader's card.
// Nothing here touches the page on import.

import { h } from '../dom.js';
import { formsMoving } from '../realism-rules.js';
import { figureCard } from './realism-figure.js';
import { standardForm } from './realism-forms.js';
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
 * What a pick on capital `c` opens: its leader's figure card from the People roster's line,
 * as the roster shows it; null when the roster holds no line for that leader.
 */
function capitalOpener(people) {
  return (c) => {
    const line = (people?.opponents ?? []).find((l) => l.name === c.name);
    if (!line) return null;
    return () => {
      const from = document.activeElement;
      const card = figureCard(line, 'opponents', {
        onClose: () => {
          card.remove();
          if (from?.isConnected) from.focus();
        },
      });
      document.body.append(card);
      card.showModal();
    };
  };
}

/**
 * The forms that can move a force of the seat's that the map holds, each open on that force:
 * a `<section class="rl-theatre-forms">`, or null for a foreign force or one no form moves.
 */
function movingForms(rv, piece, act) {
  if (piece?.kind !== 'force') return null;
  const mark = (rv.map?.marks ?? []).find((m) => m.name === piece.name);
  const forms = formsMoving(rv.desk?.levers, mark);
  if (!forms.length) return null;
  const items = forms.map(({ lever, force }) => {
    const item = standardForm(lever, { force, onSubmit: (v) => act?.('Sending it…', 'lever', v), entities: [] });
    item.querySelector('.rl-instrument-head [aria-expanded="false"]')?.click();
    return item;
  });
  return h('section', { class: 'rl-theatre-forms', 'aria-labelledby': 'rl-theatre-forms-h' },
    h('h3', { id: 'rl-theatre-forms-h' }, `Move ${mark.name}`),
    h('ul', { class: 'rl-instruments', role: 'list' }, items));
}

/**
 * `theatreBoard(rv, ui, { pick, act })`: the map for the board's main area. A mark picked on
 * the map or found from the list is `pick({ piece: { kind: 'force', name } })`; the Map or
 * List, the scope and the layer switches are `pick({ theatre })`. The piece's details are in
 * the board's side panel, so the map view's own detail block is left out.
 */
export function theatreBoard(rv, ui, { pick, act } = {}) {
  const map = rv.map;
  if (!map) {
    return h('section', { class: 'rl-map rl-theatre' },
      h('h2', {}, 'Map'), h('p', { class: 'muted' }, 'No page has placed anything yet.'));
  }
  const theatre = ui.theatre ?? { mode: 'map', scope: 'reports' };
  const opts = {
    ...theatre,
    theatres: true,
    selected: ui.piece?.kind === 'force' ? ui.piece.name : null,
    openCapital: capitalOpener(rv.people),
    onMode: (mode) => pick?.({ theatre: { ...theatre, mode } }),
    onScope: (scope) => pick?.({ theatre: { ...theatre, scope } }),
    onLayer: (layer) => pick?.({ theatre: { ...theatre, layer } }),
    onSelect: (name, mode) => pick?.({ piece: { kind: 'force', name }, ...(mode ? { theatre: { ...theatre, mode } } : {}) }),
  };
  const view = mapView(map, coast, opts);
  view.classList.add('rl-theatre');
  view.querySelector('.rl-map-detail')?.remove();
  const forms = theatre.layer === 'diplomatic' ? null : movingForms(rv, ui.piece, act);
  if (forms) {
    const fig = view.querySelector('figure.rl-map-figure');
    if (fig) fig.after(forms);
    else view.append(forms);
  }
  if (!coast && theatre.mode === 'map') {
    loadLand()?.then(() => {
      const fig = view.querySelector('figure.rl-map-figure');
      if (coast && fig?.isConnected) fig.replaceChildren(mapDrawing(map, coast, opts));
    });
  }
  return view;
}
