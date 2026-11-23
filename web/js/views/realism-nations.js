// The nations as a bar chart, with a card each (NBR): World's Nations part in the map-first room.
// One horizontal bar per nation in the server's order (largest first): the flag, the name (drawn
// from 1024 px; under it the flag labels the row), a mark for the relation that is a shape and not
// a colour, the bar against the largest figure shown, and the figure at its end. Ten rows, the
// seat's own among them, then "All nations" opens the rest in place. A row opens that nation's
// card in the chart's place: its flag, name and relation, the figure and what it is, its band at
// home as a five-step meter when the server sent a reading, and for the seat's own nation its war
// economy and its home sheet. With no economy block the nations are listed with flags and bands.
// Only what the seat's view carries is drawn: another nation's components are never read.
// `standingGrid` is World's Standing part: a tile for each nation with its flag, name and relation,
// the nations it is at war with as small flags (the public list) and its public pacts by name; a
// tile opens that nation's card.
// Nothing here touches the page on import.

import { h, svg } from '../dom.js';
import { flagBadge, loadFlagIndex } from '../flags.js';
import { worldDate } from '../rules.js';
import { ownSheet } from './realism-economy.js';
import { BANDS, bandWords } from './realism-home.js';

/** The rows shown before "All nations" `[proposed]`. */
export const SHOWN = 10;

const num = (n) => (Number.isInteger(n) ? String(n) : String(Number(Number(n).toFixed(2))));
const RELATIONS = { own: 'Yours', ally: 'Ally', enemy: 'Enemy', neutral: 'Neutral' };
const relOf = (nation) => (Object.hasOwn(RELATIONS, nation?.relation ?? '') ? nation.relation : 'neutral');

/** Each relation's mark, a shape in a 12 by 12 box: a solid diamond, a ring, a cross, a bar. */
const MARKS = {
  own: () => svg('path', { d: 'M6 1 L11 6 L6 11 L1 6 Z' }),
  ally: () => svg('circle', { cx: 6, cy: 6, r: 4 }),
  enemy: () => svg('path', { d: 'M2 2 L10 10 M10 2 L2 10' }),
  neutral: () => svg('path', { d: 'M2 6 L10 6' }),
};

/** The relation's mark, hidden from assistive tech: its word is in the row's name. */
const relMark = (rel) => svg('svg', {
  class: 'rl-nb-rel', 'data-relation': rel, viewBox: '0 0 12 12', width: 12, height: 12, 'aria-hidden': 'true', focusable: 'false',
}, MARKS[rel]());

/**
 * The nations in the server's order as `{ nation, figure, band }`: the economy's figures, each
 * with its band from the home block (`null` with no reading); with no economy, the home block's
 * standings with `figure: null`. `[]` with neither.
 */
export function nationRows(rv) {
  const bands = new Map((rv.home?.standings ?? []).map((s) => [s.nation.key, s.band ?? null]));
  if (rv.economy?.figures?.length) {
    return rv.economy.figures.map((f) => ({ nation: f.nation, figure: Number(f.figure), band: bands.get(f.nation.key) ?? null }));
  }
  return (rv.home?.standings ?? []).map((s) => ({ nation: s.nation, figure: null, band: s.band ?? null }));
}

/** The rows shown: all of them, or the first `SHOWN` with the seat's own in the last place when it is further down. */
export function shownRows(rows, all) {
  if (all || rows.length <= SHOWN) return rows;
  const first = rows.slice(0, SHOWN);
  if (first.some((r) => relOf(r.nation) === 'own')) return first;
  const own = rows.find((r) => relOf(r.nation) === 'own');
  return own ? [...rows.slice(0, SHOWN - 1), own] : first;
}

/** A bar's length, 0 to 100: `figure` against the largest figure in `rows`; nothing below nought. */
export function barShare(figure, rows) {
  const top = Math.max(0, ...rows.map((r) => Number(r.figure) || 0));
  return top > 0 ? Math.round((100 * Math.max(0, Number(figure) || 0)) / top) : 0;
}

/** The bar: a track and its fill in a 100-wide box, so no length is written as a style. */
const bar = (share) => svg('svg', {
  class: 'rl-nb-bar', viewBox: '0 0 100 8', preserveAspectRatio: 'none', 'aria-hidden': 'true', focusable: 'false',
}, svg('rect', { class: 'rl-nb-track', x: 0, y: 0, width: 100, height: 8 }), svg('rect', { class: 'rl-nb-fill', x: 0, y: 0, width: share, height: 8 }));

/** The band as five steps, the band's own step and those under it on; `null` with no reading. */
function meter(band) {
  const step = BANDS.indexOf(band) + 1;
  if (step < 1) return null;
  return h('span', { class: 'rl-nb-meter', role: 'img', 'aria-label': `${bandWords(band)}: ${step} of 5`, 'data-step': String(step) },
    [1, 2, 3, 4, 5].map((i) => h('span', { class: `rl-nb-step${i <= step ? ' on' : ''}`, 'aria-hidden': 'true' })));
}

