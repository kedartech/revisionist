// The cost strip on an order: under an open standard form, who carries the order first, the
// days its path states, and how many of the seat's orders that person already holds, from
// `view.realism.court`. Past the court's load limit it says the order is likely to go slow. A
// form whose path the court does not carry gets no strip.
// The staff read on a suggested action: what the staff expect it to move (`expects`) and the
// three risk levels (`risks`), from the agenda, and the forecast checked against what happened
// (`agenda.forecast`), the seat's record drawn as a bar beside its words. Nothing here touches
// the page on import.

import { h } from '../dom.js';
import { bar } from './realism-marks.js';

/** The court path a form travels: the one whose id is the form's pipeline; else null. */
function pathFor(lever, court) {
  return court?.paths?.find((p) => p.id === lever.pipeline) ?? null;
}

/** `pathDays(steps)`: the days the steps state, summed, and how many state none. */
export function pathDays(steps) {
  let days = 0;
  let open = 0;
  for (const s of steps) {
    if (s.days === null || s.days === undefined) open += 1;
    else days += s.days;
  }
  return { days, open };
}

/** `heldBy(person, court)`: the seat's orders waiting on `person`, on every path, each once. */
export function heldBy(person, court) {
  const ids = new Set();
  for (const p of court?.paths ?? []) {
    for (const s of p.steps) if (s.person === person) for (const o of s.orders) ids.add(o.id);
  }
  return ids.size;
}

const dayWord = (n) => (n === 1 ? '1 day' : `${n} days`);

function daysLine({ days, open }) {
  if (!open) return `Its path takes ${dayWord(days)}`;
  const steps = open === 1 ? 'one step states' : `${open} steps state`;
  return `Its path takes at least ${dayWord(days)}; ${steps} no time`;
}

function loadLine(first, held) {
  const who = first.you ? 'You' : first.name;
  if (!held) return `${who} ${first.you ? 'hold' : 'holds'} none of your orders`;
  return `${who} already ${first.you ? 'hold' : 'holds'} ${held} of your orders`;
}

/**
 * `goesSlow(first, held, limit)`: load tells against the new order. The engine counts the
 * other orders moving at the holder's step and takes one off an AI holder's decision for each
 * past the limit; a clerical step passes as time and the seat decides its own step, so neither
 * slows for load.
 */
export function goesSlow(first, held, limit) {
  return first.kind === 'decision' && !first.you && held > limit;
}

/**
 * `costStrip(lever, court)`: the strip for one form, or null when its path is not in the
 * court or has no steps.
 */
export function costStrip(lever, court) {
  const path = pathFor(lever, court);
  const first = path?.steps?.[0];
  if (!first) return null;
  const held = heldBy(first.person, court);
  const limit = court.load_limit;
  const slow = goesSlow(first, held, limit);
  return h('div', { class: 'rl-cost', role: 'note', 'aria-label': 'What this order costs', 'data-slow': slow ? 'true' : null },
    h('p', { class: 'rl-cost-who' }, first.you ? 'Carried first by you' : `Carried first by ${first.name}${first.office ? `, ${first.office}` : ''}`),
    h('p', { class: 'rl-cost-days' }, daysLine(pathDays(path.steps))),
    h('p', { class: 'rl-cost-load' }, loadLine(first, held)),
    slow
      ? h('p', { class: 'rl-cost-slow' },
        `Likely to go slow: past ${limit === 1 ? 'one order' : `${limit} orders`}, each more that ${first.name} holds counts against this one.`)
      : null);
}

/**
 * `withCostStrips(forms, levers, court)`: each form in `forms` (the standard forms' fold) gets
 * its strip under it, inside the panel its Draft button opens, so the strip shows only while
 * the form is open. Returns `forms`; null stays null.
 */
export function withCostStrips(forms, levers, court) {
  if (!forms) return forms;
  for (const lever of levers ?? []) {
    const strip = costStrip(lever, court);
    const item = strip && forms.querySelector(`.rl-instrument[data-lever="${CSS.escape(lever.name)}"]`);
    const panel = item?.querySelector('form')?.parentNode;
    panel?.append(strip);
  }
  return forms;
}

const ON_SUFFIX = { stance: ', stance to you', regard: ', regard for you' };
const SIZE_WORDS = { 1: 'One step', 2: 'Two steps' };
const SURE_WORDS = { firm: 'firm', likely: 'staff think it likely', guess: 'a guess' };
const BAR_STEPS = 5;
const BAR_NOW = 2;
const RISK_NAMES = [['escalation', 'Escalation'], ['refusal', 'Refusal'], ['exposure', 'Exposure']];
const RISK_MAX = 3;

/** `expectWords(move)`: its size, its side and how sure the staff are, in words. */
export function expectWords(move) {
  const side = move.direction === 'gain' ? 'in your favour' : 'against you';
  return `${SIZE_WORDS[move.size]} ${side} · ${SURE_WORDS[move.sure]}`;
}

/**
 * `stepCells(move)`: the five steps of its bar. The middle is where the target stands now; a
 * gain marks the one or two steps to its right, a cost the one or two to its left. The agenda
 * carries no current value, so the bar shows the move, not the level.
 */
