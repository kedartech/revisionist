// The overlay while a wake runs (Train 2 unit V): a full-screen layer that holds the room
// and gives the player something to read.

/** Three fixed, period-neutral lines for a world with no setting text. */
export const QUIET_LINES = Object.freeze([]);

/** The setting's `facts`, then its dates as "<on>: <what>"; `QUIET_LINES` when both are empty. */
export function overlayLines(setting) { // contract stub
  return [];
}

/**
 * A layer `<div class="rl-ovl" role="alertdialog" aria-busy="true">` with `message` and the
 * lines, one shown at a time by a CSS animation only; a still first line under reduced motion.
 */
export function wakeOverlay({ message, lines }) { // contract stub
  return null;
}