const flagOf = (rv, nation, opts) => flagBadge({
  world: rv.world_key, key: rv.nation_keys?.[nation.key] ?? null, name: nation.name, relation: relOf(nation),
}, opts);

/** A row's accessible name: the name, the relation, the figure and the band where each is sent. */
function rowName({ nation, figure, band }) {
  const rel = relOf(nation);
  const parts = [rel === 'own' ? `${nation.name} (yours)` : `${nation.name}, ${rel}`];
  if (figure !== null) parts.push(`war-economy figure ${num(figure)}`);
  if (band) parts.push(bandWords(band));
  return `${parts.join(', ')}. Open its card`;
}

const findRow = (root, key) => [...root.querySelectorAll('button.rl-nb-row')].find((b) => b.getAttribute('data-nation') === key) ?? null;

let flags = null;

/**
 * World's Nations part: `nationsPanel(rv, { state, act, onOffer, onHome })`. `state` is kept by
 * the room across redraws (`open`, the nation whose card is open; `all`, the rest shown; `eco`,
 * the own card's war economy open). `onHome()` opens the home sheet; `onOffer(nation)` puts
 * "Make an offer" on another nation's card. `null` with neither an economy nor a home block.
 */
export function nationsPanel(rv, { state = {}, act, onOffer = null, onHome = null } = {}) {
  const rows = nationRows(rv);
  if (!rows.length) return null;
  const bars = rows.some((r) => r.figure !== null);
  const root = h('section', { class: 'rl-nations-body rl-nb', 'data-mode': bars ? 'bars' : 'list', 'aria-label': 'Nations' });

  const rowButton = (r) => {
    const rel = relOf(r.nation);
    return h('li', {}, h('button', {
      type: 'button', class: `rl-nb-row${rel === 'own' ? ' rl-nb-own' : ''}`, 'data-nation': r.nation.key, 'data-relation': rel,
      'aria-label': rowName(r), onclick: () => openCard(r.nation.key),
    },
    flagOf(rv, r.nation, { height: 20 }),
    h('span', { class: 'rl-nb-name' }, r.nation.name, rel === 'own' ? h('span', { class: 'rl-nb-yours' }, ' · yours') : null),
    relMark(rel),
    bars ? bar(barShare(r.figure, rows)) : h('span', { class: 'rl-nb-band' }, r.band ?? ''),
    bars ? h('span', { class: 'rl-nb-num' }, num(r.figure)) : null));
  };

  const chart = () => [
    bars ? h('p', { class: 'hint rl-nb-hint' }, 'Largest first. Another nation\'s figure is read from the map: what it holds, at what the board prints.') : null,
    h('ul', { class: 'rl-nb-rows', role: 'list' }, shownRows(rows, state.all).map(rowButton)),
    rows.length > SHOWN ? h('button', {
      type: 'button', class: 'rl-btn rl-nb-all', 'aria-expanded': String(Boolean(state.all)),
      onclick: () => { state.all = !state.all; draw(); root.querySelector('button.rl-nb-all')?.focus(); },
    }, state.all ? `The first ${SHOWN}` : `All ${rows.length} nations`) : null,
  ];

  const ways = (r, rel, own) => {
    if (rel !== 'own') {
      return onOffer ? h('div', { class: 'rl-nb-ways' }, h('button', { type: 'button', class: 'rl-btn', onclick: () => onOffer(r.nation) }, 'Make an offer')) : null;
    }
    return h('div', { class: 'rl-nb-ways' },
      own ? h('button', {
        type: 'button', class: 'rl-btn rl-nb-eco', 'aria-expanded': String(Boolean(state.eco)),
        onclick: () => { state.eco = !state.eco; draw(); root.querySelector('button.rl-nb-eco')?.focus(); },
      }, 'Your war economy') : null,
      rv.home ? h('button', { type: 'button', class: 'rl-btn rl-nb-home', onclick: () => onHome?.() }, 'At home') : null);
  };

  const card = (r) => {
    const rel = relOf(r.nation);
    // the components drawn are the seat's own block's, and only on the seat's own card
    const own = rel === 'own' && rv.economy?.own?.nation?.key === r.nation.key;
    const figure = r.figure === null ? null : h('div', { class: 'rl-nb-fact' },
      h('h4', {}, 'War economy'),
      h('p', { class: 'rl-nb-figure' }, num(r.figure)),
      bar(barShare(r.figure, rows)),
      h('p', { class: 'muted' }, rel === 'own'
        ? `Your war-economy figure, counted for ${worldDate(rv.economy.day)}.`
        : 'Read from the map: what it holds, at what the board prints. You see no more of it.'));
    const band = r.band ? h('div', { class: 'rl-nb-fact' }, h('h4', {}, 'At home'), meter(r.band), h('p', {}, bandWords(r.band))) : null;
    return h('section', {
      class: 'rl-nb-card', 'data-nation': r.nation.key, 'data-relation': rel, 'aria-labelledby': 'rl-nb-card-h',
      onkeydown: (e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeCard(); } },
    },
    h('button', { type: 'button', class: 'rl-btn rl-nb-back', onclick: () => closeCard() }, '‹ Nations'),
    h('div', { class: 'rl-nb-cardhead' },
      flagOf(rv, r.nation, { height: 48 }),
      h('div', {},
        h('h3', { class: 'rl-nb-card-title', id: 'rl-nb-card-h', tabindex: '-1' }, r.nation.name),
        h('p', { class: 'rl-nb-relation' }, relMark(rel), ' ', RELATIONS[rel]))),
    figure, band, ways(r, rel, own),
    own && state.eco ? ownSheet(rv.economy, rv.map, { levers: rv.desk?.levers, act }) : null);
  };

  const draw = () => {
    const r = rows.find((x) => x.nation.key === state.open);
    root.replaceChildren(...(r ? [card(r)] : chart()).filter(Boolean));
  };

  function openCard(key) {
    state.open = key;
    state.eco = false;
    draw();
    root.querySelector('.rl-nb-card-title')?.focus();
  }

  function closeCard() {
    const key = state.open;
    state.open = null;
    state.eco = false;
    draw();
    findRow(root, key)?.focus();
  }

  draw();
  flags ??= loadFlagIndex();
  // the flags arrive once a page: redraw with them unless the seat is working in the panel
  flags.then(() => { if (root.isConnected && globalThis.document?.activeElement?.closest?.('.rl-nb') !== root) draw(); });
  return root;
}

