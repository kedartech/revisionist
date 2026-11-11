// "Ideas" (Train 2 unit M2): orders the seat could file now, the initiative offer and the
// aide's suggested drafts in one list.

/**
 * The list: `agenda.initiative` options as `{ type: 'option', label, to, risk, historical,
 * pick, taken }`, then `brief.drafts` as `{ type: 'draft', label, terms, lever }`. A draft
 * whose label equals an option's (case and spacing ignored) is dropped; taken options go
 * last, in their order. `brief` may be null.
 */
export function ideas(agenda, brief) { // contract stub
  return [];
}

/**
 * The section headed "Ideas". An option row has "Choose", calling
 * `act('Filing it…', 'option', { pick })`, or the word "Filed" when taken; a draft row has
 * "Open the form", calling `useDraft(draft)`. Under the guided style the plan's steps are
 * listed with no buttons; under the free style only drafts show. Nothing to list: null.
 */
export function ideasPanel(agenda, brief, { act, useDraft }) { // contract stub
  return null;
}
