// The Theatre board: the seat's map, drawn from its own papers (view.realism.map), filling the
// board. Each theatre is a labelled box around its places. A layer switch shows the forces
// (Military) or the capitals of the leaders set against the seat (Diplomatic). A picked force
// of the seat's shows the forms that can move it; a picked capital opens its leader's card.
// Nothing here touches the page on import.

import { api } from '../api.js';
import { h } from '../dom.js';
import { formsMoving } from '../realism-rules.js';
import { figureCard } from './realism-figure.js';
import { daysLabel, liftLabel, liftNote, standardForm, tierLabel } from './realism-forms.js';
import { mapDrawing, mapView } from './realism-map.js';
import { territoryDrawing, territoryView } from './realism-territory.js';

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

// A territory game's shapes, by the map file's hash: fetched once per hash, kept for the page.
const shapesBy = new Map();
const asking = new Map();

/** The shapes for map file `file` ({ name, sha256 }), when they are here; null until then. */
export const shapesFor = (file) => shapesBy.get(file?.sha256) ?? null;

/**
 * Fetch the shapes for `file` once: a promise while one is out, null once they are here or
 * when there is no file. A refusal or a reply for another hash keeps none (the next draw asks
 * again); a reply that fails to arrive is asked for again on the next draw too.
 */
export function loadShapes(file, ask = api.map) {
  const hash = file?.sha256;
  if (!hash || shapesBy.has(hash)) return null;
  if (asking.has(hash)) return asking.get(hash);
  const out = Promise.resolve()
    .then(() => ask())
    .then((r) => { if (!r?.refused && r?.file?.sha256 === hash && r.map) shapesBy.set(hash, r.map); })
    .catch(() => {})
    .finally(() => asking.delete(hash));
  asking.set(hash, out);
  return out;
}

/** Forget every fetched shape (tests). */
export function forgetShapes() { shapesBy.clear(); asking.clear(); }

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
 * `onPlaces(n, state)` is told form n's place picker state (`standardForm`).
 */
function movingForms(rv, piece, act, onPlaces) {
  if (piece?.kind !== 'force') return null;
  const mark = (rv.map?.marks ?? []).find((m) => m.name === piece.name);
  const forms = formsMoving(rv.desk?.levers, mark);
  if (!forms.length) return null;
  const items = forms.map(({ lever, force }, n) => {
    const item = standardForm(lever, {
      force, onSubmit: (v) => act?.('Sending it…', 'lever', v), entities: [], onPlaces: (s) => onPlaces(n, s),
    });
    item.querySelector('.rl-instrument-head [aria-expanded="false"]')?.click();
    return item;
  });
  return h('section', { class: 'rl-theatre-forms', 'aria-labelledby': 'rl-theatre-forms-h' },
    h('h3', { id: 'rl-theatre-forms-h' }, `Move ${mark.name}`),
    h('ul', { class: 'rl-instruments', role: 'list' }, items));
}

/**
 * The map's lit places for an open form's picker state: each place it offers that the map
 * holds, with its days (or "Out of reach") and its lift line for the form's force. `from`:
 * where the seat's latest page places the force, the start of a sea leg.
 */
