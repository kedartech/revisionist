// Battles on the map, and the battle sheet (BTC). Draws only the seat's `battles` block and the
// press papers it holds: a battle mark on each area with a battle the seat's nation is in, and a
// mark for a battle it knows only from the press, which opens that paper. The battle sheet holds
// each day's round (the seat's losses and the enemy's as reported), the seat's strength as pips
// and the enemy's as a range, the decision in force, the four decisions and the order on its way;
// a piece's sheet holds the contingency picker. A fall-back area is picked on the map among the lit
// adjacent areas (`theatre.battlePick`). Nothing here reads whether another seat is present.
// Nothing here touches the page on import.

import { h, svg } from '../dom.js';
import {
  BATTLE_CONTINGENCIES, BATTLE_DECISIONS, LABEL_PX, MIN_MARK_PX, MIN_TAP_PX, battleDay, battleRangePips, battleRangeWords,
  contingencyWord, decisionInForce, decisionWord, fallBackAreas, newsBattles, pieceForm, pipsOf, shortDate, stepsWord,
} from '../realism-rules.js';
import { pipGlyph } from './realism-map.js';
import { orderChip, orderLines } from './realism-orders.js';
import { chip } from './ui-kit.js';

const r2 = (n) => Math.round(n * 100) / 100;
/** How far above its area's label point the battle mark sits, clear of the pieces there, in pixels. */
const BATTLE_LIFT = 92;
const KIT_TONE = { need: 'warn', moving: 'info', ok: 'ok', bad: 'danger', quiet: 'quiet' };

/** The seat's battle at area `key`, or null. */
export const battleAt = (rv, key) => (rv.battles ?? []).find((b) => b.area === key) ?? null;

/** The sheet's title: "Battle at The Sudland Coast · day 3". */
export const battleTitle = (b, today) => `Battle at ${b.name} · day ${battleDay(b, today)}`;

/**
 * Every battle mark the map draws: `{ area, kind: 'own', battle, words }` for each battle the
 * seat's nation is in, `{ area, kind: 'news', paper, words }` for each the press gave it.
 */
export function battleMarksOf(rv) {
  const today = rv.clock?.world_date ?? null;
  const own = (rv.battles ?? []).map((b) => ({
    area: b.area, kind: 'own', battle: b,
    words: `Battle at ${b.name}, day ${battleDay(b, today)}: you ${b.side === 'defender' ? 'defend against' : 'attack'} ${b.enemy}. Open the battle sheet`,
  }));
  const news = newsBattles(rv).map((n) => ({ area: n.area, kind: 'news', paper: n.paper, words: `In the press: ${n.title}. Open the paper` }));
  return [...own, ...news];
}

/** The crossed swords in a ring, centred on (0, 0). */
function swords(size) {
  const q = size * 0.32;
  return svg('g', { class: 'rl-bt-glyph' },
    svg('circle', { r: r2(size * 0.55), class: 'rl-bt-ring' }),
    svg('path', { d: `M${r2(-q)} ${r2(-q)}L${r2(q)} ${r2(q)}M${r2(q)} ${r2(-q)}L${r2(-q)} ${r2(q)}`, class: 'rl-bt-x' }));
}

/**
 * The battle marks, each above its area's label point. `ctx`: { battles (`battleMarksOf`),
 * labelAt, atPx, activate, opts: { still, battle (the open one's area), onBattle(mark) } }.
 */
export function battleLayer({ battles, labelAt, atPx, activate, opts }) {
  return (battles ?? []).filter((m) => labelAt.has(m.area)).map((m) => {
    const [x, y] = labelAt.get(m.area);
    const chosen = m.kind === 'own' && opts.battle === m.area;
    const attrs = opts.still ? { role: 'img', 'aria-label': m.words } : {
      'aria-label': m.words, ...(m.kind === 'own' ? { 'aria-pressed': String(chosen) } : {}), ...activate(() => opts.onBattle?.(m)),
    };
    return atPx({
      class: `rl-bt-mark rl-bt-${m.kind}${chosen ? ' selected' : ''}`, 'data-area': m.area, 'data-battle': m.kind, ...attrs,
    }, x, y, svg('g', { transform: `translate(0 ${-BATTLE_LIFT})` },
      svg('rect', { x: -MIN_TAP_PX / 2, y: -MIN_TAP_PX / 2, width: MIN_TAP_PX, height: MIN_TAP_PX, class: 'rl-tm-hit' }),
      swords(MIN_MARK_PX * 1.1),
      m.kind === 'news'
        ? svg('text', { x: r2(MIN_MARK_PX * 0.75), y: 4, 'font-size': LABEL_PX * 0.85, class: 'rl-bt-note' }, 'press')
        : null),
    svg('title', {}, m.words));
  });
}

