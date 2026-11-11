// Everyone else who held power on the start date (Train 3 unit P2): side chips, one table,
// and the Find someone search. A row opens the short dossier; a name not on the list can
// be drawn up. The search and list rules below it (figureGroups, alreadyPlayed,
// searchState) came over from realism-cast.js unchanged.

import { h } from '../dom.js';

/** The generated list without anyone already in the cast, by side then kind of power. */
export function figureGroups(groups, castNames) {
  const cast = new Set(castNames.map((n) => n.toLowerCase()));
  return groups
    .map((g) => ({ ...g, figures: g.figures.filter((f) => !cast.has(f.name.toLowerCase())) }))
    .filter((g) => g.figures.length)
    .sort((a, b) => a.side.localeCompare(b.side) || a.power.localeCompare(b.power));
}

/** Names on the generated list that are already in the cast. */
export function alreadyPlayed(groups, castNames) {
  const cast = new Set(castNames.map((n) => n.toLowerCase()));
  return groups.flatMap((g) => g.figures).map((f) => f.name).filter((n) => cast.has(n.toLowerCase()));
}

/**
 * What the Find someone box shows: a loading line, the list, or a line saying why it is empty.
 * `taken` names matches hidden because they are already played; the query then names them,
 * not someone new, so no draw is offered.
 */
export function searchState({ loading, shown, query, taken = [] }) {
  if (loading) return { kind: 'loading', text: 'Searching…' };
  if (shown.length) return { kind: 'list' };
  const q = query.trim();
  if (q && taken.length) {
    const who = taken.length === 1 ? `${taken[0]} matches` : `${taken.slice(0, -1).join(', ')} and ${taken.at(-1)} match`;
    return { kind: 'taken', text: `Only ${who} “${q}”, and they are already played.` };
  }
  if (q) return { kind: 'none', text: `No one on the list matches “${q}”.`, offer: `Draw up ${q}` };
  return { kind: 'empty', text: 'No one is listed for this date.' };
}

/**
 * The side chips over `groups` (the `figures` reply: [{side, power, figures: [{name, title}]}],
 * already passed through `figureGroups`): first `{ side: null, label: 'All', count }` with the
 * count of every figure, then one `{ side, label: side, count }` per side, sides in
 * alphabetical order, a side's count summed across its groups. No groups gives `[]`.
 * contract stub
 */
export function sideChips(groups) {
  return [];
}

/**
 * The table rows: `figureGroups(groups, cast)` (cast: the names already in the cast), kept to
 * `side` unless it is null, flattened in group order to `{ name, title, side, power }`.
 * A missing title is null.
 * contract stub
 */
export function tableRows(groups, { side = null, cast = [] } = {}) {
  return [];
}

/**
 * `<section class="rl-cl" aria-labelledby="rl-cl-title">` with the h2 "Who held power", a
 * line saying anyone listed can be played, the search field (label "Find someone",
 * `input#rl-cl-search[type=search]`), the chips as a `role="tablist"` of
 * `button[role=tab][aria-selected]` reading "<label> (<count>)", one `table.rl-cl-table`
 * (columns Name, Title, Side, Kind of power; each row a button named "<name>" in the first
 * cell that calls `onOpen(row)`), and a `role="status"` line with `searchState`'s text.
 * Typing waits `wait` ms after the last key, then calls `load(query)`; `load` resolves to
 * the `figures` reply (`{ figures }`, or `{ refused, reply }`); a reply that is not the
 * latest is dropped. On the "none" state a button with the state's `offer` calls
 * `onDraw(query)`, with the line that a person not on the list takes about a minute.
 * Chip choice and search survive inside the section; the section is built once.
 * contract stub
 */
export function castList({ cast = [], load, onOpen, onDraw, wait = 300 } = {}) {
  return h('section', { class: 'rl-cl', 'aria-labelledby': 'rl-cl-title' },
    h('h2', { id: 'rl-cl-title' }, 'Who held power'));
}
