// Requests from named leaders, filed in the in-tray as papers with their choices. A matter
// with no issuer (a crisis, blowback, an opportunity) stays in the desk's agenda panel.

import { h } from '../dom.js';
import { dayWords, itemDates, optionLines } from './realism-wake.js';

const TITLE_MAX = 120;

/** The live matters a named leader has asked of the seat, under any play style. */
export function requests(agenda) {
  return (agenda?.items ?? []).filter((item) => item.issuer);
}

/** What the paper offers: a beginner's options, a guided plan filed in one go, or nothing. */
export function requestChoices(style, item) {
  if (style === 'beginner' && item.options.length) return { kind: 'options', options: item.options };
  if (style === 'guided' && item.plan.length) return { kind: 'plan', options: item.plan };
  return { kind: 'none', options: [] };
}

/** The request's own words, cut to fit a row; the row names the leader beside it. */
export function requestTitle(item) {
  const full = item.text;
  return full.length <= TITLE_MAX ? full : `${full.slice(0, TITLE_MAX - 1).trimEnd()}…`;
}

function optionLine(o) {
  return [h('strong', {}, o.label), optionLines(o).map((line) => h('span', { class: 'rl-request-note' }, line))];
}

function choiceBlock(item, style, act) {
  const { kind, options } = requestChoices(style, item);
  if (kind === 'none') {
    return h('p', { class: 'rl-request-free' }, 'Answer it with an order of your own from the desk.');
  }
  if (kind === 'plan') {
    return [
      h('ol', { class: 'rl-request-plan' }, options.map((o) => h('li', {}, optionLine(o)))),
      h('button', {
        type: 'button', class: 'rl-btn', 'aria-label': `File the plan for ${item.issuer}`,
        onclick: () => act('Filing it…', 'option', { pick: options[0].pick }),
      }, 'File this plan'),
    ];
  }
  return h('ul', { class: 'rl-request-options', role: 'list' }, options.map((o) => h('li', {},
    h('div', {}, optionLine(o)),
    h('button', {
      type: 'button', class: 'rl-btn', 'aria-label': `Choose: ${o.label}`,
      onclick: () => act('Filing it…', 'option', { pick: o.pick }),
    }, 'Choose'))));
}

function requestPaper(item, style, act) {
  return h('li', { class: 'rl-request' },
    h('details', {},
      h('summary', { class: 'rl-row rl-row-paper' },
        h('span', { class: 'rl-dot rl-dot-on', title: 'Waiting on you' }),
        h('span', { class: 'rl-row-main' },
          h('span', { class: 'rl-row-from' }, item.issuer),
          h('span', { class: 'rl-row-title' }, requestTitle(item))),
        h('span', { class: 'rl-row-date' }, item.deadline ? `Due ${dayWords(item.deadline)}` : '')),
      h('div', { class: 'rl-request-body' },
        h('p', { class: 'rl-matter-text' }, item.text),
        h('p', { class: 'rl-matter-dates' }, itemDates(item)),
        choiceBlock(item, style, act))));
}

/** The requests block at the head of the tray; nothing when no leader has asked anything. */
export function requestsPanel(agenda, { act }) {
  const mine = requests(agenda);
  if (!mine.length) return null;
  return h('section', { class: 'rl-requests', 'aria-labelledby': 'rl-requests-h' },
    h('h3', { id: 'rl-requests-h' }, mine.length === 1 ? 'A request waiting on you' : `${mine.length} requests waiting on you`),
    h('ul', { class: 'rl-rows', role: 'list' }, mine.map((item) => requestPaper(item, agenda.style, act))));
}