/** List mode's twin of the marks: a row for each battle, with what opens it. */
export function battleTable(battles, onBattle) {
  if (!battles?.length) return null;
  return h('table', { class: 'rl-map-list rl-bt-list' },
    h('caption', {}, 'Battles on your map'),
    h('thead', {}, h('tr', {}, ['Battle', 'Known from', ''].map((c) => h('th', { scope: 'col' }, c)))),
    h('tbody', {}, battles.map((m) => h('tr', { 'data-area': m.area },
      h('th', { scope: 'row' }, m.kind === 'own' ? `${m.battle.name}: against ${m.battle.enemy}` : m.words.replace(/^In the press: |\. Open the paper$/g, '')),
      h('td', {}, m.kind === 'own' ? 'Your own forces there' : 'The press'),
      h('td', {}, h('button', { type: 'button', class: 'rl-find', onclick: () => onBattle?.(m) }, m.kind === 'own' ? 'Open the battle' : 'Open the paper'))))));
}

/** Pips in a small inline drawing of their own. */
function pipsInline(pips, cls, label) {
  const w = r2(pips.slots * 8.4 + 2);
  return svg('svg', { class: `rl-bt-pips ${cls}`, viewBox: `${r2(-w / 2)} -1 ${w} 8`, width: w, height: 8, role: 'img', 'aria-label': label },
    pipGlyph(pips, 30, 0));
}

/** The two sides: the seat's pieces there and strength as pips; the enemy as a range from its papers. */
function sidesBlock(b) {
  const own = pipsOf({ domain: 'land', strength: b.strength });
  const range = battleRangePips(b);
  return h('div', { class: 'rl-bt-sides' },
    h('div', { class: 'rl-bt-side rl-bt-own' },
      h('p', { class: 'rl-bt-cap' }, 'Yours'),
      h('p', { class: 'rl-bt-who' }, (b.pieces ?? []).map((p) => p.name).join(', ') || 'Your side'),
      pipsInline(own, 'rl-bt-pips-own', `strength ${b.strength}`),
      h('p', { class: 'rl-bt-s' }, `Strength ${b.strength} · ${b.side === 'defender' ? 'defending' : 'attacking'}`)),
    h('div', { class: 'rl-bt-side rl-bt-enemy' },
      h('p', { class: 'rl-bt-cap' }, 'Reported'),
      h('p', { class: 'rl-bt-who' }, b.enemy),
      range ? pipsInline(range, 'rl-bt-pips-enemy', `strength ${battleRangeWords(b)}`) : null,
      h('p', { class: 'rl-bt-s' }, range
        ? `${battleRangeWords(b)}, as your papers put ${b.enemy} there`
        : `Not yet reported: no paper of yours places ${b.enemy} there`)));
}

