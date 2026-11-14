// The in-tray as a message list with a reading pane (In-Tray follow-up, unit T1).

import { h } from '../dom.js';
import { TRAY_FILTERS, filterInTray, sortInTray, trayCounts } from '../realism-rules.js';
import { worldDate } from '../rules.js';
import { panelHead, tag } from './ui-kit.js';
import { dossier } from './realism.js';

const KIND_TAG = Object.freeze({
  cable: ['cable', 'info'], intercept: ['intercept', 'intel'], press: ['press', 'warn'],
  fleet: ['order', 'ok'], route: ['order', 'ok'],
});

/** Fold same-group papers into one row at the place of the group's newest paper. Does not mutate `items`. */
export function trayRows(items) {
  const groups = new Map();
  items.forEach((item, i) => {
    if (item.group == null) return;
    const g = groups.get(item.group) || { items: [], at: i };
    g.items.push(item);
    if (item.arrives > items[g.at].arrives) g.at = i;
    groups.set(item.group, g);
  });
  const rows = [];
  items.forEach((item, i) => {
    if (item.group == null) { rows.push({ type: 'paper', item }); return; }
    const g = groups.get(item.group);
    if (g.at !== i) return;
    rows.push({
      type: 'group', group: item.group, count: g.items.length,
      unread: g.items.filter((d) => d.unread).length, latest: item, items: g.items.slice(),
    });
  });
  return rows;
}

export function rowLabel(row) {
  if (row.type === 'group') return `${row.group} (${row.count} ${row.count === 1 ? 'paper' : 'papers'})`;
  return `${row.item.author} — ${row.item.title}`;
}

function tabBar(filter, counts, onFilter) {
  return TRAY_FILTERS.map(([key, word]) => h('button', {
    type: 'button', role: 'tab', id: `rl-filter-${key}`, 'aria-selected': String(filter === key),
    'aria-controls': 'rl-folders', tabindex: filter === key ? 0 : -1, class: 'rl-filter',
    onclick: () => onFilter?.(key),
    onkeydown: (e) => {
      const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (!step) return;
      e.preventDefault();
      const last = TRAY_FILTERS.length - 1;
      let to = TRAY_FILTERS.findIndex(([k]) => k === key) + step;
      if (to < 0) to = last;
      if (to > last) to = 0;
      onFilter?.(TRAY_FILTERS[to][0], true);
    },
  }, word, h('span', { class: 'rl-count n' }, ` ${counts[key]}`)));
}

function moveFocus(e) {
  const step = e.key === 'ArrowDown' ? 1 : e.key === 'ArrowUp' ? -1 : 0;
  if (!step) return;
  e.preventDefault();
  const rows = [...e.currentTarget.closest('.rl-mail-list').querySelectorAll('.rl-row')]
    .filter((r) => !r.closest('[hidden]'));
  rows[rows.indexOf(e.currentTarget) + step]?.focus();
}

function paperRow(item, onOpen, open, nested) {
  const [word, tone] = KIND_TAG[item.kind] ?? ['report', 'quiet'];
  return h('button', {
    type: 'button', role: 'option', class: `rl-row rl-row-paper${item.unread ? ' unread' : ''}${nested ? ' rl-row-nested' : ''}`,
    'aria-selected': String(open?.id === item.id), onclick: () => onOpen?.(item), onkeydown: moveFocus,
  },
  h('span', { class: 'rl-row-main' },
    h('span', { class: 'rl-row-from' }, item.author),
    h('span', { class: 'rl-row-title' }, item.title)),
  tag(word, tone),
  item.unread ? h('span', { class: 'rl-row-unread' }, 'Unread') : null,
  h('span', { class: 'rl-row-date' }, worldDate(item.arrives)),
  item.flagged ? h('span', { class: 'rl-flag', title: 'Flagged' }, 'Flagged') : null);
}

