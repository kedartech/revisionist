// The aide's briefing: what the aide tells the seat at the head of What happened, built in code
// from the seat's own view (no model call). The splash greets the seat with the same component.

import { h } from '../dom.js';
import { changedFigures, happenedLines } from './realism-happened.js';

/** The settled statuses the aide reports: an order that went slowly, loosely or only in part. */
export const SLOW_STATUSES = Object.freeze(['carried out loosely', 'carried out late', 'carried out in part']);

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December'];
const DAY_MS = 86400000;

/** "20 October 1941" (the record's and the agenda's day in words) as a day count; null otherwise. */
function dayNumber(words) {
  const m = /^(\d{1,2}) ([A-Z][a-z]+) (\d{4})$/.exec(words ?? '');
  const month = m ? MONTHS.indexOf(m[2]) : -1;
  return month < 0 ? null : Date.UTC(Number(m[3]), month, Number(m[1])) / DAY_MS;
}

/** Mandates issued after the day the wake before opened, up to the day this one opened. */
function newMandates(agenda, wake) {
  const opened = dayNumber(wake?.opened);
  const passed = wake?.days_passed;
  if (opened === null || !Number.isInteger(passed)) return [];
  return (agenda?.items ?? [])
    .filter((m) => {
      const day = dayNumber(m.issued);
      return day !== null && day > opened - passed && day <= opened;
    })
    .map((m) => `New ${(m.kind ?? 'matter').toLowerCase()}${m.issuer ? ` from ${m.issuer}` : ''}: ${m.text}`);
}

/** The record's orders settled this wake with a `SLOW_STATUSES` status: the aide tells these. */
export function slowOrders(record) {
  const settled = record?.wake?.settled ?? [];
  return (record?.orders ?? []).filter((o) => settled.includes(o.id) && SLOW_STATUSES.includes(o.status));
}

/**
 * The aide's lines for the wake just opened, from the seat's view (`record`, `situation`,
 * `agenda`) and nothing else: each order settled this wake that went slowly, loosely or in part,
 * in the record's own sentence; each figure that moved; each mandate issued since the wake
 * before. Missing parts give no lines.
 */
export function briefingLines(view) {
  const record = view?.record;
  return [
    ...happenedLines({ orders: slowOrders(record), wake: record?.wake }),
    ...changedFigures(view?.situation),
    ...newMandates(view?.agenda, record?.wake),
  ];
}

/**
 * The briefing block: the aide's name (and portrait, when there is one), a lead sentence when
 * given, then one item per line, all as text. Null when there is neither a lead nor a line.
 */
export function aideBriefing({ aide, portrait, lines, lead } = {}) {
  const items = lines ?? [];
  if (!lead && !items.length) return null;
  const name = aide || 'Your aide';
  return h('section', { class: 'rl-brief', 'aria-label': `${name}: briefing` },
    h('div', { class: 'rl-brief-head' },
      portrait ? h('img', { class: 'rl-brief-portrait', src: portrait, alt: '' }) : null,
      h('p', { class: 'rl-brief-who' }, name)),
    lead ? h('p', { class: 'rl-brief-lead' }, lead) : null,
    items.length ? h('ul', { class: 'rl-brief-lines' }, items.map((l) => h('li', {}, l))) : null);
}
