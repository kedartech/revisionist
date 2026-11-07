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
  return m ? `${m[3]}-${String(MONTHS.indexOf(m[2]) + 1).padStart(2, '0')}-${m[1].padStart(2, '0')}` : '';
}

function latestApplied(parts) {
  return parts.map((p) => p.applied).reduce((a, b) => (sortKey(b) > sortKey(a) ? b : a));
}

/** Where an order stands, in words: finished, refused, landed in part, or only made. */
export function orderStage(result) {
  const { parts } = result;
  if (parts.length && parts.every((p) => p.applied)) {
    const day = latestApplied(parts);
    return `Finished ${ISO_DAY.test(day) ? worldDate(day) : day}`;
  }
  if (parts.length && parts.every((p) => p.refused_under)) return 'Refused';
  if (parts.some((p) => p.applied || p.refused_under)) return 'Landed in part';
  return `Made ${worldDate(result.filed)}`;
}

/** Results with the newest filed first; ties keep their given order. Does not mutate. */
export function newestFirst(results) {
  return results
    .map((r, i) => [r, i])
    .sort(([a, i], [b, j]) => (a.filed < b.filed ? 1 : a.filed > b.filed ? -1 : i - j))
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