function groupRow(row, onOpen, open) {
  const holds = open && row.items.some((d) => d.id === open.id);
  const kids = h('div', { class: 'rl-group-papers', role: 'presentation', hidden: !holds },
    row.items.map((d) => paperRow(d, onOpen, open, true)));
  const head = h('button', {
    type: 'button', class: 'rl-row rl-row-group', 'aria-expanded': String(!!holds), onkeydown: moveFocus,
    onclick: () => {
      const on = head.getAttribute('aria-expanded') !== 'true';
      head.setAttribute('aria-expanded', String(on));
      kids.hidden = !on;
    },
  },
  h('span', { class: row.unread ? 'rl-dot rl-dot-on' : 'rl-dot' }),
  h('span', { class: 'rl-row-main' }, h('span', { class: 'rl-row-title' }, rowLabel(row))),
  h('span', { class: 'rl-row-date' }, worldDate(row.latest.arrives)),
  row.unread ? h('span', { class: 'rl-row-unread' }, `${row.unread} unread`) : null);
  return h('li', { class: 'rl-group', role: 'presentation' }, head, kids);
}

const TRAY_SECTIONS = Object.freeze([
  ['answers', 'Answers to your orders'], ['press', 'Press'], ['reports', 'Reports'],
]);

/**
 * The tray's sections, in this order and empty ones dropped: `answers` (`answer` true), `press`
 * (kind press), `reports` (everything else). Acknowledgements are in no section. Each
 * `{ key, heading, rows }`, rows folded by `trayRows`.
 */
export function traySections(items) {
  const bins = { answers: [], press: [], reports: [] };
  for (const d of items) {
    if (d.ack) continue;
    if (d.answer) bins.answers.push(d);
    else if (d.kind === 'press') bins.press.push(d);
    else bins.reports.push(d);
  }
  return TRAY_SECTIONS.filter(([key]) => bins[key].length)
    .map(([key, heading]) => ({ key, heading, rows: trayRows(bins[key]) }));
}

function rowNodes(rows, onOpen, open) {
  return rows.map((r) => (r.type === 'group'
    ? groupRow(r, onOpen, open)
    : h('li', { role: 'presentation' }, paperRow(r.item, onOpen, open, false))));
}

function sectionList(section, onOpen, open) {
  const id = `rl-tray-${section.key}-h`;
  return h('div', { class: 'rl-tray-section' },
    h('h3', { id, class: 'rl-tray-head' }, section.heading),
    h('ul', { class: 'rl-rows', role: 'listbox', 'aria-labelledby': id }, rowNodes(section.rows, onOpen, open)));
}

/**
 * The tray panel. `opts`: { filter, sort, onFilter, onSort, page, onClose, onFlag, wide }.
 * The press is not In-Tray: its pages are on the newspaper desk, so the tray neither lists nor counts them.
 */
export function trayView(listing, onOpen, opts = {}) {
  const { filter = 'all', sort = 'newest', onFilter, onSort, page } = opts;
  const papers = listing.documents.filter((d) => d.kind !== 'press');
  const counts = trayCounts(papers);
  const open = page?.item;
  const sorted = sortInTray(filterInTray(papers, filter), sort);
  const lists = filter === 'all'
    ? traySections(sorted).map((s) => sectionList(s, onOpen, open))
    : sorted.length
      ? [h('ul', { class: 'rl-rows', role: 'listbox', 'aria-label': 'Papers' }, rowNodes(trayRows(sorted), onOpen, open))]
      : [];
  return h('section', { class: 'rl-tray panel', 'aria-label': 'In-tray' },
    panelHead('In-tray', counts.unread, [
      h('label', { class: 'rl-sort' }, 'Sort ',
        h('select', { name: 'sort', onchange: (e) => onSort?.(e.target.value) },
          h('option', { value: 'newest', selected: sort === 'newest' }, 'Newest first'),
          h('option', { value: 'oldest', selected: sort === 'oldest' }, 'Oldest first'))),
    ]),
    h('div', { class: 'rl-tray-body' },
      h('div', { role: 'tablist', 'aria-label': 'Show papers', class: 'seg' }, tabBar(filter, counts, onFilter)),
      h('div', { role: 'tabpanel', id: 'rl-folders', 'aria-labelledby': `rl-filter-${filter}` },
        h('div', { class: `rl-mail${page ? ' rl-mail-open' : ''}` },
          h('div', { class: 'rl-mail-list' },
            lists.length ? lists : h('p', { class: 'rl-none' }, 'Nothing in this tray.')),
          h('div', { class: 'rl-mail-pane' },
            page
              ? dossier(page, { onClose: opts.onClose, onFlag: opts.onFlag })
              : h('p', { class: 'rl-none' }, 'Choose a paper to read it here.'))))));
}
