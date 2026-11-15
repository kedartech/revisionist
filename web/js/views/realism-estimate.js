// The cost strip on an order: under an open standard form, who carries the order first, the
// days its path states, and how many of the seat's orders that person already holds, from
// `view.realism.court`. Past the court's load limit it says the order is likely to go slow. A
// form whose path the court does not carry gets no strip. Nothing here touches the page on
// import.

import { h } from '../dom.js';

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
