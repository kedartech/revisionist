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

/** The card on Beginner's map-first room, worded for what that room shows [proposed]. */
export const FIRST_WAKE_BEGINNER = Object.freeze({
  ...FIRST_WAKE,
  steps: Object.freeze([
    'Read your three aims above the map.',
    'Do the next step in What needs you.',
    'Press Done; come back when the notice says.',
  ]),
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
 * Dismiss, or Escape with focus in the card, calls `onDismiss()`. `beginner` words it for Beginner's map-first room.
 */
export function firstWakeCard(wake, { dismissed, onDismiss, beginner = false }) {
  if (!firstWakeDue(wake, dismissed)) return null;
  const words = beginner ? FIRST_WAKE_BEGINNER : FIRST_WAKE;
  return h('section', {
    class: 'rl-firstwake',
    role: 'region',
    'aria-label': words.label,
    onkeydown: (e) => {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      onDismiss();
    },
  },
  h('h2', { class: 'rl-firstwake-h' }, words.heading),
  h('ol', { class: 'rl-firstwake-steps' }, words.steps.map((step) => h('li', {}, step))),
  h('button', { type: 'button', class: 'ghost rl-firstwake-dismiss', onclick: onDismiss }, words.dismiss));
}
