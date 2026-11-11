// The messenger (Train 2 unit C1): a fixed "Messages" button with the unread count, and a
// panel with Chats (your aide, then each inner-circle person) and Contacts.

export const SEEN_PREFIX = 'rv.chat.seen.';

/** `{ total, fresh }`: lines newer than `seen` summed over every key, and the keys that have them. */
export function unread(counts, seen) { // contract stub
  return { total: 0, fresh: [] };
}

/**
 * The lines seen per thread, kept under `rv.chat.seen.<campaignId>`: `{ read(), write(seen) }`.
 * `read()` gives `{}` for a missing or broken value; with no storage both do nothing.
 */
export function seenStore(storage, campaignId) { // contract stub
  return { read: () => ({}), write: () => {} };
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
export function chatDock(opts) { // contract stub
  return null;
}
