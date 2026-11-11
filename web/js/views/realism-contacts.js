// The Contacts tab of the messenger (Train 2 unit C2): everyone the seat can reach, and a
// contact's detail with what to do next.

/**
 * The four reach groups in order (`reachGroups`, realism-reach.js), empty ones dropped, as
 * `{ key, heading, rows }` with rows `{ name, title, how, can }`: `how` from `channelsLine`,
 * `can` 'message' for a name in `inner` (the inner circle's names) and 'order' otherwise.
 */
export function contactRows(reach, inner) { // contract stub
  return [];
}

/** A contact's detail lines: `{ office, powers, how }`, `powers` as one sentence (`powersSentence`), null when empty. */
export function contactDetail(contact) { // contract stub
  return { office: null, powers: null, how: null };
}

/**
 * The tab: the groups of rows; a row opens `selected`'s detail via `onSelect(name)`, with
 * "Message" (`onMessage(name)`) for the inner circle or "Write them an order"
 * (`onOrder(contact)`) for anyone else.
 */
export function contactsTab(reach, { inner, selected, onSelect, onMessage, onOrder }) { // contract stub
  return null;
}
