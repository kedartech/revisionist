// The overlay while a wake runs (Train 2 unit V): a full-screen layer that holds the room
// and gives the player something to read.

import { h } from '../dom.js';

/** Three fixed, period-neutral lines for a world with no setting text. */
export const QUIET_LINES = Object.freeze([
  'Dispatches are being written.',
  'The wires are quiet for the moment.',
  'Each desk is waiting on its reports.',
]);

const TITLE_ID = 'rl-ovl-title';

const text = (v) => (typeof v === 'string' && v.trim() ? v : null);

/** The setting's `facts`, then its dates as "<on>: <what>"; `QUIET_LINES` when both are empty. */
export function overlayLines(setting) {
  const facts = Array.isArray(setting?.facts) ? setting.facts.map(text).filter(Boolean) : [];
  const dates = Array.isArray(setting?.dates)
    ? setting.dates.map((d) => [text(d?.on), text(d?.what)].filter(Boolean).join(': ')).filter(Boolean)
    : [];
  const lines = [...facts, ...dates];
  return lines.length ? lines : [...QUIET_LINES];
}

/**
 * A layer `<div class="rl-ovl" role="alertdialog" aria-busy="true">` with `message` and the
 * lines, one shown at a time by a CSS animation only; a still first line under reduced motion.
 */
export function wakeOverlay({ message, lines }) {
  const items = (lines ?? []).map(text).filter(Boolean);
  return h('div', {
    class: 'rl-ovl',
    role: 'alertdialog',
    'aria-busy': 'true',
    'aria-modal': 'true',
    'aria-labelledby': TITLE_ID,
  },
  h('div', { class: 'rl-ovl-box' },
    h('h2', { id: TITLE_ID, class: 'rl-ovl-msg' }, message),
    items.length
      ? h('ul', { class: 'rl-ovl-lines' }, items.map((line) => h('li', { class: 'rl-ovl-line' }, line)))
      : null));
}
