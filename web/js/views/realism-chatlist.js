// The Chats tab: one row per conversation, the aide first, then the newest activity.
// contract stub: the wave replaces these bodies; the signatures are final.

/**
 * `chatRows({ threads, reach, record, seen })`: rows `{ key, name, initials, title, preview,
 * day, unread, holds }`. `threads` maps 'aide' and each contact's name to its `threadItems`.
 */
export function chatRows(_input) {
  return [];
}

/** `chatList({ rows, onOpen })`: the rows as buttons, `onOpen(key)` on a click. */
export function chatList(_opts) {
  return null;
}
