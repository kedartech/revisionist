// Who the seat can reach and how (Phase 4 unit C3), in four groups (realism_api.py).

import { h } from '../dom.js';

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

function person(p) {
  const channels = channelsLine(p.channels);
  return h('li', { class: 'rl-reach-person' },
    h('span', { class: 'rl-reach-name' }, p.name),
    p.title ? h('span', { class: 'rl-reach-title' }, p.title) : null,
    channels ? h('span', { class: 'rl-reach-channels' }, channels) : null);
}

function group({ heading, people }) {
  const id = `rl-reach-${heading.toLowerCase().replace(/\s+/g, '-')}`;
  const { shown, rest } = collapseSplit(people);
  return h('section', { class: 'rl-reach-group', 'aria-labelledby': id },
    h('h3', { id }, heading),
    h('ul', { class: 'rl-reach-list' }, shown.map(person)),
    rest.length > 0 ? h('details', { class: 'rl-reach-more' },
      h('summary', {}, `Show all ${people.length}`),
      h('ul', { class: 'rl-reach-list' }, rest.map(person))) : null);
}

/** The reach panel on the desk. Phase 4 unit C3. */
export function reachPanel(reach) {
  const groups = reachGroups(reach);
  if (groups.length === 0) return document.createDocumentFragment();
  return h('section', { class: 'rl-reach', 'aria-labelledby': 'rl-reach-title' },
    h('h2', { id: 'rl-reach-title' }, 'Who you can reach'),
    groups.map(group));
}
