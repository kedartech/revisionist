// The orders log: one row per order, made, landed and finished (In-Tray follow-up, unit T4).

import { h } from '../dom.js';
import { worldDate } from '../rules.js';
import { partLines } from './realism-wake.js';

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December'];

// The server words its days ("14 October 1941"); a bare ISO day is worded here. Only ISO sorts.
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

function sortKey(day) {
  if (ISO_DAY.test(day ?? '')) return day;
  const m = /^(\d{1,2}) (\w+) (\d{4})$/.exec(day ?? '');
  const month = m ? MONTHS.indexOf(m[2]) + 1 : 0;
  return month ? `${m[3]}-${String(month).padStart(2, '0')}-${m[1].padStart(2, '0')}` : '';
}

function latestApplied(parts) {
  return parts.map((p) => p.applied).reduce((a, b) => (sortKey(b) > sortKey(a) ? b : a));
}

function dayInWords(day) {
  return ISO_DAY.test(day) ? worldDate(day) : day;
}

/** Where an order stands, in words: finished, refused, landed in part, or only made. */
export function orderStage(result) {
  const { parts } = result;
  if (parts.length && parts.every((p) => p.applied)) return `Finished ${dayInWords(latestApplied(parts))}`;
  if (parts.length && parts.every((p) => p.refused_under)) return 'Refused';
  if (parts.some((p) => p.applied || p.refused_under)) return 'Landed in part';
  return result.filed ? `Made ${dayInWords(result.filed)}` : 'Made';
}

/** Results with the newest filed first; ties keep their given order. Does not mutate. */
export function newestFirst(results) {
  return results
    .map((r, i) => [r, sortKey(r.filed), i])
    .sort(([, a, i], [, b, j]) => (a < b ? 1 : a > b ? -1 : i - j))
    .map(([r]) => r);
}

function askLine(result) {
  const [first, ...rest] = result.parts;
  if (!first) return 'This cannot be sent';
  return rest.length ? `${first.ask} and ${rest.length} more` : first.ask;
}

function logRow(result) {
  return h('li', { class: 'rl-log-row' },
    h('p', { class: 'rl-log-ask' }, askLine(result)),
    h('p', { class: 'rl-log-stage' }, orderStage(result)),
    h('details', { class: 'rl-log-parts' },
      h('summary', {}, 'Each part'),
      h('ul', { role: 'list' }, result.parts.map((p) => h('li', {},
        h('strong', {}, p.ask),
        partLines(p).map((line) => h('p', { class: 'rl-offer-line' }, line)))))));
}

/** The log for the side column. `results` is view.realism.results, `orders` view.realism.orders. */
export function ordersLog(results, orders) {
  void orders;
  if (!results.length) return null;
  return h('section', { class: 'rl-log', 'aria-labelledby': 'rl-log-h' },
    h('h2', { id: 'rl-log-h' }, 'Orders log'),
    h('ul', { class: 'rl-log-rows', role: 'list' }, newestFirst(results).map(logRow)));
}

/**
 * The order's status chip, `{ word, tone }`: "Needs you" (`need`) when `track` waits on the
 * seat's decision; "Under way" (`moving`) while moving; once settled "Carried out" (any
 * status starting "carried out", and `enacted`), "Agreed" (`ok` both), "Declined"
 * (`rebuffed`), "Refused" (`bad` both), "Lapsed", "Withdrawn" (`quiet` both); any other
 * settled status is its own words capitalised, `quiet`.
 */
const SETTLED = {
  agreed: ['Agreed', 'ok'],
  rebuffed: ['Declined', 'bad'],
  refused: ['Refused', 'bad'],
  lapsed: ['Lapsed', 'quiet'],
  withdrawn: ['Withdrawn', 'quiet'],
};

export function orderChip(entry, track) {
  if (track?.decision_needed) return { word: 'Needs you', tone: 'need' };
  if (entry.moving) return { word: 'Under way', tone: 'moving' };
  const status = (entry.status ?? '').toLowerCase();
  if (status.startsWith('carried out') || status === 'enacted') return { word: 'Carried out', tone: 'ok' };
  if (SETTLED[status]) return { word: SETTLED[status][0], tone: SETTLED[status][1] };
  if (!status) return { word: 'Settled', tone: 'quiet' };
  return { word: status.charAt(0).toUpperCase() + status.slice(1), tone: 'quiet' };
}

/**
 * The card's lines: "To <to>"; "With <holder>" while moving and the holder is not `to`;
 * "Answer expected <due>"; "Settled <settled>"; `said` as “<said>”. Each only when set.
 */
export function orderLines(entry) {
  const lines = [];
  if (entry.to) lines.push(`To ${entry.to}`);
  if (entry.moving && entry.holder && entry.holder !== entry.to) lines.push(`With ${entry.holder}`);
  if (entry.due) lines.push(`Answer expected ${dayInWords(entry.due)}`);
  if (entry.settled) lines.push(`Settled ${dayInWords(entry.settled)}`);
  if (entry.said) lines.push(`“${entry.said}”`);
  return lines;
}

/**
 * The record's orders in three lists, each in record order: `need` (a tracker entry that
 * waits on the seat), `moving` (the rest still moving), `finished`. `tracker` is
 * view.realism.orders; an entry's `track` is a tracker order's `id`.
 */
export function orderGroups(record, tracker) {
  const waiting = new Set((tracker?.orders ?? []).filter((o) => o.decision_needed).map((o) => o.id));
  const groups = { need: [], moving: [], finished: [] };
  for (const e of record?.orders ?? []) {
    if (waiting.has(e.track)) groups.need.push(e);
    else if (e.moving) groups.moving.push(e);
    else groups.finished.push(e);
  }
  return groups;
}

export const NO_ORDERS = 'No orders yet. Pick an idea or write one.';

/**
 * The right column, headed "Your orders": cards that need the seat first, each with
 * `stepForm(trackerOrder)` under it, then the moving ones, then a folded "Finished (n)";
 * with no orders, `NO_ORDERS`.
 */
export function orderCards(record, tracker, stepForm) {
  const head = h('h2', { id: 'rl-oc-h' }, 'Your orders');
  if (!(record?.orders ?? []).length) {
    return h('section', { class: 'rl-oc', 'aria-labelledby': 'rl-oc-h' }, head, h('p', { class: 'rl-oc-empty' }, NO_ORDERS));
  }
  const trackerOrder = (e) => (tracker?.orders ?? []).find((o) => o.id === e.track) ?? null;
  const card = (e, form = false) => {
    const t = trackerOrder(e);
    const chip = orderChip(e, t);
    return h('li', { class: 'rl-oc-card' },
      e.asked ? h('p', { class: 'rl-oc-ask' }, e.asked) : null,
      h('span', { class: `rl-oc-chip rl-oc-${chip.tone}` }, chip.word),
      orderLines(e).map((line) => h('p', { class: 'rl-oc-line' }, line)),
      form && t ? stepForm(t) : null);
  };
  const { need, moving, finished } = orderGroups(record, tracker);
  const active = [...need.map((e) => card(e, true)), ...moving.map((e) => card(e))];
  return h('section', { class: 'rl-oc', 'aria-labelledby': 'rl-oc-h' },
    head,
    active.length ? h('ul', { class: 'rl-oc-list', role: 'list' }, active) : null,
    finished.length ? h('details', { class: 'rl-oc-done' },
      h('summary', {}, `Finished (${finished.length})`),
      h('ul', { class: 'rl-oc-list', role: 'list' }, finished.map((e) => card(e)))) : null);
}

