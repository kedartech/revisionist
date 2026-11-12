// The messenger: the launcher with the unread count, and a panel with Chats (one row per
// conversation) and Contacts. This module composes the launcher, the list, the thread and the
// typing indicator, and keeps the unread marks.

import { h } from '../dom.js';
import { chatLauncher } from './realism-launcher.js';
import { chatList, chatRows } from './realism-chatlist.js';
import { threadView } from './realism-thread.js';
import { typingBubble, typingFor } from './realism-typing.js';

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

/** Lines from the other side per thread (`threads` as `threadItems` gives them): what unread counts. */
export function threadCounts(threads) {
  const counts = {};
  for (const [key, items] of Object.entries(threads ?? {})) {
    counts[key] = (items ?? []).filter((i) => i.side === 'theirs').length;
  }
  return counts;
}

const GROUPS = ['inner_circle', 'government', 'foreign', 'other'];

/** The reach entry called `name`, and whether it is in the inner circle. */
function contactOf(reach, name) {
  for (const key of GROUPS) {
    const hit = (reach?.[key] ?? []).find((c) => c.name === name);
    if (hit) return { contact: hit, inner: key === 'inner_circle' };
  }
  return { contact: null, inner: false };
}

/**
 * The dock. `opts`: `{ state, onState(next), threads, seen, reach, record, pending, drafts,
 * brief, dossierFor(name), ask(text), consult(name, text), onOpen(doc), useDraft(d),
 * contactsTab }`. `state` is `{ open, tab: 'chats' | 'contacts', thread: null | 'aide' | name }`,
 * kept by the room; `threads` maps 'aide' and each contact's name to its items; `pending` is the
 * message being sent (`{ thread, text }`) or null; `drafts` the text kept per thread.
 * Opening a thread calls `onState` with it; the room marks it seen. Esc and the button close it.
 */
export function chatDock(opts) {
  const { state, onState, threads, seen } = opts;
  const { total } = unread(threadCounts(threads), seen);
  const close = () => onState({ ...state, open: false });
  const escape = (e) => { if (e.key === 'Escape') close(); };

  return h('div', { class: 'rl-msgr' },
    chatLauncher({
      open: state.open,
      total,
      onToggle: () => onState({ ...state, open: !state.open }),
      onKey: state.open ? escape : null,
    }),
    state.open ? panel(opts, escape) : null);
}

function panel(opts, escape) {
  const { state, onState } = opts;
  const tab = (key, label) => h('button', {
    type: 'button',
    role: 'tab',
    class: 'rl-msgr-tab',
    'aria-selected': String(state.tab === key),
    onclick: () => onState({ ...state, tab: key, thread: key === 'chats' ? state.thread : null }),
  }, label);

  let body;
  if (state.tab === 'contacts') body = h('div', { class: 'rl-msgr-body' }, opts.contactsTab ?? null);
  else if (state.thread) body = thread(opts);
  else {
    body = h('div', { class: 'rl-msgr-body' }, chatList({
      rows: chatRows({ threads: opts.threads, reach: opts.reach, record: opts.record, seen: opts.seen }),
      onOpen: (key) => onState({ ...state, thread: key }),
    }));
  }

  return h('section', { class: 'rl-msgr-panel', 'aria-labelledby': 'rl-msgr-title', onkeydown: escape },
    h('div', { class: 'rl-msgr-head' }, h('h2', { class: 'rl-msgr-title', id: 'rl-msgr-title' }, 'Messages')),
    h('div', { class: 'rl-msgr-tabs', role: 'tablist', 'aria-label': 'Messages' },
      tab('chats', 'Chats'), tab('contacts', 'Contacts')),
    body);
}

function thread(opts) {
  const { state, onState, pending } = opts;
  const key = state.thread;
  const aide = key === 'aide';
  const { contact, inner } = aide ? { contact: null, inner: true } : contactOf(opts.reach, key);
  const writing = typingFor(pending, key);
  return threadView({
    name: aide ? 'Your aide' : key,
    title: contact?.title ?? null,
    tie: inner ? 'inner' : 'outer',
    dossier: aide ? null : opts.dossierFor?.(key) ?? null,
    lead: aide ? opts.brief ?? null : null,
    items: opts.threads?.[key] ?? [],
    pending: pending?.thread === key ? pending : null,
    draft: opts.drafts?.[key] ?? '',
    typing: writing ? typingBubble(writing) : null,
    onSend: (text) => (aide ? opts.ask(text) : opts.consult(key, text)),
    onBack: () => onState({ ...state, thread: null }),
    onOpen: opts.onOpen,
    onDraft: opts.useDraft,
  });
}
