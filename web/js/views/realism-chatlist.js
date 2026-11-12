// The Chats tab: one row per conversation, the aide first, then the newest activity.

import { h } from '../dom.js';

const CUT = 60;

/**
 * `chatRows({ threads, reach, record, seen })`: rows `{ key, name, initials, title, preview,
 * day, unread, holds }`. `threads` maps 'aide' and each contact's name to its `threadItems`.
 */
export function chatRows({ threads, reach, record, seen }) {
  const contacts = Object.entries(threads ?? {})
    .filter(([key, items]) => key !== 'aide' && items?.length)
    .sort(([ka, ia], [kb, ib]) => lastIso(ib).localeCompare(lastIso(ia)) || ka.localeCompare(kb));
  return [
    rowFor('aide', threads?.aide ?? [], { reach, record, seen }),
    ...contacts.map(([key, items]) => rowFor(key, items, { reach, record, seen })),
  ];
}

const lastIso = (items) => items[items.length - 1]?.iso ?? '';

function rowFor(key, items, { reach, record, seen }) {
  const last = items[items.length - 1] ?? null;
  const theirs = items.filter((i) => i.side === 'theirs').length;
  const aide = key === 'aide';
  return {
    key,
    name: aide ? 'Your aide' : key,
    initials: initials(aide ? 'Your aide' : key),
    title: aide ? null : titleOf(reach, key),
    preview: last ? preview(last) : null,
    day: last?.day ?? null,
    unread: Math.max(0, theirs - (seen?.[key] ?? 0)),
    holds: aide ? null : holdOf(record, key),
  };
}

function initials(name) {
  const parts = name.split(/\s+/).filter(Boolean);
  const first = parts[0]?.[0] ?? '?';
  const last = parts.length > 1 ? parts[parts.length - 1][0] : '';
  return (first + last).toUpperCase();
}

const GROUPS = ['inner_circle', 'government', 'foreign', 'other'];

function titleOf(reach, name) {
  for (const group of GROUPS) {
    const hit = (reach?.[group] ?? []).find((c) => c.name === name);
    if (hit) return hit.title ?? null;
  }
  return null;
}

/** The last line, with "You: " before the player's own, cut to 60 characters. */
function preview(item) {
  const line = item.side === 'mine' ? `You: ${item.text}` : item.text;
  return line.length > CUT ? `${line.slice(0, CUT - 1)}…` : line;
}

function holdOf(record, name) {
  const order = (record?.orders ?? []).find((o) => o.moving && o.holder === name);
  return order ? `Has your order: ${order.asked}` : null;
}

/** `chatList({ rows, onOpen })`: the rows as buttons, `onOpen(key)` on a click. */
export function chatList({ rows, onOpen }) {
  return h('div', { class: 'rl-cl' },
    rows.every((r) => r.key === 'aide')
      ? h('p', { class: 'rl-cl-empty' }, 'No conversations yet. Start one from Contacts.')
      : null,
    h('ul', { class: 'rl-cl-list' }, rows.map((row) => h('li', {},
      h('button', { type: 'button', class: 'rl-cl-row', onclick: () => onOpen(row.key) },
        h('span', { class: 'rl-cl-avatar', 'aria-hidden': 'true' }, row.initials),
        h('span', { class: 'rl-cl-main' },
          h('span', { class: 'rl-cl-name' },
            row.unread > 0 ? h('span', { class: 'sr-only' }, 'New: ') : null,
            row.name),
          row.preview !== null ? h('span', { class: 'rl-cl-preview' }, row.preview) : null,
          row.holds ? h('span', { class: 'rl-cl-holds' }, row.holds) : null),
        h('span', { class: 'rl-cl-meta' },
          row.day ? h('span', { class: 'rl-cl-day' }, row.day) : null,
          row.unread > 0 ? h('span', { class: 'rl-cl-dot', 'aria-hidden': 'true' }) : null))))));
}
