// The messenger's launcher: a fixed bottom-right speech-bubble button with the unread count.
// contract stub: the wave replaces this body; the signature is final.

/**
 * `chatLauncher({ open, total, onToggle, onKey })`: a `button.rl-msgr-btn` holding the `chat`
 * icon and a visually hidden "Messages" (its accessible name), `aria-expanded` from `open`,
 * and, when `total` > 0, `span.rl-msgr-count` with the number and a hidden " unread". A click
 * calls `onToggle()`; a keydown calls `onKey(event)` when `onKey` is given.
 */
export function chatLauncher(_opts) {
  return null;
}
