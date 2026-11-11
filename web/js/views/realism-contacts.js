// The Contacts tab of the messenger (Train 2 unit C2): everyone the seat can reach, and a
// contact's detail with what to do next.

import { h } from '../dom.js';
import { powersSentence } from '../realism-rules.js';
import { channelsLine, reachGroups } from './realism-reach.js';

const KEY_OF = { 'Inner circle': 'inner_circle', Government: 'government', Foreign: 'foreign', Other: 'other' };

/**
 * The four reach groups in order (`reachGroups`, realism-reach.js), empty ones dropped, as
 * `{ key, heading, rows }` with rows `{ name, title, how, can }`: `how` from `channelsLine`,
 * `can` 'message' for a name in `inner` (the inner circle's names) and 'order' otherwise.
 */
export function contactRows(reach, inner) {
  return reachGroups(reach).map((g) => ({
    key: KEY_OF[g.heading],
    heading: g.heading,
    rows: g.people.map((p) => ({
      name: p.name,
      title: p.title || null,
      how: channelsLine(p.channels) || null,
      can: (inner ?? []).includes(p.name) ? 'message' : 'order',
    })),
  }));
}

/** A contact's detail lines: `{ office, powers, how }`, `powers` as one sentence (`powersSentence`), null when empty. */
export function contactDetail(contact) {
  return {
    office: contact.title || null,
    powers: powersSentence(contact.powers ?? []) || null,
    how: channelsLine(contact.channels) || null,
  };
}

const ALL_GROUPS = ['inner_circle', 'government', 'foreign', 'other'];

function findContact(reach, name) {
  for (const key of ALL_GROUPS) {
    const hit = (reach?.[key] ?? []).find((c) => c.name === name);
    if (hit) return hit;
  }
  return null;
}

function rowButton(row, selected, onSelect) {
  return h('button', {
    type: 'button', class: 'rl-ct-row', 'aria-current': selected === row.name ? 'true' : null,
    onclick: () => onSelect?.(row.name),
  },
  h('span', { class: 'rl-ct-row-name' }, row.name),
  row.title ? h('span', { class: 'rl-ct-row-title' }, row.title) : null,
  row.how ? h('span', { class: 'rl-ct-row-how' }, row.how) : null);
}

function detailPane(contact, can, { onSelect, onMessage, onOrder }) {
  const d = contactDetail(contact);
  const act = can === 'message'
    ? h('button', { type: 'button', class: 'rl-ct-act', onclick: () => onMessage?.(contact.name) }, 'Message')
    : h('button', { type: 'button', class: 'rl-ct-act', onclick: () => onOrder?.(contact) }, 'Write them an order');
  return h('div', { class: 'rl-ct-detail' },
    h('button', { type: 'button', class: 'rl-ct-back', onclick: () => onSelect?.(null) }, 'Back'),
    h('h3', { class: 'rl-ct-name' }, contact.name),
    d.office ? h('p', { class: 'rl-ct-office' }, d.office) : null,
    d.powers ? h('p', { class: 'rl-ct-powers' }, d.powers) : null,
    d.how ? h('p', { class: 'rl-ct-how' }, d.how) : null,
    act);
}

/**
 * The tab: the groups of rows; a row opens `selected`'s detail via `onSelect(name)`, with
 * "Message" (`onMessage(name)`) for the inner circle or "Write them an order"
 * (`onOrder(contact)`) for anyone else.
 */
export function contactsTab(reach, { inner, selected, onSelect, onMessage, onOrder }) {
  const groups = contactRows(reach, inner);
  const section = (...children) => h('section', { class: 'rl-ct', 'aria-labelledby': 'rl-ct-title' },
    h('h2', { id: 'rl-ct-title' }, 'Contacts'), ...children);
  if (!groups.length) return section(h('p', { class: 'rl-ct-empty' }, 'No one is within reach.'));

  const picked = selected ? findContact(reach, selected) : null;
  if (picked) {
    const can = (inner ?? []).includes(picked.name) ? 'message' : 'order';
    return section(detailPane(picked, can, { onSelect, onMessage, onOrder }));
  }
  return section(...groups.map((g) => {
    const id = `rl-ct-${g.key}`;
    return h('section', { class: 'rl-ct-group', 'aria-labelledby': id },
      h('h3', { id }, g.heading),
      h('ul', { class: 'rl-ct-rows' }, g.rows.map((r) => h('li', {}, rowButton(r, selected, onSelect)))));
  }));
}
