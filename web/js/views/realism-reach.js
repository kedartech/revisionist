// Who the seat can reach and how, in four groups (realism_api.py), as pure helpers: the
// messenger's Contacts tab (realism-contacts.js) draws them.

const GROUPS = [
  ['inner_circle', 'Inner circle'],
  ['government', 'Government'],
  ['foreign', 'Foreign'],
  ['other', 'Other'],
];

// A group longer than this starts folded; the first few stay in view. [proposed]
const SHOWN = 8;

/** The non-empty groups in order, each with its people (ReachGroups). */
export function reachGroups(reach) {
  return GROUPS.map(([key, heading]) => ({ heading, people: reach?.[key] ?? [] }))
    .filter((g) => g.people.length > 0);
}

/** The channels in the order given, in words: "In person · Cable". */
export function channelsLine(channels) {
  return (channels ?? []).join(' · ');
}

/** The people shown at once, and the rest folded behind a disclosure. */
export function collapseSplit(people) {
  return { shown: people.slice(0, SHOWN), rest: people.slice(SHOWN) };
}