function litPlaces(map, s, from) {
  const at = new Map(map.places.map((p) => [p.name, p]));
  return s.places.filter((p) => at.has(p.label)).map((p) => {
    const reach = s.force ? p.reach?.[s.force] ?? null : null;
    const refused = reach?.tier === 'refused';
    return {
      place: at.get(p.label),
      value: p.value,
      days: !s.force ? null : refused ? tierLabel(reach) : daysLabel(p.days?.[s.force] ?? null),
      lift: s.force ? liftNote(p.lift?.[s.force] ?? null) : null,
      liftWords: s.force ? liftLabel(p.lift?.[s.force] ?? null) : null,
      refused,
      chosen: s.value === p.value,
      from,
    };
  });
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
  // each moving form's place picker state; the lit places follow the form told last while open
  const states = new Map();
  let active = null;
  let redraw = () => {};
  const onPlaces = (n, s) => {
    states.set(n, s);
    if (s.open) active = n;
    else if (active === n) active = [...states].reverse().find(([, v]) => v.open)?.[0] ?? null;
    redraw();
  };
  const from = (map.marks ?? []).find((m) => ui.piece?.kind === 'force' && m.name === ui.piece.name)?.places?.[0] ?? null;
  const lit = () => (active === null ? [] : litPlaces(map, states.get(active), from));
  const forms = theatre.layer === 'diplomatic' ? null : movingForms(rv, ui.piece, act, onPlaces);
  const opts = {
    ...theatre,
    theatres: true,
    selected: ui.piece?.kind === 'force' ? ui.piece.name : null,
    openCapital: capitalOpener(rv.people),
    onTarget: (value) => states.get(active)?.choose(value),
    onMode: (mode) => pick?.({ theatre: { ...theatre, mode } }),
    onScope: (scope) => pick?.({ theatre: { ...theatre, scope } }),
    onLayer: (layer) => pick?.({ theatre: { ...theatre, layer } }),
    onSelect: (name, mode) => pick?.({ piece: { kind: 'force', name }, ...(mode ? { theatre: { ...theatre, mode } } : {}) }),
  };
  const territorial = Array.isArray(map.areas) && map.areas.length > 0;
  // the stack fanned out, by its area: the view's own, redrawn in place, focus kept on the stack
  let fanned = theatre.fanned ?? null;
  let fanFocus = null;
  if (territorial) {
    Object.assign(opts, {
      fanned,
      onFan: (key) => {
        fanFocus = key ?? fanned;
        fanned = key;
        opts.fanned = key;
        // kept on the room's own theatre state, so the next poll's drawing keeps the fan
        if (ui.theatre) ui.theatre.fanned = key;
        redraw();
      },
      onArea: (area) => pick?.({ theatre: { ...theatre, area } }),
      onFrame: (frame) => pick?.({ theatre: { ...theatre, frame, zoom: 1, centre: null } }),
      onView: ({ zoom, centre }) => pick?.({ theatre: { ...theatre, zoom, centre } }),
    });
  }
  const drawing = territorial
    ? () => (shapesFor(map.file) ? territoryDrawing(map, shapesFor(map.file), { ...opts, targets: lit() }) : h('p', { class: 'muted rl-tm-wait' }, 'Drawing the map…'))
    : () => mapDrawing(map, coast, { ...opts, scope: theatre.scope ?? 'reports', targets: lit() });
  const view = territorial
    ? territoryView(map, shapesFor(map.file), { ...opts, targets: lit() })
    : mapView(map, coast, { ...opts, targets: lit() });
  view.classList.add('rl-theatre');
  view.querySelector('.rl-map-detail')?.remove();
  if (forms) {
    const fig = view.querySelector('figure.rl-map-figure');
    if (fig) fig.after(forms);
    else view.append(forms);
  }
  redraw = () => {
    const fig = view.querySelector('figure.rl-map-figure');
    if (!fig) return;
    const was = document.activeElement;
    const focused = was?.closest?.('figure.rl-map-figure') === fig ? was.getAttribute('data-place') : null;
    fig.replaceChildren(drawing());
    if (focused) Array.from(fig.querySelectorAll('.rl-map-target')).find((t) => t.getAttribute('data-place') === focused)?.focus();
    if (fanFocus !== null) {
      const here = Array.from(fig.querySelectorAll('[data-stack]')).filter((g) => g.getAttribute('data-stack') === fanFocus);
      (fanned === fanFocus ? here.find((g) => g.classList.contains('rl-tm-mark')) : here.find((g) => g.classList.contains('rl-tm-stack')))?.focus();
      fanFocus = null;
    }
  };
  if (territorial) {
    if (!shapesFor(map.file) && theatre.mode !== 'list') {
      loadShapes(map.file)?.then(() => {
        if (!shapesFor(map.file) || !view.isConnected) return;
        const fresh = territoryView(map, shapesFor(map.file), { ...opts, targets: lit() });
        view.replaceChildren(...fresh.childNodes);
        if (forms) view.querySelector('figure.rl-map-figure')?.after(forms);
      });
    }
    return view;
  }
  if (!coast && theatre.mode === 'map') {
    loadLand()?.then(() => {
      const fig = view.querySelector('figure.rl-map-figure');
      if (coast && fig?.isConnected) fig.replaceChildren(drawing());
    });
  }
  return view;
}
