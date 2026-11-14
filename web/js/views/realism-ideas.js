// "Ideas" (Train 2 unit M2): orders the seat could file now, the initiative offer and the
// aide's suggested drafts in one list.
// Also the desk's agenda item parts: a crisis as an alert, failure sentences, deadline chips.

import { h, icon } from '../dom.js';
import { optionLines } from './realism-wake.js';
import { alertBox, chip, panelHead } from './ui-kit.js';

const sameWords = (s) => String(s ?? '').toLowerCase().replace(/\s+/g, ' ').trim();

/**
 * What failing an agenda item costs, by kind (`AgendaItem.kind`, lower case). An order and a
 * crisis fail at their date and the failure counts against the seat; blowback and an
 * opportunity only lapse (core/realism/mandates.py `_FAILS`, `_PAID`).
 */
export const FAIL_SENTENCES = Object.freeze({
  order: 'If it is not done by its date the order fails, and a failed order counts heavily against you.',
  crisis: 'If it is not met by its date the crisis fails, and that counts against you.',
  blowback: 'If it is not met by its date it lapses, at no further cost to you.',
  opportunity: 'Ignoring it costs nothing: the window simply closes.',
});

/** Days left at or under which a deadline chip reads as danger. */
export const DUE_DANGER_DAYS = 7;
/** Days left at or under which a deadline chip reads as a warning; beyond it, info. */
export const DUE_WARN_DAYS = 21;

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December'];
const DAY_MS = 86400000;

/** A day as "26 October 1941" or "1941-10-26" to a day count; null for anything else. */
function dayCount(day) {
  const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day ?? '');
  if (iso) return Date.UTC(Number(iso[1]), Number(iso[2]) - 1, Number(iso[3])) / DAY_MS;
  const w = /^(\d{1,2}) ([A-Z][a-z]+) (\d{4})$/.exec(day ?? '');
  const month = w ? MONTHS.indexOf(w[2]) : -1;
  return month < 0 ? null : Date.UTC(Number(w[3]), month, Number(w[1])) / DAY_MS;
}

/** Whole days from `today` (the world date) to `deadline`; null when either is not a day. */
export function daysLeft(deadline, today) {
  const due = dayCount(deadline);
  const now = dayCount(today);
  return due === null || now === null ? null : due - now;
}

/** "6 days left" as a `chip`, toned by `DUE_DANGER_DAYS` and `DUE_WARN_DAYS`; null when undated. */
export function deadlineChip(deadline, today) {
  const days = daysLeft(deadline, today);
  if (days === null) return null;
  const tone = days <= DUE_DANGER_DAYS ? 'danger' : days <= DUE_WARN_DAYS ? 'warn' : 'info';
  const word = days <= 0 ? 'Due today' : `${days} ${days === 1 ? 'day' : 'days'} left`;
  return chip(word, tone);
}

/**
 * One agenda item's own parts on the desk: `head` is the item's title, `text` its text,
 * `rest` the nodes under it (dates, choices). A crisis is an `alertBox` with the cause line
 * (`AgendaItem.cause`, nothing when null) and its failure sentence; any other kind is a plain
 * heading with its failure sentence. Never an alert for an opportunity.
 */
export function agendaEntry(item, head, text, rest) {
  const kind = String(item.kind ?? '').toLowerCase();
  const sentence = Object.hasOwn(FAIL_SENTENCES, kind) ? FAIL_SENTENCES[kind] : null;
  const fail = sentence ? h('p', { class: 'rl-crisis-fail' }, sentence) : null;
  if (kind === 'crisis') {
    const cause = item.cause ? h('p', { class: 'rl-crisis-cause' }, `Behind it: ${item.cause}`) : null;
    return [alertBox(head, text, [cause, fail].filter(Boolean)), rest];
  }
  return [h('h3', {}, head), text ? h('p', { class: 'rl-ans-text' }, text) : null, fail, rest];
}

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
