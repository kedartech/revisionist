// The stakes strip: what is being fought over and how long is left. One tile per contest the
// seat's view holds, then one per open mandate of the seat's own. A tile shows the name and
// the days left, and the lean only when the data carries one (the server sends a lean only
// once a contest's track has moved in this game). Nothing here touches the page on import.

import { h } from '../dom.js';

const STEPS = 10;

/** `daysLeft(n)`: "Due now" at zero, "1 day left", "n days left". */
export function daysLeft(n) {
  if (!(n > 0)) return 'Due now';
  return n === 1 ? '1 day left' : `${n} days left`;
}

/** Ten steps, as many on as `lean.step`, counted toward the contest's first side. */
function leanBlock(sides, lean) {
  const cells = [];
  for (let i = 0; i < STEPS; i += 1) cells.push(h('span', { class: i < lean.step ? 'on' : null }));
  return h('span', { class: 'rl-stake-lean' },
    h('span', { class: 'rl-stake-bar', role: 'img', 'aria-label': `${lean.step} of ${STEPS} steps toward ${sides[0] ?? 'the first side'}` }, cells),
    h('span', { class: 'rl-stake-side' }, lean.favours ? `Leaning to ${lean.favours}` : 'No side ahead'));
}

function contestTile(c) {
  return h('li', { class: 'rl-stake', 'data-kind': 'contest', title: c.prize || null },
    h('span', { class: 'rl-stake-name' }, c.name),
    h('span', { class: 'rl-stake-days' }, daysLeft(c.days_left)),
    c.lean ? leanBlock(c.sides ?? [], c.lean) : null);
}

function mandateTile(m) {
  return h('li', { class: 'rl-stake', 'data-kind': 'mandate' },
    h('span', { class: 'rl-stake-kind' }, 'Your mandate'),
    h('span', { class: 'rl-stake-name' }, m.text),
    h('span', { class: 'rl-stake-days' }, daysLeft(m.days_left)));
}

/**
 * `stakesStrip(stakes)`: the strip for `view.realism.stakes`, or null when it holds no
 * contest and no mandate. Contests come in the data's order (soonest first), then mandates.
 */
export function stakesStrip(stakes) {
  const contests = stakes?.contests ?? [];
  const mandates = stakes?.mandates ?? [];
  if (!contests.length && !mandates.length) return null;
  return h('div', { class: 'rl-stakes', role: 'region', 'aria-label': 'What is at stake' },
    h('ul', { class: 'rl-stakes-list' }, ...contests.map(contestTile), ...mandates.map(mandateTile)));
}
