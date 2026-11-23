// The map-first room's sheets in four groups: Inbox, Orders, People and World, each one sheet
// with its parts as inner tabs, and Messages as a chat button on the bar. A part is one of the
// room's sheets as realism-room.js builds it; this file holds which group a part is in, the
// bar's group tabs, a sheet's part tabs, the chat button, the Write part's search over the
// standing forms, and the forms that take a picked piece. Nothing here touches the page on import.

import { h, icon } from '../dom.js';

/** The four groups, in tab order, each with its parts as [sheet key, label] [proposed]. */
export const GROUPS = Object.freeze([
  { key: 'inbox', label: 'Inbox', parts: [['papers', 'Papers'], ['press', 'Press']] },
  { key: 'orders', label: 'Orders', parts: [['forms', 'Write'], ['orders', 'Sent']] },
  { key: 'people', label: 'People', parts: [['people', 'Roster'], ['court', 'Court']] },
  { key: 'world', label: 'World', parts: [['nations', 'Nations'], ['standing', 'Standing'], ['home', 'Home'], ['diplomacy', 'Diplomacy']] },
].map((g) => Object.freeze({ ...g, parts: Object.freeze(g.parts) })));

/** The group sheet `part` is in, or null for a sheet of no group (a piece, a matter, the messenger). */
export function groupOf(part) {
  return GROUPS.find((g) => g.parts.some(([key]) => key === part)) ?? null;
}

/** A group's count: the sum of the counts of its parts that are drawn (`drawn`, the part keys). */
export function groupCount(group, counts, drawn) {
  return group.parts.filter(([key]) => drawn.includes(key)).reduce((sum, [key]) => sum + (Number(counts?.[key]) || 0), 0);
}

/** The part a group opens on: `last`, the part last open in it, while it is drawn; else its first drawn part. */
export function partFor(group, last, drawn) {
  return drawn.includes(last) && groupOf(last) === group ? last : group.parts.map(([key]) => key).find((k) => drawn.includes(k)) ?? null;
}

const badge = (n) => (n > 0 ? [' ', h('span', { class: 'badge tone-warn rl-tab-count' }, String(n))] : null);

/**
 * The bar's group tabs: one button per group with a drawn part, with the group's count; the
 * group of the open part is expanded. `drawn` is the part keys drawn; a press calls `onGroup(key)`.
 */
export function groupTabs(open, counts, onGroup, drawn) {
  const at = groupOf(open);
  return h('nav', { class: 'rl-sheettabs', 'aria-label': 'Sheets' },
    GROUPS.filter((g) => g.parts.some(([key]) => drawn.includes(key))).map((g) => h('button', {
      type: 'button', class: 'rl-sheettab', 'data-group': g.key, 'aria-expanded': String(at === g),
      'aria-controls': at === g ? 'rl-over' : null, onclick: () => onGroup(g.key),
    }, g.label, badge(groupCount(g, counts, drawn)))));
}

/** A group's sheet's inner tabs: one button per drawn part, the open one pressed; a press calls `onPart(key)`. */
export function partTabs(open, counts, onPart, drawn) {
  const group = groupOf(open);
  if (!group) return null;
  return h('div', { class: 'rl-parts seg', role: 'group', 'aria-label': `${group.label}: its parts` },
    group.parts.filter(([key]) => drawn.includes(key)).map(([key, label]) => h('button', {
      type: 'button', class: 'rl-part', 'data-sheet': key, 'aria-pressed': String(key === open), onclick: () => onPart(key),
    }, label, badge(Number(counts?.[key]) || 0))));
}

/** The bar's chat button: the messenger, with the unread count on its badge and in its name. */
export function chatButton(open, unread, onOpen) {
  const n = Number(unread) || 0;
  return h('button', {
    type: 'button', class: 'rl-btn rl-chat-btn', 'data-sheet': 'messages', 'aria-expanded': String(Boolean(open)),
    'aria-controls': open ? 'rl-over' : null, 'aria-label': n > 0 ? `Messages, ${n} unread` : 'Messages', onclick: onOpen,
  }, icon('chat', 16), n > 0 ? h('span', { class: 'badge tone-warn rl-tab-count', 'aria-hidden': 'true' }, String(n)) : null);
}

const folded = (s) => String(s ?? '').trim().toLowerCase();

/** The names of the forms in `levers` whose name or label holds `query`, in their order; an empty query matches every form. */
export function matchForms(levers, query) {
  const q = folded(query);
  return new Set((levers ?? []).filter((l) => !q || folded(l.label).includes(q) || folded(l.name).includes(q)).map((l) => l.name));
}

/**
 * The Write part's search over the standing forms in `forms` (the `.rl-forms` block): a search
 * field that hides every form whose name does not hold the words typed, and a line when none
 * does. `query` is what was typed before a redraw; `onQuery(text)` is told each change.
 */
export function formSearch(forms, levers, query, onQuery) {
  if (!forms) return null;
  const none = h('p', { class: 'muted rl-formfind-none', hidden: true }, 'No form is called that.');
  const apply = (text) => {
    const keep = matchForms(levers, text);
    let shown = 0;
    for (const item of [...forms.querySelectorAll('.rl-instrument')]) {
      const on = keep.has(item.getAttribute('data-lever'));
      item.hidden = !on;
      shown += on ? 1 : 0;
    }
    none.hidden = shown > 0;
  };
  const field = h('input', {
    type: 'search', class: 'rl-formfind-field', 'aria-label': 'Find a form by name', placeholder: 'Search the standing forms', value: query ?? '',
    oninput: (e) => { apply(e.target.value); onQuery?.(e.target.value); },
  });
  apply(query ?? '');
  return h('section', { class: 'rl-formfind', 'aria-labelledby': 'rl-formfind-h' },
    h('h3', { id: 'rl-formfind-h' }, 'Find a form'), field, none, forms);
}

const nameOf = (label) => label.replace(/^The /, '');

/**
 * The forms in `levers` that take the seat's own piece `mark` by name (an enum field named
 * `force` or `piece` with a choice for it), as `{ lever, param, value }`; `skip` holds the forms
 * already shown (the ones that move it).
 */
export function formsTaking(levers, mark, skip = new Set()) {
  if (mark?.side !== 'own') return [];
  const named = (c) => mark.name === nameOf(c.label) || mark.name.endsWith(` ${nameOf(c.label)}`);
  const out = [];
  for (const lever of levers ?? []) {
    if (skip.has(lever.name)) continue;
    for (const param of lever.params ?? []) {
      if (param.kind !== 'enum' || !['force', 'piece'].includes(param.name)) continue;
      const choice = param.choices.find((c) => c.label === mark.name) ?? param.choices.find(named);
      if (!choice) continue;
      out.push({ lever, param: param.name, value: choice.value });
      break;
    }
  }
  return out;
}

/**
 * A person's moves on their card: "Ask a question" where a channel reaches them (`onAsk`), and
 * "Write an order" where an order can go to them (`onWrite`); with neither, a line saying so.
 */
export function personMoves(contact, { onAsk, onWrite } = {}) {
  const ask = (contact?.channels ?? []).length > 0;
  const write = (contact?.channel_keys ?? []).length > 0;
  return h('div', { class: 'rl-person-moves' },
    ask ? h('button', { type: 'button', class: 'rl-btn', onclick: () => onAsk?.(contact) }, 'Ask a question') : null,
    write ? h('button', { type: 'button', class: 'rl-btn', onclick: () => onWrite?.(contact) }, 'Write an order') : null,
    ask || write ? null : h('p', { class: 'muted' }, 'You cannot reach them from here.'));
}
