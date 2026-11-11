// The overlay while a wake runs (Train 2 unit V): a full-screen layer that holds the room
// and gives the player something to read.

import { h } from '../dom.js';

/** Three fixed, period-neutral lines for a world with no setting text. */
export const QUIET_LINES = Object.freeze([
  'Dispatches are being written.',
  'The wires are quiet for the moment.',
  'Each desk is waiting on its reports.',
]);

/** The delay rules in p5-overlay.css: one per slot, so no more lines than this are drawn. */
export const OVERLAY_SLOTS = 8;

const TITLE_ID = 'rl-ovl-title';

const text = (v) => (typeof v === 'string' && v.trim() ? v : null);

/**
 * The setting's `facts`, then its dates as "<on>: <what>"; `QUIET_LINES` when both are empty.
 * More lines than slots: the window of `OVERLAY_SLOTS` that starts at `(turn * OVERLAY_SLOTS) % n`.
 */
export function overlayLines(setting, turn = 0) {
  const facts = Array.isArray(setting?.facts) ? setting.facts.map(text).filter(Boolean) : [];
  const dates = Array.isArray(setting?.dates)
    ? setting.dates.map((d) => [text(d?.on), text(d?.what)].filter(Boolean).join(': ')).filter(Boolean)
    : [];
  const lines = [...facts, ...dates];
  const all = lines.length ? lines : [...QUIET_LINES];
  const n = all.length;
  if (n <= OVERLAY_SLOTS) return all;
  const start = (((Number.isInteger(turn) ? turn : 0) * OVERLAY_SLOTS) % n + n) % n;
  return Array.from({ length: OVERLAY_SLOTS }, (_, i) => all[(start + i) % n]);
}

/**
 * A layer `<div class="rl-ovl" role="alertdialog" aria-busy="true">` with `message` and the
 * lines, one shown at a time by a CSS animation only; a still first line under reduced motion.
 */
export function wakeOverlay({ message, lines }) {
  const items = (lines ?? []).map(text).filter(Boolean).slice(0, OVERLAY_SLOTS);
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