export function stepCells(move) {
  const cells = Array.from({ length: BAR_STEPS }, (_, i) => (i === BAR_NOW ? 'now' : ''));
  const way = move.direction === 'gain' ? 1 : -1;
  for (let k = 1; k <= move.size; k += 1) cells[BAR_NOW + way * k] = move.direction;
  return cells;
}

function expectRow(move) {
  return h('li', { class: 'rl-exp-row', 'data-direction': move.direction },
    h('span', { class: 'rl-exp-name' }, `${move.name}${ON_SUFFIX[move.on] ?? ''}`),
    h('span', { class: 'rl-exp-bar', 'aria-hidden': 'true' },
      stepCells(move).map((step) => h('i', { 'data-step': step || null }))),
    h('span', { class: 'rl-exp-read' },
      h('span', { class: 'rl-exp-glyph', 'aria-hidden': 'true' }, move.direction === 'gain' ? '▲' : '▼'), ' ',
      h('span', { class: 'rl-exp-words' }, expectWords(move))));
}

/** `riskChips(risks)`: escalation, refusal and exposure, each as a chip with its level of three. */
export function riskChips(risks) {
  return h('ul', { class: 'rl-exp-risks', role: 'list', 'aria-label': 'What the staff think it risks' },
    RISK_NAMES.map(([key, word]) => {
      const level = risks[key];
      return h('li', { class: 'rl-exp-chip', 'aria-label': `${word}: ${level} of ${RISK_MAX}` },
        word, h('span', { class: 'rl-exp-level', 'aria-hidden': 'true' }, '●'.repeat(level) + '○'.repeat(RISK_MAX - level)));
    }));
}

/**
 * `staffRead(option)`: the staff read under a suggested action, or null when it carries
 * neither moves nor risk levels. Each move is a row; the levels are chips with the risk
 * sentence under them as a caption.
 */
export function staffRead(option) {
  const moves = option.expects ?? [];
  if (!moves.length && !option.risks) return null;
  return h('div', { class: 'rl-exp' },
    moves.length
      ? h('ul', { class: 'rl-exp-rows', role: 'list', 'aria-label': 'What the staff expect it to move' }, moves.map(expectRow))
      : null,
    option.risks ? riskChips(option.risks) : null,
    option.risks && option.risk ? h('p', { class: 'rl-exp-cap' }, option.risk) : null);
}

/** `readLines(option)`: the option's lines; with risk levels the risk sentence moves to the caption. */
export function readLines(option) {
  return option.risks ? { ...option, risk: '' } : option;
}

const OUTCOME_WORDS = { held: 'It happened', missed: 'It did not happen', open: 'Not settled yet' };

/** `outcomeWords(outcome)`: held, missed or open, in words; open is never worded as a result. */
export function outcomeWords(outcome) {
  return OUTCOME_WORDS[outcome] ?? OUTCOME_WORDS.open;
}

/** `recordLine(forecast)`: the seat's record, "Your staff were right N of M"; null while none has settled. */
export function recordLine(forecast) {
  if (!forecast?.checked) return null;
  return `Your staff were right ${forecast.held} of ${forecast.checked}`;
}

function forecastMove(move) {
  return h('li', { class: 'rl-fc-move', 'data-outcome': move.outcome },
    h('span', { class: 'rl-exp-name' }, `${move.name}${ON_SUFFIX[move.on] ?? ''}`),
    h('span', { class: 'rl-fc-expect' }, expectWords(move)),
    h('span', { class: 'rl-fc-outcome' }, outcomeWords(move.outcome)));
}

function forecastOrder(order) {
  return h('li', { class: 'rl-fc-order' },
    h('p', { class: 'rl-fc-asked' }, h('strong', {}, order.asked || 'Your order'), ` · filed ${order.filed}`),
    order.aide ? h('p', { class: 'rl-fc-aide' }, 'Chosen by your aide') : null,
    h('ul', { class: 'rl-fc-moves', role: 'list', 'aria-label': 'What the staff expected, and what happened' }, order.moves.map(forecastMove)),
    order.settles ? h('p', { class: 'rl-fc-settles' }, `Settles ${order.settles}`) : null);
}

/**
 * `forecastRecord(forecast)`: each filed order that came from a suggested action with its
 * expected moves and how each came out, under the seat's record. Null when there are none.
 */
export function forecastRecord(forecast) {
  const orders = (forecast?.orders ?? []).filter((o) => o.moves.length);
  if (!orders.length) return null;
  const record = recordLine(forecast);
  return h('div', { class: 'rl-fc' },
    h('h3', { id: 'rl-fc-h' }, 'Your staff\'s forecasts'),
    record ? h('p', { class: 'rl-fc-record' }, record) : h('p', { class: 'rl-fc-record' }, 'None has settled yet'),
    record ? bar({ value: forecast.held, limit: forecast.checked, name: 'Your staff were right', num: false, extra: 'rl-fc-bar' }) : null,
    h('ul', { class: 'rl-fc-orders', role: 'list', 'aria-labelledby': 'rl-fc-h' }, orders.map(forecastOrder)));
}
