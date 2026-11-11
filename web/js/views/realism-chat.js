// The messenger (Train 2 unit C1): a fixed "Messages" button with the unread count, and a
// panel with Chats (your aide, then each inner-circle person) and Contacts.

import { h } from '../dom.js';
import { counselThread, helpThread } from './realism.js';

export const SEEN_PREFIX = 'rv.chat.seen.';

/** `{ total, fresh }`: lines newer than `seen` summed over every key, and the keys that have them. */
export function unread(counts, seen) {
  const fresh = [];
  let total = 0;
  for (const [key, n] of Object.entries(counts)) {
    const newer = n - (seen?.[key] ?? 0);
    if (newer > 0) {
      total += newer;
      fresh.push(key);
    }
  }
  return { total, fresh };
}

/**
 * The lines seen per thread, kept under `rv.chat.seen.<campaignId>`: `{ read(), write(seen) }`.
 * `read()` gives `{}` for a missing or broken value; with no storage both do nothing.
 */
export function seenStore(storage, campaignId) {
  const key = `${SEEN_PREFIX}${campaignId}`;
  return {
    read() {
      try {
        const value = JSON.parse(storage?.getItem(key) ?? 'null');
        return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
      } catch {
        return {};
      }
    },
    write(seen) {
      try {
        storage?.setItem(key, JSON.stringify(seen));
      } catch {
        // a browser that blocks storage keeps no marks; the dock still works
      }
    },
  };
}

/**
 * The dock. `opts`: `{ state, onState(next), counts, seen, contacts, counsel, help, brief,
 * ask(text), consult(person, text), useDraft(d), ackThread(person), contactsTab }`.
 * `state` is `{ open, tab: 'chats' | 'contacts', thread: null | 'aide' | name }`, kept by the
 * room. Chats lists "Your aide" then each of `contacts` (desk.inner_circle) with a dot when
 * fresh; a thread shows its lines as `bubble`s newest last (`helpThread`, `counselThread`,
 * realism.js), the aide's opening with `brief` (a node), and a composer at the foot.
 * Opening a thread calls `onState` with it; the room marks it seen. Esc and the button close it.
 */
export function chatDock(opts) {
  const { state, onState, counts, seen } = opts;
  const { total, fresh } = unread(counts, seen);
  const close = () => onState({ ...state, open: false });
  const escape = (e) => { if (e.key === 'Escape') close(); };

  return h('div', { class: 'rl-msgr' },
    h('button', {
      type: 'button',
      class: 'rl-msgr-btn',
      'aria-expanded': String(state.open),
      onclick: () => onState({ ...state, open: !state.open }),
      onkeydown: state.open ? escape : null,
    }, 'Messages', total > 0 ? h('span', { class: 'rl-msgr-count' }, String(total), h('span', { class: 'sr-only' }, ' unread')) : null),
    state.open ? panel(opts, fresh, escape) : null);
}

function panel(opts, fresh, escape) {
  const { state, onState, contacts = [] } = opts;
  const tab = (key, label) => h('button', {
    type: 'button',
    role: 'tab',
    class: 'rl-msgr-tab',
    'aria-selected': String(state.tab === key),
    onclick: () => onState({ ...state, tab: key }),
  }, label);

  let body;
  if (state.tab === 'contacts') body = h('div', { class: 'rl-msgr-body' }, opts.contactsTab ?? null);
  else if (state.thread) body = thread(opts);
  else {
    body = h('ol', { class: 'rl-msgr-list', role: 'list' },
      h('li', null, listItem(opts, 'aide', 'Your aide', null, fresh.includes('aide'))),
      contacts.map((c) => h('li', null, listItem(opts, c.person, c.person, c.title, fresh.includes(c.person)))));
  }

  return h('section', { class: 'rl-msgr-panel', 'aria-labelledby': 'rl-msgr-title', onkeydown: escape },
    h('div', { class: 'rl-msgr-head' }, h('h2', { class: 'rl-msgr-title', id: 'rl-msgr-title' }, 'Messages')),
    h('div', { class: 'rl-msgr-tabs', role: 'tablist', 'aria-label': 'Messages' },
      tab('chats', 'Chats'), tab('contacts', 'Contacts')),
    body);
}

function listItem(opts, key, name, title, isFresh) {
  return h('button', {
    type: 'button',
    class: 'rl-msgr-item',
    onclick: () => opts.onState({ ...opts.state, thread: key }),
  },
  isFresh ? h('span', { class: 'rl-msgr-dot', 'aria-hidden': 'true' }) : null,
  isFresh ? h('span', { class: 'sr-only' }, 'New: ') : null,
  h('span', { class: 'rl-msgr-item-text' },
    h('span', {}, name),
    title ? h('span', { class: 'rl-msgr-item-title' }, title) : null));
}

function thread(opts) {
  const { state, onState } = opts;
  const aide = state.thread === 'aide';
  const name = aide ? 'Your aide' : state.thread;
  const lines = aide
    ? [opts.brief ?? null, helpThread(opts.help ?? [], opts.useDraft)]
    : [counselThread(name, opts.counsel ?? []), opts.ackThread?.(name) ?? null];
  const send = (e) => {
    e.preventDefault();
    const text = e.currentTarget.elements.text.value.trim();
    if (!text) return;
    if (aide) opts.ask(text);
    else opts.consult(name, text);
  };

  return [
    h('div', { class: 'rl-msgr-head' },
      h('button', { type: 'button', class: 'rl-msgr-back', onclick: () => onState({ ...state, thread: null }) }, 'Back'),
      h('h3', { class: 'rl-msgr-name' }, name)),
    h('div', { class: 'rl-msgr-body' }, lines),
    h('form', { class: 'rl-msgr-compose', onsubmit: send },
      h('textarea', { name: 'text', rows: 3, 'aria-label': 'Message', placeholder: 'Write a message' }),
      h('button', { type: 'submit', class: 'rl-msgr-send' }, 'Send')),
  ];
}
