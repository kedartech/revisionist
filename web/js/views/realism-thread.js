// One conversation in the messenger: the items in order, grouped by side, as text-message
// bubbles with a composer at the foot.
// contract stub: the wave replaces these bodies; the signatures are final.

/**
 * The thread's items, oldest first, each `{ side, kind, text, day, iso, docId, lever, label }`:
 * `side` 'mine' or 'theirs'; `kind` 'counsel', 'reply', 'letter' or 'help'; `day` the in-world
 * date in words and `iso` the same date as YYYY-MM-DD (both '' when unknown); `docId` the paper
 * an item opens, else null; `lever` and `label` only on an aide line that offers a form.
 * `person` 'aide' reads `help`; any other name reads `counsel` (their answers and the seat's
 * questions) and the papers in `documents` (a listing) that they wrote.
 */
export function threadItems(_input) {
  return [];
}

/** Consecutive items from one side as `{ side, day, items }`, `day` that of the group's last item. */
export function groupItems(_items) {
  return [];
}

/**
 * The open thread: `{ name, title, tie, dossier, lead, items, pending, draft, typing, onSend,
 * onBack, onOpen, onDraft }`, as an array of nodes for the panel.
 */
export function threadView(_opts) {
  return [];
}
