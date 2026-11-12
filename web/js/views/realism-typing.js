// The typing indicator: the other side's bubble with three dots while their reply is written.

import { h } from '../dom.js';

/** The name to show as writing in `thread`, or null: "Your aide" for 'aide'. */
export function typingFor(pending, thread) {
  if (pending?.thread !== thread) return null;
  return thread === 'aide' ? 'Your aide' : thread;
}

/** A `theirs` bubble `.rl-typing` with three dots and a hidden status line "<name> is writing". */
export function typingBubble(name) {
  return h('div', { class: 'rl-typing rl-th-bubble theirs' },
    h('span', { class: 'rl-typing-dot', 'aria-hidden': 'true' }),
    h('span', { class: 'rl-typing-dot', 'aria-hidden': 'true' }),
    h('span', { class: 'rl-typing-dot', 'aria-hidden': 'true' }),
    h('span', { class: 'sr-only', role: 'status' }, `${name} is writing`));
}
