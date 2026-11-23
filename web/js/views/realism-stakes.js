// The stakes strip: what is being fought over and how long is left. One tile per contest the
// seat's view holds, then one per open mandate of the seat's own. A tile shows the name and
// the days left, and the lean only when the data carries one (the server sends a lean only
// once a contest's track has moved in this game). Above the tiles: one line per aim of the
// seat's own with its status chip, a tap opening the aim's drill-down, then the degree of the
// win, the drift and the days to the season's end exactly as the data sends them; the client
// counts nothing. Nothing here touches the page on import.

import { h } from '../dom.js';
import { worldDate } from '../rules.js';

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

function decidedTile(c) {
  return h('li', { class: 'rl-stake', 'data-kind': 'decided', title: c.prize || null },
    h('span', { class: 'rl-stake-name' }, c.name),
    h('span', { class: 'rl-stake-winner' }, c.winner ? `Won by ${c.winner}` : 'Decided'));
}

function mandateTile(m) {
  return h('li', { class: 'rl-stake', 'data-kind': 'mandate' },
    h('span', { class: 'rl-stake-kind' }, 'Your mandate'),
    h('span', { class: 'rl-stake-name' }, m.text),
    h('span', { class: 'rl-stake-days' }, daysLeft(m.days_left)));
}

const STATUS_WORD = { met: 'Met', at_risk: 'At risk', failed: 'Failed' };
const openAims = new Set();

/** Open aim `aim`'s drill-down, as a press on its line would: a mark on the bar opens its aim this way. */
export function openAim(aim) {
  openAims.add(String(aim.aim ?? aim.text));
}

function periodLine(aim) {
  if (aim.opens && aim.deadline) return `${worldDate(aim.opens)} to ${worldDate(aim.deadline)}`;
  if (aim.deadline) return `By ${worldDate(aim.deadline)}`;
  if (aim.opens) return `From ${worldDate(aim.opens)}`;
  return null;
}

function leafLine(leaf) {
  const unseen = leaf.seen === 'uncertain';
  return h('li', { class: 'rl-aim-leaf', 'data-holds': unseen ? null : String(Boolean(leaf.holds)) },
    h('span', { class: 'rl-aim-reads' }, leaf.reads),
    unseen ? h('span', { class: 'rl-aim-uncertain' }, 'Uncertain: hidden from you') : null,
    ...(unseen ? [] : (leaf.evidence ?? []).map((e) => h('span', { class: 'rl-aim-evidence' }, e))));
}

function aimRow(aim) {
  const id = String(aim.aim ?? aim.text);
  const period = periodLine(aim);
  const more = h('div', { class: 'rl-aim-more', id: `rl-aim-more-${id}`, hidden: openAims.has(id) ? null : true },
    aim.rule ? h('p', { class: 'rl-aim-rule' }, aim.rule) : null,
    period ? h('p', { class: 'rl-aim-period' }, period) : null,
    (aim.leaves ?? []).length ? h('ul', { class: 'rl-aim-leaves' }, aim.leaves.map(leafLine)) : null,
    aim.reason ? h('p', { class: 'rl-aim-reason' }, aim.reason) : null);
  const toggle = h('button', {
    type: 'button', class: 'rl-aim-toggle', 'aria-expanded': String(openAims.has(id)), 'aria-controls': more.getAttribute('id'),
    onclick: () => {
      const on = !openAims.has(id);
      if (on) openAims.add(id); else openAims.delete(id);
      toggle.setAttribute('aria-expanded', String(on));
      if (on) more.removeAttribute('hidden'); else more.setAttribute('hidden', '');
    },
  },
  h('span', { class: 'rl-aim-chip' }, STATUS_WORD[aim.status] ?? String(aim.status ?? '')),
  h('span', { class: 'rl-aim-text' }, aim.text));
  return h('li', { class: 'rl-aim', 'data-status': aim.status }, toggle, more);
}

/** `aimList(aims)`: one line per aim, each with its status chip and a drill-down; null with none. */
export function aimList(aims, extra = '') {
  const list = Array.isArray(aims) ? aims : [];
  return list.length ? h('ul', { class: `rl-aims${extra ? ` ${extra}` : ''}` }, list.map(aimRow)) : null;
}

function scoreLine(stakes) {
  const items = [];
  if (stakes.degree) items.push(h('span', { class: 'rl-score-item rl-score-degree' }, `Degree of the win: ${stakes.degree}`));
  if (Number.isFinite(stakes.drift)) items.push(h('span', { class: 'rl-score-item rl-score-drift' }, `Drift from history: ${stakes.drift}`));
  if (Number.isFinite(stakes.season_days_left)) {
    const n = stakes.season_days_left;
    items.push(h('span', { class: 'rl-score-item rl-score-end' }, n > 0 ? `Season ends in ${n === 1 ? '1 day' : `${n} days`}` : 'Season ends today'));
  }
  return items.length ? h('p', { class: 'rl-score' }, items) : null;
}

/**
 * `stakesStrip(stakes, { aims })`: the strip for `view.realism.stakes`, or null when it holds
 * nothing to show. The aim lines come first (`aims: false` leaves them out where the Board's
 * pin draws them), then the score line, then the contests in the data's order (soonest first),
 * the seat's mandates and the decided contests.
 */
export function stakesStrip(stakes, { aims = true } = {}) {
  const contests = stakes?.contests ?? [];
  const mandates = stakes?.mandates ?? [];
  const decided = stakes?.decided ?? [];
  const lines = aims ? aimList(stakes?.aims) : null;
  const score = stakes ? scoreLine(stakes) : null;
  const tiles = [...contests.map(contestTile), ...mandates.map(mandateTile), ...decided.map(decidedTile)];
  if (!lines && !score && !tiles.length) return null;
  return h('div', { class: 'rl-stakes', role: 'region', 'aria-label': 'What is at stake' },
    lines, score, tiles.length ? h('ul', { class: 'rl-stakes-list' }, tiles) : null);
}
