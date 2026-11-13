// "Ideas" (Train 2 unit M2): orders the seat could file now, the initiative offer and the
// aide's suggested drafts in one list.

import { h, icon } from '../dom.js';
import { optionLines } from './realism-wake.js';
import { panelHead } from './ui-kit.js';

const sameWords = (s) => String(s ?? '').toLowerCase().replace(/\s+/g, ' ').trim();

/**
 * The list: `agenda.initiative` options as `{ type: 'option', label, to, risk, historical,
 * pick, taken }`, then `brief.drafts` as `{ type: 'draft', label, terms, lever }`. A draft
 * whose label equals an option's (case and spacing ignored) is dropped; taken options go
 * last, in their order. `brief` may be null.
 */
export function ideas(agenda, brief) {
  const options = agenda.initiative.map((o) => ({
    type: 'option', label: o.label, to: o.to, risk: o.risk, historical: o.historical, pick: o.pick, taken: o.taken,
  }));
  const named = new Set(options.map((o) => sameWords(o.label)));
  const drafts = (brief?.drafts ?? [])
    .filter((d) => !named.has(sameWords(d.label)))
    .map((d) => ({ type: 'draft', label: d.label, terms: d.terms, lever: d.lever }));
  return [...options.filter((o) => !o.taken), ...options.filter((o) => o.taken), ...drafts];
}

function optionRow(o, act) {
  return h('li', { class: 'rl-idea-row' },
    h('p', { class: 'rl-idea-label' }, h('strong', {}, o.label)),
    optionLines(o).map((line) => h('p', { class: 'rl-idea-line' }, line)),
    o.taken
      ? h('span', { class: 'rl-idea-filed' }, icon('check'), 'Filed')
      : h('button', {
        type: 'button', class: 'rl-btn btn-1', 'aria-label': `Choose: ${o.label}`,
        onclick: () => act('Filing it…', 'option', { pick: o.pick }),
      }, 'Choose'));
}

function planStep(o) {
  return h('li', { class: 'rl-idea-step' },
    h('p', { class: 'rl-idea-label' }, h('strong', {}, o.label)),
    optionLines(o).map((line) => h('p', { class: 'rl-idea-line' }, line)),
    o.taken ? h('span', { class: 'rl-idea-filed' }, icon('check'), 'Filed') : null);
}

function draftRow(d, useDraft) {
  return h('li', { class: 'rl-idea-row rl-idea-draft' },
    h('p', { class: 'rl-idea-label' }, h('strong', {}, d.label)),
    d.terms?.length ? h('ul', { class: 'rl-idea-terms' }, d.terms.map((t) => h('li', {}, t))) : null,
    h('button', {
      type: 'button', class: 'rl-btn btn-1', 'aria-label': `Open the form: ${d.label}`,
      onclick: () => useDraft(d),
    }, 'Open the form'));
}

/**
 * The section headed "Ideas". An option row has "Choose", calling
 * `act('Filing it…', 'option', { pick })`, or the word "Filed" when taken; a draft row has
 * "Open the form", calling `useDraft(draft)`. Under the guided style the plan's steps are
 * listed with no buttons; under the free style only drafts show. Nothing to list: null.
 */
export function ideasPanel(agenda, brief, { act, useDraft }) {
  const all = ideas(agenda, brief);
  const drafts = all.filter((i) => i.type === 'draft');
  const options = all.filter((i) => i.type === 'option');
  const guided = agenda.style === 'guided';
  const beginner = agenda.style !== 'guided' && agenda.style !== 'free';
  const plan = guided && options.length
    ? h('ol', { class: 'rl-idea-plan' }, options.map(planStep))
    : null;
  const offers = beginner && options.length
    ? h('ul', { class: 'rl-idea-rows', role: 'list' }, options.map((o) => optionRow(o, act)))
    : null;
  const suggested = drafts.length
    ? h('ul', { class: 'rl-idea-rows', role: 'list' }, drafts.map((d) => draftRow(d, useDraft)))
    : null;
  if (!plan && !offers && !suggested) return null;
  return h('section', { class: 'panel rl-idea-panel', 'aria-label': 'Ideas' },
    panelHead('Ideas'),
    h('div', { class: 'rl-idea-body' }, plan, offers, suggested));
}
