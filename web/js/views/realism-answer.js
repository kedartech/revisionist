// "Needs your answer" (Train 2 unit M1): what is waiting on the seat, leader requests
// first, then the desk's own matters, each with its choices (realism_api.py AgendaBlock).

import { h, icon } from '../dom.js';
import { itemDates, itemHeading, optionLines } from './realism-wake.js';
import { agendaEntry, deadlineChip } from './realism-ideas.js';
import { requestChoices } from './realism-requests.js';

/**
 * Every live item, leader requests (`issuer` set) first, then desk matters, each as
 * `{ id, heading, text, dates, choices }`: `heading` from `itemHeading`, `dates` from
 * `itemDates` (realism-wake.js), `choices` from `requestChoices(agenda.style, item)`
 * (realism-requests.js). Under the free style too: a free player answers with an order.
 */
export function answerItems(agenda) {
  const items = agenda.items ?? [];
  return [...items.filter((i) => i.issuer), ...items.filter((i) => !i.issuer)].map((item) => ({
    id: item.id,
    heading: itemHeading(item),
    text: item.text,
    dates: itemDates(item),
    choices: requestChoices(agenda.style, item),
  }));
}

/** An offered option's control: `{ word: 'Choose', button: true }`, or `{ word: 'Filed', button: false }` once `taken`. */
export function optionAction(option) {
  return option.taken ? { word: 'Filed', button: false } : { word: 'Choose', button: true };
}

function optionRow(o, act) {
  const action = optionAction(o);
  return h('li', { class: 'rl-ans-option' },
    h('p', { class: 'rl-ans-label' }, h('strong', {}, o.label)),
    optionLines(o).map((line) => h('p', { class: 'rl-ans-line' }, line)),
    action.button
      ? h('button', {
        type: 'button', class: 'rl-ans-choose', 'aria-label': `Choose: ${o.label}`,
        onclick: () => act('Filing it…', 'option', { pick: o.pick }),
      }, action.word)
      : h('span', { class: 'rl-ans-filed' }, icon('check'), action.word));
}

function planRow(steps, act) {
  const [first] = steps;
  return [
    h('ol', { class: 'rl-ans-plan' }, steps.map((s) => h('li', { class: 'rl-ans-step' },
      h('p', { class: 'rl-ans-label' }, h('strong', {}, s.label)),
      optionLines(s).map((line) => h('p', { class: 'rl-ans-line' }, line))))),
    first.taken
      ? h('span', { class: 'rl-ans-filed' }, icon('check'), 'Filed')
      : h('button', {
        type: 'button', class: 'rl-ans-choose', 'aria-label': `File this plan: ${first.label}`,
        onclick: () => act('Filing it…', 'option', { pick: first.pick }),
      }, 'File this plan'),
  ];
}

function choicesBlock(choices, act) {
  if (choices.kind === 'options') return h('ul', { class: 'rl-ans-options', role: 'list' }, choices.options.map((o) => optionRow(o, act)));
  if (choices.kind === 'plan') return planRow(choices.options, act);
  return h('p', { class: 'rl-ans-own' }, 'Answer it with an order of your own.');
}

/**
 * The section headed "Needs your answer". An option's "Choose" calls
 * `act('Filing it…', 'option', { pick })`; a guided plan has one "File this plan"; no
 * choices reads "Answer it with an order of your own."; with nothing waiting,
 * "Nothing is waiting on you. Your ideas are below.". Each item is drawn by `agendaEntry`
 * (a crisis as an alert) and its dates carry `deadlineChip` against `today`, the world date.
 */
export function needsAnswer(agenda, { act, today }) {
  const items = answerItems(agenda);
  const raw = new Map((agenda.items ?? []).map((i) => [i.id, i]));
  return h('section', { class: 'rl-ans', 'aria-labelledby': 'rl-ans-h' },
    h('h2', { id: 'rl-ans-h' }, 'Needs your answer'),
    items.length
      ? h('ul', { class: 'rl-ans-items', role: 'list' }, items.map((item) => h('li', { class: 'rl-ans-item' },
        agendaEntry(raw.get(item.id), item.heading, item.text, [
          item.dates ? h('p', { class: 'rl-ans-dates' }, item.dates, ' ', deadlineChip(raw.get(item.id).deadline, today)) : null,
          choicesBlock(item.choices, act)]))))
      : h('p', { class: 'rl-ans-none' }, 'Nothing is waiting on you. Your ideas are below.'));
}
