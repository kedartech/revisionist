// The messenger's launcher: a fixed bottom-right speech-bubble button with the unread count.

import { h, icon } from '../dom.js';

/**
 * `chatLauncher({ open, total, onToggle, onKey })`: a `button.rl-msgr-btn` holding the `chat`
 * icon and a visually hidden "Messages" (its accessible name), `aria-expanded` from `open`,
 * and, when `total` > 0, `span.rl-msgr-count` with the number and a hidden " unread". A click
 * calls `onToggle()`; a keydown calls `onKey(event)` when `onKey` is given.
 */
export function chatLauncher({ open, total, onToggle, onKey }) {
  const count = total > 0
    ? h('span', { class: 'rl-msgr-count' }, String(total), h('span', { class: 'sr-only' }, ' unread'))
    : null;
  return h('button', {
    type: 'button',
    class: 'rl-msgr-btn',
    'aria-expanded': String(Boolean(open)),
    onclick: () => onToggle(),
    onkeydown: onKey ?? null,
  }, icon('chat', 20), h('span', { class: 'sr-only' }, 'Messages'), count);
}