/** The wars of each nation in `rv.wars`, by its key: the other side of each, as `{ key, name }`, in the list's order. */
export function warsOf(rv) {
  const by = new Map();
  const add = (k, other) => by.set(k, [...(by.get(k) ?? []), other]);
  for (const w of rv.wars ?? []) {
    if (!w?.a?.key || !w?.b?.key) continue;
    add(w.a.key, w.b);
    add(w.b.key, w.a);
  }
  return by;
}

/** The public pacts of each nation, by its name: a pact's wording, else its parties; only those the view marks public. */
export function pactsOf(rv) {
  const by = new Map();
  for (const a of rv.agreements?.agreements ?? []) {
    if (a?.published === null || a?.published === undefined || !a.parties?.length) continue;
    const name = String(a.wording ?? '').trim()
      || (a.parties.length > 1 ? `${a.parties.slice(0, -1).join(', ')} and ${a.parties.at(-1)}` : a.parties[0]);
    for (const party of new Set(a.parties)) by.set(party, [...(by.get(party) ?? []), name]);
  }
  return by;
}

/**
 * World's Standing part: `standingGrid(rv, { onOpen })`, one tile for each nation in the server's
 * order, `onOpen(key)` called when a tile is pressed. `null` with neither an economy nor a home block.
 */
export function standingGrid(rv, { onOpen = null } = {}) {
  const rows = nationRows(rv);
  if (!rows.length) return null;
  const wars = warsOf(rv);
  const pacts = pactsOf(rv);
  const known = new Map(rows.map((r) => [r.nation.key, relOf(r.nation)]));
  const tile = ({ nation }) => {
    const rel = relOf(nation);
    const foes = wars.get(nation.key) ?? [];
    const named = pacts.get(nation.name) ?? [];
    const label = [rel === 'own' ? `${nation.name} (yours)` : `${nation.name}, ${rel}`,
      foes.length ? `at war with ${foes.map((f) => f.name).join(', ')}` : null,
      named.length ? `pacts: ${named.join(', ')}` : null].filter(Boolean).join('. ');
    return h('li', {}, h('button', {
      type: 'button', class: `rl-sg-tile${rel === 'own' ? ' rl-nb-own' : ''}`, 'data-nation': nation.key, 'data-relation': rel,
      'aria-label': `${label}. Open its card`, onclick: () => onOpen?.(nation.key),
    },
    h('span', { class: 'rl-sg-head' },
      flagOf(rv, nation, { height: 32 }),
      h('span', { class: 'rl-sg-name' }, nation.name),
      h('span', { class: 'rl-sg-relline' }, relMark(rel), h('span', { class: 'rl-sg-relation' }, RELATIONS[rel]))),
    foes.length ? h('span', { class: 'rl-sg-wars' }, h('span', { class: 'rl-sg-tag' }, 'At war'),
      foes.map((f) => flagOf(rv, { ...f, relation: known.get(f.key) ?? 'neutral' }, { height: 16, alone: true }))) : null,
    named.length ? h('span', { class: 'rl-sg-pacts' }, named.map((n) => h('span', { class: 'rl-sg-pact' }, n))) : null));
  };
  return h('section', { class: 'rl-nb rl-sg', 'aria-label': 'Where each nation stands' },
    h('ul', { class: 'rl-sg-grid', role: 'list' }, rows.map(tile)));
}
