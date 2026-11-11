// "What happened" (Train 2 unit W): the sheet that opens once when a new wake opens.

export const HAPPENED_PREFIX = 'rv.happened.';

/**
 * One line per order that is moving or settled since the last wake (`record.wake.settled`):
 * moving "<asked>: under way, with <holder>" (", with" dropped with no holder); settled
 * "<asked>: <status>", then " — “<said>”" when the order has an answer.
 */
export function happenedLines(record) { // contract stub
  return [];
}

/**
 * Figures whose latest reading differs from the one before (first source's `history`), as
 * "<label>: <before> to <after> <unit>", numbers in en-US digits, the unit dropped when none.
 */
export function changedFigures(situation) { // contract stub
  return [];
}

/** The last wake shown, kept under `rv.happened.<campaignId>`: `{ read(), write(n) }`; `read()` is 0 when missing, broken or with no storage. */
export function happenedStore(storage, campaignId) { // contract stub
  return { read: () => 0, write: () => {} };
}

/** True for a wake page whose number is above 0 and above the one stored. */
export function shouldShow(wake, store) { // contract stub
  return false;
}

/**
 * A `<dialog class="rl-hap">` headed "What happened": "It is <date>. <n> days have passed.",
 * the lines, "<n> new papers in your tray", the changed figures, and "To the desk", which
 * calls `onClose()`; the room then stores the wake number.
 */
export function happenedSheet({ record, situation, date, onClose }) { // contract stub
  return null;
}
