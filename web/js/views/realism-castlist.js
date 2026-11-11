// Everyone else who held power on the start date (Train 3 unit P2): side chips, one table,
// and the Find someone search. A row opens the short dossier; a name not on the list can
// be drawn up. The search and list rules below it (figureGroups, alreadyPlayed,
// searchState) came over from realism-cast.js unchanged.

import { h, reply } from '../dom.js';

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
 */
export function sideChips(groups) {
  const bySide = new Map();
  for (const g of groups) bySide.set(g.side, (bySide.get(g.side) ?? 0) + g.figures.length);
  const total = [...bySide.values()].reduce((sum, n) => sum + n, 0);
  if (!total) return [];
  const sides = [...bySide.keys()].sort((a, b) => a.localeCompare(b));
  return [
    { side: null, label: 'All', count: total },
    ...sides.map((side) => ({ side, label: side, count: bySide.get(side) })),
  ];
}

/**
 * The table rows: `figureGroups(groups, cast)` (cast: the names already in the cast), kept to
 * `side` unless it is null, flattened in group order to `{ name, title, side, power }`.
 * A missing title is null.
 */
export function tableRows(groups, { side = null, cast = [] } = {}) {
  return figureGroups(groups, cast)
    .filter((g) => side === null || g.side === side)
    .flatMap((g) => g.figures.map((f) => ({ name: f.name, title: f.title ?? null, side: g.side, power: g.power })));
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
 */
export function castList({ cast = [], load, onOpen, onDraw, wait = 300 } = {}) {
  let groups = [];
  let query = '';
  let side = null;
  let loading = false;
  let notice = null;
  let seq = 0;
  let timer = null;

  const input = h('input', {
    id: 'rl-cl-search',
    type: 'search',
    maxlength: 400,
    autocomplete: 'off',
    oninput: () => {
      clearTimeout(timer);
      timer = setTimeout(() => run(input.value.trim()), wait);
    },
  });
  const chips = h('div', { class: 'rl-cl-chips', role: 'tablist', 'aria-label': 'Side' });
  const body = h('tbody');
  const status = h('div', { class: 'rl-cl-status', role: 'status' });

  const chipNode = (c) => h('button', {
    type: 'button',
    class: 'rl-cl-chip',
    role: 'tab',
    'aria-selected': String(c.side === side),
    onclick: () => {
      side = c.side;
      render();
    },
  }, `${c.label} (${c.count})`);

  const rowNode = (row) => h('tr', {},
    h('td', {}, h('button', { type: 'button', class: 'rl-cl-name', onclick: () => onOpen(row) }, row.name)),
    h('td', { class: 'rl-cl-title' }, row.title),
    h('td', { class: 'rl-cl-side' }, row.side),
    h('td', { class: 'rl-cl-power' }, row.power));

  function statusNodes(rows) {
    if (notice) return [notice];
    const state = searchState({ loading, shown: rows, query, taken: alreadyPlayed(groups, cast) });
    if (state.kind === 'list') return [];
    const nodes = [h('p', {}, state.text)];
    if (state.kind === 'none') {
      nodes.push(
        h('p', { class: 'hint' }, 'A person not on the list takes about a minute, and the record may not place them.'),
        h('button', { type: 'button', class: 'rl-cl-draw', onclick: () => onDraw(query) }, state.offer));
    }
    return nodes;
  }

  function render() {
    chips.replaceChildren(...sideChips(figureGroups(groups, cast)).map(chipNode));
    const rows = tableRows(groups, { side, cast });
    body.replaceChildren(...rows.map(rowNode));
    status.replaceChildren(...statusNodes(rows));
  }

  function run(q) {
    query = q;
    const n = ++seq;
    loading = true;
    notice = null;
    render();
    Promise.resolve()
      .then(() => load(q))
      .then((r) => {
        if (n !== seq) return;
        loading = false;
        if (r?.refused) {
          groups = [];
          notice = reply(r.reply ?? '');
        } else {
          groups = r?.figures ?? [];
        }
        if (side && !figureGroups(groups, cast).some((g) => g.side === side)) side = null;
        render();
      }, (ex) => {
        if (n !== seq) return;
        loading = false;
        groups = [];
        notice = h('p', { class: 'form-error' }, ex?.message ?? String(ex));
        render();
      });
  }

  run('');

  return h('section', { class: 'rl-cl', 'aria-labelledby': 'rl-cl-title' },
    h('h2', { id: 'rl-cl-title' }, 'Who held power'),
    h('p', { class: 'rl-cl-lead' }, 'Anyone listed here can be played. Open a name to read them first.'),
    h('label', { class: 'rl-cl-search-label', for: 'rl-cl-search' }, 'Find someone'),
    input,
    chips,
    h('table', { class: 'rl-cl-table' },
      h('thead', {}, h('tr', {},
        h('th', { scope: 'col' }, 'Name'),
        h('th', { scope: 'col' }, 'Title'),
        h('th', { scope: 'col', class: 'rl-cl-side' }, 'Side'),
        h('th', { scope: 'col', class: 'rl-cl-power' }, 'Kind of power'))),
      body),
    status);
}
