// The first-wake card: three steps for a seat's first day. Shown while wake 0 is open and the
// seat has not pressed Done; the wake header from the server decides, and nothing is stored in
// the browser. Dismissing hides it for that wake, in the room's memory only.
// Nothing here touches the page on import.

import { h } from '../dom.js';

export const FIRST_WAKE = Object.freeze({
  label: 'Your first day',
  heading: 'Your first day in three steps',
  steps: Object.freeze([
    'Read your aims, pinned on the Board.',
    'Choose an option for each matter.',
    'Press Done; come back when the notice says.',
  ]),
  dismiss: 'Dismiss',
});

/**
 * Whether the card shows: wake 0 is open, this seat has not pressed Done, and the card has not
 * been dismissed for it. `dismissed` is the wake number it was dismissed for, or null.
 */
export function firstWakeDue(wake, dismissed) {
  if (!wake || !wake.deadline || wake.wake !== 0) return false;
  return !wake.you_committed && dismissed !== wake.wake;
}

/**
 * `firstWakeCard(wake, { dismissed, onDismiss })`: the card, or null when it is not due.
 * Dismiss, or Escape with focus in the card, calls `onDismiss()`.
 */
export function firstWakeCard(wake, { dismissed, onDismiss }) {
  if (!firstWakeDue(wake, dismissed)) return null;
  return h('section', {
    class: 'rl-firstwake',
    role: 'region',
    'aria-label': FIRST_WAKE.label,
    onkeydown: (e) => {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      onDismiss();
    },
  },
  h('h2', { class: 'rl-firstwake-h' }, FIRST_WAKE.heading),
  h('ol', { class: 'rl-firstwake-steps' }, FIRST_WAKE.steps.map((step) => h('li', {}, step))),
  h('button', { type: 'button', class: 'ghost rl-firstwake-dismiss', onclick: onDismiss }, FIRST_WAKE.dismiss));
}
