// The Contacts tab of the messenger (Train 2 unit C2): everyone the seat can reach, and a
// contact's detail with what to do next.

import { h } from '../dom.js';
import { powersSentence } from '../realism-rules.js';
import { channelsLine, reachGroups } from './realism-reach.js';

const NOTE = 'A message changes nothing in the world and files no order.';
const KEY_OF = { 'Inner circle': 'inner_circle', Government: 'government', Foreign: 'foreign', Other: 'other' };

/** What the seat may do with a contact: `{ message, order }`, from its channels and channel keys. */
function canOf(contact) {
  return {
    message: (contact.channels ?? []).length > 0,
    order: (contact.channel_keys ?? []).length > 0,
  };
}

/**
 * The four reach groups in order (`reachGroups`, realism-reach.js), empty ones dropped, as
 * `{ key, heading, rows }` with rows `{ name, title, how, can }`: `how` from `channelsLine`,
 * `can` from `canOf`.
 */
export function contactRows(reach) {
  return reachGroups(reach).map((g) => ({
    key: KEY_OF[g.heading],
    heading: g.heading,
    rows: g.people.map((p) => ({
      name: p.name,
      title: p.title || null,
      how: channelsLine(p.channels) || null,
      can: canOf(p),
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

function detailPane(contact, { inner, onSelect, onMessage, onOrder }) {
  const d = contactDetail(contact);
  const can = canOf(contact);
  const acts = h('div', { class: 'rl-ct-acts' },
    can.message ? h('button', { type: 'button', class: 'rl-ct-act', onclick: () => onMessage?.(contact.name) }, 'Message') : null,
    can.order ? h('button', { type: 'button', class: 'rl-ct-act', onclick: () => onOrder?.(contact) }, 'Write them an order') : null);
  return h('div', { class: 'rl-ct-detail' },
    h('button', { type: 'button', class: 'rl-ct-back', onclick: () => onSelect?.(null) }, 'Back'),
    h('h3', { class: 'rl-ct-name' }, contact.name),
    d.office ? h('p', { class: 'rl-ct-office' }, d.office) : null,
    d.powers ? h('p', { class: 'rl-ct-powers' }, d.powers) : null,
    d.how ? h('p', { class: 'rl-ct-how' }, d.how) : null,
    acts,
    (inner ?? []).includes(contact.name) ? null : h('p', { class: 'rl-ct-note' }, NOTE));
}

/**
 * The tab, headed "New message": the groups of rows; a row opens `selected`'s detail via
 * `onSelect(name)`, with "Message" (`onMessage(name)`) and "Write them an order"
 * (`onOrder(contact)`) where the seat can do them. `inner` names the inner circle, for whom a
 * message needs no note.
 */
export function contactsTab(reach, { inner, selected, onSelect, onMessage, onOrder }) {
  const groups = contactRows(reach);
  const section = (...children) => h('section', { class: 'rl-ct', 'aria-labelledby': 'rl-ct-title' },
    h('h2', { id: 'rl-ct-title' }, 'New message'), ...children);
  if (!groups.length) return section(h('p', { class: 'rl-ct-empty' }, 'No one is within reach.'));

  const picked = selected ? findContact(reach, selected) : null;
  if (picked) return section(detailPane(picked, { inner, onSelect, onMessage, onOrder }));
  return section(...groups.map((g) => {
    const id = `rl-ct-${g.key}`;
    return h('section', { class: 'rl-ct-group', 'aria-labelledby': id },
      h('h3', { id }, g.heading),
      h('ul', { class: 'rl-ct-rows' }, g.rows.map((r) => h('li', {}, rowButton(r, selected, onSelect)))));
  }));
}
