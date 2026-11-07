// Acknowledgements in the conversation with their author (In-Tray follow-up, unit T2).

import { h } from '../dom.js';
import { worldDate } from '../rules.js';

/** The papers in `listing` that acknowledge an order and come from `person`, newest first. */
export function ackLines(listing, person) {
  return listing.documents
    .filter((d) => d.ack === true && d.author === person)
    .sort((a, b) => (a.arrives < b.arrives ? 1 : a.arrives > b.arrives ? -1 : a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
    .map((d) => ({
      id: d.id,
      title: d.title.replace(/^On your order: /, ''),
      day: worldDate(d.arrives),
      unread: Boolean(d.unread),
    }));
}

/** The acknowledgement lines for the open conversation with `person`, or null when there are none. */
export function ackThread(listing, person, onOpen) {
  const lines = ackLines(listing, person);
  if (!lines.length) return null;
  return h('section', { class: 'rl-acks', 'aria-labelledby': 'rl-acks-h' },
    h('h3', { id: 'rl-acks-h' }, 'Acknowledgements'),
    h('ul', { class: 'rl-acks-list' }, lines.map((l) => h('li', null,
      h('button', { type: 'button', class: 'rl-ack', onclick: () => onOpen({ id: l.id }) },
        l.unread ? h('span', { class: 'rl-ack-dot', 'aria-hidden': 'true' }) : null,
        l.unread ? h('span', { class: 'sr-only' }, 'Unread: ') : null,
        `${l.title} — ${l.day}`)))));
}