/** What the close will apply, in words. */
function nowWords(b, may) {
  if (b.held) return 'At this wake\'s close: your decision is held for the next wake';
  if (b.decided) return 'At this wake\'s close: the decision you filed this wake';
  const { decision, given } = decisionInForce(b);
  const word = `${decisionWord(decision)}${given ? '' : ` (the ${b.side === 'defender' ? 'defender' : 'attacker'}'s default)`}`;
  return `At this wake's close: ${word}${may ? ' unless you change it' : ''}`;
}

/** Day by day: each round's losses, the seat's and the enemy's as reported, and the close to come. */
function daysTable(b, may) {
  return h('table', { class: 'rl-bt-days' },
    h('thead', {}, h('tr', {}, ['Day', 'Your losses', 'Theirs, as reported'].map((c) => h('th', { scope: 'col' }, c)))),
    h('tbody', {}, (b.rounds ?? []).map((r) => h('tr', {},
      h('th', { scope: 'row' }, shortDate(r.on)), h('td', {}, stepsWord(r.own_lost)), h('td', {}, stepsWord(r.enemy_lost))))),
    h('tfoot', {}, h('tr', {}, h('td', { colspan: '3', class: 'rl-bt-now' }, nowWords(b, may)))));
}

/** The seat's latest order for this battle still on its way, as the orders sheet shows a waiting order. */
function waitingOrder(rv, b) {
  const head = `The battle at ${b.name}:`;
  const e = (rv.record?.orders ?? []).filter((o) => o.moving && (o.asked ?? '').startsWith(head)).at(-1);
  if (!e) return null;
  const status = orderChip(e, null);
  return h('div', { class: 'rl-bt-order' },
    h('p', { class: 'rl-oc-ask' }, e.asked),
    chip(status.word, KIT_TONE[status.tone]),
    orderLines(e).map((line) => h('p', { class: 'rl-oc-line' }, line)));
}

/** A decision button: its word, its one line, pressed when in force. */
const decisionButton = ([key, word, line], inForce, onclick) => h('button', {
  type: 'button', class: 'rl-bt-choice', 'data-decision': key, 'aria-pressed': String(inForce === key), onclick,
}, h('b', {}, word), h('span', {}, line));

/** The fall-back pick under way: what is asked, and Cancel. */
function pickingLine(pick, theatre, what) {
  return h('p', { class: 'rl-bt-picking', role: 'status' }, what, ' ',
    h('button', { type: 'button', class: 'rl-find', onclick: () => pick?.({ theatre: { ...theatre, battlePick: null } }) }, 'Cancel'));
}

/**
 * The battle sheet for the seat's battle at `key`: `<section class="rl-bt-sheet">`, or null when
 * the seat's nation is in no battle there. `opts`: { today, act, pick, theatre, onClose }.
 * Press and hold file the `battle` action; withdraw asks for its area on the map first.
 */
export function battleSheet(rv, key, { today, act, pick, theatre = {}, onClose } = {}) {
  const b = battleAt(rv, key);
  if (!b) return null;
  const may = (b.decisions ?? []).length > 0 && !b.decided;
  const { decision: inForce } = decisionInForce(b);
  const hint = h('p', { class: 'rl-bt-hint', role: 'status' });
  const file = (decision, extra = {}) => act?.(`Sending the decision for ${b.name}…`, 'battle', { area: b.area, decision, ...extra });
  const onDecision = {
    press: () => file('press'),
    hold: () => file('hold'),
    reinforce: () => { hint.textContent = `Pick one of your forces next to ${b.name} on the map and put it down there.`; },
    withdraw: () => pick?.({ theatre: { ...theatre, battle: theatre.battle ?? null, battlePick: { kind: 'withdraw', area: b.area, from: b.area, name: b.name } } }),
  };
  const offered = BATTLE_DECISIONS.filter(([k]) => k === 'reinforce' || (b.decisions ?? []).includes(k));
  const picking = theatre.battlePick?.kind === 'withdraw' && theatre.battlePick.area === b.area;
  return h('section', { class: 'rl-bt-sheet', 'aria-labelledby': 'rl-bt-sheet-h', 'data-area': b.area },
    h('h3', { id: 'rl-bt-sheet-h' }, battleTitle(b, today ?? rv.clock?.world_date)),
    sidesBlock(b),
    h('h4', {}, 'Day by day'),
    daysTable(b, may),
    h('h4', {}, 'Your decision'),
    may
      ? h('div', { class: 'rl-bt-decisions', role: 'group', 'aria-label': `Your decision for ${b.name}` },
        offered.map((d) => decisionButton(d, inForce, onDecision[d[0]])))
      : h('p', { class: 'rl-bt-cannot' }, b.held
        ? 'Your decision is held for the next wake and is filed when it opens.'
        : b.decided ? 'You have given this battle its decision for this wake.' : 'You cannot give this battle a decision now.'),
    picking ? pickingLine(pick, theatre, `Pick the area to fall back to on the map: ${fallBackWords(rv, b.area)}.`) : null,
    hint,
    waitingOrder(rv, b),
    h('p', { class: 'rl-bt-note-line muted' }, 'One decision a wake. It is applied at the close, whenever you file it.'),
    standingBlock(b),
    onClose ? h('button', { type: 'button', class: 'rl-find', onclick: onClose }, 'Close') : null);
}

/** The areas lit for a fall-back from `key`, in words. */
function fallBackWords(rv, key) {
  const names = new Map((rv.map?.areas ?? []).map((a) => [a.key, a.name]));
  const lit = fallBackAreas(rv.map, key).map((k) => names.get(k) ?? k);
  return lit.length ? lit.join(', ') : 'none is held by your side';
}

/** Each of the seat's pieces in the battle with its standing order, set on the piece's own sheet. */
function standingBlock(b) {
  if (!(b.pieces ?? []).length) return null;
  return h('div', { class: 'rl-bt-standing' },
    h('h4', {}, 'If you are not here'),
    h('ul', { role: 'list' }, b.pieces.map((p) => h('li', {}, `${p.name}: ${contingencyWord(p.contingency)}`))),
    h('p', { class: 'muted' }, 'Change a standing order on the piece\'s own sheet.'));
}

/** The force key and standing order of own map mark `mark`: from a battle it is in, else its movement form. */
function forceOf(rv, mark) {
  for (const b of rv.battles ?? []) {
    const p = (b.pieces ?? []).find((x) => x.name === mark.name);
    if (p) return { force: p.force, contingency: p.contingency ?? 'hold', known: true };
  }
  const form = pieceForm(rv.desk?.levers, mark);
  return form ? { force: form.force, contingency: null, known: false } : null;
}

/**
 * The contingency picker on own piece `mark`'s sheet: "If you are not here", the four standing
 * orders with a line each, the one in force pressed where the seat's battles say it. Hold and hold
 * at all costs file the `contingency` action; fall back and withdraw when weak ask for their area
 * on the map first. Folded until opened, and open while its area is being picked. Null for a
 * piece no form names or an envoy. `opts`: { act, pick, theatre }.
 */
export function contingencyPicker(rv, mark, { act, pick, theatre = {} } = {}) {
  if (mark?.side !== 'own' || !mark.piece || mark.piece.domain === 'envoy') return null;
  const found = forceOf(rv, mark);
  if (!found) return null;
  const strength = Math.max(1, Math.floor(Number(mark.piece.strength) || 0));
  const below = h('select', { name: 'below', class: 'rl-bt-below', 'aria-label': 'Withdraw when its strength falls below' },
    Array.from({ length: strength }, (_, i) => h('option', { value: String(i + 1), selected: i + 1 === Math.max(1, strength - 1) }, String(i + 1))));
  const from = mark.piece.area?.key ?? null;
  const ask = (kind, extra = {}) => pick?.({ theatre: { ...theatre, battlePick: { kind, force: found.force, from, name: mark.name, ...extra } } });
  const on = {
    hold: () => act?.(`Setting ${mark.name}'s standing order…`, 'contingency', { force: found.force, kind: 'hold' }),
    hold_fast: () => act?.(`Setting ${mark.name}'s standing order…`, 'contingency', { force: found.force, kind: 'hold_fast' }),
    fall_back: () => ask('fall_back'),
    withdraw_below: () => ask('withdraw_below', { below: Number(below.value) || Math.max(1, strength - 1) }),
  };
  const picking = Boolean(theatre.battlePick && theatre.battlePick.force === found.force);
  // folded until opened, so a phone's piece sheet stays short and the lit places above it stay free
  return h('details', { class: 'rl-bt-contingency', open: picking },
    h('summary', {}, h('h3', { id: 'rl-bt-cont-h' }, 'If you are not here')),
    h('p', { class: 'muted' }, found.known
      ? `${mark.name} stands on: ${contingencyWord(found.contingency)}.`
      : 'What this piece does in a battle while no decision of yours is in force.'),
    h('div', { class: 'rl-bt-kinds', role: 'group', 'aria-label': `Standing order for ${mark.name}` },
      BATTLE_CONTINGENCIES.map(([key, word, line]) => h('button', {
        type: 'button', class: 'rl-bt-choice', 'data-kind': key, 'aria-pressed': String(found.known && found.contingency === key), onclick: on[key],
      }, h('b', {}, word), h('span', {}, line)))),
    h('label', { class: 'rl-bt-below-l' }, 'Withdraw when weak: below strength ', below),
    picking ? pickingLine(pick, theatre, `Pick the area to fall back to on the map: ${fallBackWords(rv, from)}.`) : null);
}

/**
 * The map's lit areas while a fall-back area is being picked (`theatre.battlePick`), as the
 * drawing's targets, at their label points in `shapes`.
 */
export function battleTargets(rv, battlePick, shapes) {
  if (!battlePick?.from || !shapes) return [];
  const names = new Map((rv.map?.areas ?? []).map((a) => [a.key, a.name]));
  const verb = battlePick.kind === 'withdraw' ? 'Withdraw to' : 'Fall back to';
  return fallBackAreas(rv.map, battlePick.from).filter((k) => shapes.areas?.[k]).map((k) => {
    const [lon, lat] = shapes.areas[k].label;
    return { place: { name: names.get(k) ?? k, lon, lat }, value: k, area: k, days: null, lift: null, chosen: false, words: `${verb} ${names.get(k) ?? k}` };
  });
}

/** What putting down on lit area `to` files for `battlePick`: [action, body]. */
export function battlePickOrder(battlePick, to) {
  if (battlePick.kind === 'withdraw') return ['battle', { area: battlePick.area, decision: 'withdraw', to }];
  const body = { force: battlePick.force, kind: battlePick.kind, to };
  if (battlePick.kind === 'withdraw_below') body.below = battlePick.below;
  return ['contingency', body];
}
