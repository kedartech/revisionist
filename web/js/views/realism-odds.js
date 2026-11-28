// The odds panel (ODC). "Odds" on the move chip and on the battle sheet asks the server's `odds`
// action and shows only its reply: whose picture it is (each report used, with its source, age
// and confidence), the outcome bar with its three shares and a text twin, the loss range for each
// side, the chance and the days to take the territory, the risk of being forced back and where
// to, and the win share at each strength in the reported range. With no report it says the enemy
// is unknown and shows no figure. Never one headline number: every share sits beside its outcome.
// With the kinds in battle on, it names the kinds on each side as the seat knows them (its own
// pieces', each report's or, for a report naming none, its domain's) and the cause the server
// says moved the odds most.
// Asking and closing file nothing. On a phone the panel is a half sheet (c-odds.css).
// Nothing here touches the page on import.

import { api } from '../api.js';
import { h, svg } from '../dom.js';
import {
  confidenceWord, decisionWord, pieceForm, rangeWords, reportAge, reportAgoWords, reportWhat, reportWho, shortDate,
} from '../realism-rules.js';
import { markSwatch } from './realism-map.js';
import { bar, markNum } from './realism-marks.js';
import { causeWords, ownKind } from './realism-piece.js';
import { reportByKey } from './realism-reports.js';

// The replies asked for on this page, by request, and the one panel open, by request. A reply
// stands for the wake on the server, so a redraw shows it again rather than asking twice.
const replies = new Map();
let openKey = null;
let hatchN = 0;

/** Forget every reply and close the panel. */
export function forgetOdds() { replies.clear(); openKey = null; }

// a reply stands while the wake, the day and the seat's reports stand
const keyOf = (rv, body) => JSON.stringify([
  rv.wake?.wake ?? null, rv.clock?.world_date ?? null, (rv.map?.reports ?? []).map((r) => `${r.key}@${r.seen}`), body,
]);
const in100 = (pct) => `${Math.round(pct)} in 100`;
const steps = (r) => (r.low === r.high ? `${r.low} ${r.low === 1 ? 'step' : 'steps'}` : `${r.low} to ${r.high} steps`);

/** The first section: whose picture the odds come from, each report used in words. */
function whose(rv, odds) {
  const today = rv.clock?.world_date ?? null;
  const used = odds.reports ?? [];
  const lines = used.map((key) => {
    const r = reportByKey(rv.map, key);
    if (!r) return 'a report no longer on your map';
    const age = today ? `, ${reportAgoWords(reportAge(r.seen, today))}` : '';
    return `${reportWhat(r)}, ${rangeWords(r)}, ${reportWho(r)}, seen ${shortDate(r.seen)}${age}, ${confidenceWord(r.confidence)}`;
  });
  return h('section', { class: 'rl-odds-whose' },
    h('h4', {}, 'Whose picture'),
    h('p', {}, used.length === 1 ? 'Yours, from 1 report:' : `Yours, from ${used.length} reports:`),
    h('ul', { role: 'list' }, lines.map((l) => h('li', {}, l))));
}

/** The seat's own pieces the odds were asked for: a battle's side there, or the force a move sends. */
function ownPieces(rv, body) {
  const marks = (rv.map?.marks ?? []).filter((m) => m.side === 'own' && m.piece);
  if (body?.battle) {
    const names = new Set(((rv.battles ?? []).find((b) => b.area === body.battle)?.pieces ?? []).map((p) => p.name));
    return marks.filter((m) => names.has(m.name));
  }
  return marks.filter((m) => body?.force && pieceForm(rv.desk?.levers, m)?.force === body.force);
}

/** A report's kind as the seat knows it: the kind it names, else its area's domain's. */
function theirKind(rv, key) {
  const r = reportByKey(rv.map, key);
  if (!r) return h('li', {}, 'A report no longer on your map');
  if (r.kind && r.kind_name && r.kind_name !== 'unknown') {
    const swatch = r.picture ? markSwatch({ side: 'other', kind: null, certainty: 'reported', picture: r.picture }) : null;
    return h('li', {}, swatch, `${r.kind_name}, as reported`);
  }
  const sea = (rv.map?.areas ?? []).find((a) => a.key === r.area?.key)?.kind === 'sea';
  return h('li', {}, `A ${sea ? 'sea' : 'land'} piece, its kind not reported`);
}

/** The kinds on each side as the seat knows them; sent only with the kinds in battle on. */
function kindsBlock(rv, odds, body) {
  return h('section', { class: 'rl-odds-kinds' },
    h('h4', {}, 'Who fights, as you know them'),
    h('p', { class: 'rl-odds-cap' }, 'Yours'),
    h('ul', { class: 'rl-odds-yours', role: 'list' }, ownPieces(rv, body).map((m) => h('li', {},
      markSwatch(m), `${ownKind(m)?.name ?? m.piece.kind}: ${m.name}`))),
    h('p', { class: 'rl-odds-cap' }, 'Theirs'),
    h('ul', { class: 'rl-odds-theirs', role: 'list' }, (odds.reports ?? []).length
      ? odds.reports.map((k) => theirKind(rv, k))
      : h('li', {}, 'None reported: their kind is not known')));
}

/** The cause the server says moved the odds most, and which way, or that no one cause did. */
function movedLine(moved) {
  if (!moved) return h('p', { class: 'rl-odds-moved' }, 'No one cause here moves the odds');
  const way = moved.direction === 'for' ? 'for you' : 'against you';
  return h('p', { class: 'rl-odds-moved', 'data-cause': moved.cause, 'data-direction': moved.direction },
    `Moved most by ${causeWords(moved.cause, moved.words)}, ${way}`);
}

const OUTCOMES = ['win', 'stalemate', 'loss'];

/** The outcome bar: a segment for each share above none, each with its word; a loss is hatched. */
function outcomeBar(shares) {
  hatchN += 1;
  const id = `rl-odds-hatch-${hatchN}`;
  let x = 0;
  const segs = [];
  for (const k of OUTCOMES) {
    const w = Math.max(0, Number(shares[k]) || 0);
    if (!w) continue;
    segs.push(svg('rect', {
      class: 'rl-odds-seg', 'data-outcome': k, x, y: 0, width: w, height: 10, fill: k === 'loss' ? `url(#${id})` : null,
    }));
    x += w;
  }
  return h('div', { class: 'rl-odds-bar' },
    svg('svg', { class: 'rl-odds-bars', viewBox: '0 0 100 10', preserveAspectRatio: 'none', 'aria-hidden': 'true', focusable: 'false' },
      svg('defs', {}, svg('pattern', { id, width: 4, height: 4, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' },
        svg('rect', { class: 'rl-odds-hatch-bg', width: 4, height: 4 }),
        svg('line', { class: 'rl-odds-hatch', x1: 0, y1: 0, x2: 0, y2: 4 }))),
      segs),
    h('p', { class: 'rl-odds-keys' }, OUTCOMES.filter((k) => Number(shares[k]) > 0)
      .map((k) => h('span', { class: 'rl-odds-key', 'data-outcome': k }, `${k} ${Math.round(shares[k])}`))));
}

/** The bar's text twin: in 100 runs, how many end each way. */
function twin(shares, area) {
  const n = (k) => Math.round(Number(shares[k]) || 0);
  return h('p', { class: 'rl-odds-twin' },
    `In 100 runs of this from your picture of ${area}: ${n('win')} win, ${n('stalemate')} end with neither side through, ${n('loss')} lose.`);
}

/** A loss range as a band on a scale from 0 to `top`, its words above it. */
function lossRow(who, cls, range, top) {
  const at = (v) => (100 * v) / Math.max(1, top);
  return h('div', { class: 'rl-odds-loss' },
    h('p', {}, `${who}: ${steps(range)}`),
    svg('svg', { class: 'rl-odds-band', viewBox: '0 0 100 6', preserveAspectRatio: 'none', 'aria-hidden': 'true', focusable: 'false' },
      svg('rect', { class: 'rl-odds-band-track', x: 0, y: 2, width: 100, height: 2 }),
      svg('rect', { class: `rl-odds-band-fill ${cls}`, x: at(range.low), y: 0, width: Math.max(1, at(range.high) - at(range.low)), height: 6 })));
}

function losses(odds) {
  const top = Math.max(odds.own_lost.high, odds.enemy_lost.high, 1);
  return h('section', { class: 'rl-odds-losses' },
    h('h4', {}, 'Losses, in steps (most runs fall in the range)'),
    lossRow('Yours', 'rl-odds-own', odds.own_lost, top),
    lossRow('Theirs', 'rl-odds-enemy', odds.enemy_lost, top));
}

/** A share of the runs as a bar of 100, named for the outcome it counts; its words sit beside it. */
const runsBar = (name, pct, tone) => bar({ value: pct, limit: 100, name, words: `${name}: ${markNum(pct)} in 100 runs`, tone, num: false });

/** Taking the territory: the chance, the day if taken, and the risk of being forced back, each share a bar. */
function taking(rv, odds) {
  const names = new Map((rv.map?.areas ?? []).map((a) => [a.key, a.name]));
  const row = (dt, ...dd) => [h('dt', {}, dt), h('dd', {}, ...dd)];
  const none = (v) => v === null || v === undefined;
  const when = none(odds.taken_days) ? 'no run took it' : `day ${odds.taken_days} of the fighting, in half the runs that took it`;
  const back = odds.back_to ? `, to ${names.get(odds.back_to) ?? odds.back_to}` : ', with nowhere to fall back to';
  const forced = odds.forced_back ?? 0;
  return h('section', { class: 'rl-odds-take' },
    h('h4', {}, 'Taking the territory'),
    h('dl', {},
      none(odds.taken) ? row('Chance', 'A win here takes no territory')
        : [row('Chance', runsBar('Taken', odds.taken, 'own'), h('span', {}, in100(odds.taken))), row('When, if taken', when)],
      row('Forced back', runsBar('Forced back', forced, 'hostile'), h('span', {}, `${in100(forced)}${back}`))));
}

let folded = false;

/** Whether the table of win shares by strength sits behind "More" (Beginner's room); set at each draw of the room. */
export function foldOdds(on) { folded = Boolean(on); }

/**
 * The win share at each strength the reports allow, as a column each over its strength, a bracket
 * under them naming the reported range the columns span; the table under them is their twin.
 */
function columns(odds, area) {
  const first = odds.by_strength[0].strength;
  const last = odds.by_strength.at(-1).strength;
  const said = (s) => `You win at ${area} if their strength is ${s.strength}`;
  return h('div', { class: 'rl-odds-cols', role: 'group', 'aria-label': `You win at ${area}, by their strength` },
    h('div', { class: 'rl-odds-col-row' }, odds.by_strength.map((s) => {
      const drawn = s.win !== null && s.win !== undefined;
      return h('div', { class: 'rl-odds-col' },
        bar({
          value: drawn ? s.win : 0, limit: 100, name: said(s), column: true, tone: 'own',
          words: drawn ? `${said(s)}: ${markNum(s.win)} in 100 runs` : `${said(s)}: no run drew it`,
          label: drawn ? String(Math.round(s.win)) : '–',
        }),
        h('span', { class: 'rl-odds-col-s', 'aria-hidden': 'true' }, String(s.strength)));
    })),
    h('p', { class: 'rl-odds-col-range' }, first === last ? `Your reports: strength ${first}` : `Your reports: strength ${first} to ${last}`));
}

/** The win share at each strength the reports allow: the columns, and the table behind More on Beginner. */
function byStrength(odds, area) {
  if (!odds.by_strength?.length) return null;
  const table = (...rows) => (folded ? h('details', { class: 'rl-odds-more' }, h('summary', {}, 'More'), rows) : rows);
  return h('section', { class: 'rl-odds-strengths' },
    h('h4', {}, 'If the report is wrong'),
    columns(odds, area),
    table(h('table', { class: 'rl-odds-table' },
      h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'Their strength'), h('th', { scope: 'col' }, `You win at ${area}`))),
      h('tbody', {}, odds.by_strength.map((s) => h('tr', {},
        h('th', { scope: 'row' }, String(s.strength)),
        h('td', {}, s.win === null || s.win === undefined ? 'no run drew it' : in100(s.win))))))));
}

/** The terrain's public facts: all the reply gives without a report. */
function terrainLine(t) {
  const holder = t.holder ? `held by ${t.holder}` : 'held by no one';
  const adds = t.defence ? `adds ${t.defence} to a defender` : 'adds nothing to a defender';
  return h('p', { class: 'rl-odds-terrain' }, `${t.name}: ${t.terrain}, ${adds}; ${holder}.`);
}

/** The body for a reply: the spread, or the unknown enemy and the terrain, or the refusal. */
function replyBody(rv, out, retry, body) {
  if (!out) return [h('p', { class: 'rl-odds-asking', role: 'status' }, 'Asking the odds desk…')];
  if (out.refused || !out.odds) {
    return [h('p', { class: 'rl-odds-refused', role: 'status' }, out.reply || 'No odds just now.'),
      out.busy && retry ? h('button', { type: 'button', class: 'rl-find', onclick: retry }, 'Ask again') : null];
  }
  const odds = out.odds;
  const area = odds.terrain?.name ?? odds.area;
  if (!odds.known) {
    return [
      h('section', { class: 'rl-odds-whose' },
        h('h4', {}, 'Whose picture'),
        h('p', { class: 'rl-odds-unknown' }, `Nothing is known in ${area}. No odds without a report.`)),
      odds.terrain ? terrainLine(odds.terrain) : null,
    ];
  }
  const kinded = Object.hasOwn(odds, 'moved_by');
  return [
    whose(rv, odds),
    kinded ? kindsBlock(rv, odds, body) : null,
    kinded ? movedLine(odds.moved_by) : null,
    h('section', { class: 'rl-odds-outcome' },
      h('h4', {}, `Outcome after ${odds.days} days`),
      outcomeBar(odds.shares),
      twin(odds.shares, area)),
    losses(odds),
    taking(rv, odds),
    byStrength(odds, area),
    h('p', { class: 'rl-odds-foot muted' },
      `${odds.runs.toLocaleString('en-US')} runs on the server from your own map and reports. Asking again gives the same answer.`),
  ];
}

/**
 * The odds panel for reply `out` (the `odds` action's answer; null while it is being asked):
 * `<section class="rl-odds" role="dialog">`. `opts`: { what (the heading's words), onClose, retry,
 * decisions, decision, onDecision (a battle's decisions, each asked anew), body (the request, whose
 * pieces are the seat's side) }. Close and Escape call `onClose`. Nothing here files an order.
 */
export function oddsPanel(rv, out, { what, onClose, retry, decisions = [], decision = null, onDecision, body = null } = {}) {
  const ifs = decisions.length > 1 ? h('div', { class: 'rl-odds-if', role: 'group', 'aria-label': 'Odds if you' },
    h('span', {}, 'If you:'), ' ',
    decisions.map((d) => h('button', {
      type: 'button', class: 'rl-find', 'aria-pressed': String(d === decision), onclick: () => onDecision?.(d),
    }, decisionWord(d)))) : null;
  return h('section', {
    class: 'rl-odds', role: 'dialog', 'aria-modal': 'false', 'aria-labelledby': 'rl-odds-h',
    onkeydown: (e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onClose?.(); } },
  },
  h('div', { class: 'rl-odds-head' },
    h('h3', { id: 'rl-odds-h', tabindex: '-1' }, `Odds · ${what}`),
    h('button', { type: 'button', class: 'rl-odds-close', onclick: () => onClose?.() }, 'Close')),
  ifs,
  h('div', { class: 'rl-odds-body', tabindex: '0', 'aria-label': `The odds for ${what}` }, replyBody(rv, out, retry, body)),
  h('p', { class: 'rl-odds-nofile' }, 'Closing this files nothing.'));
}

/**
 * The Odds button and the box its panel opens in, for request `body` (`{ force, to }` for a move,
 * `{ force, battle, decision }` for a battle). `opts`: { what(body), decisions (a battle's) }.
 * Replies are kept for the page, so a panel left open survives a redraw without asking again.
 */
export function oddsAsker(rv, body, { what, decisions = [] } = {}) {
  let current = body;
  const box = h('div', { class: 'rl-odds-box' });
  const button = h('button', { type: 'button', class: 'rl-odds-ask', 'aria-haspopup': 'dialog', 'aria-expanded': 'false' }, 'Odds');
  const close = () => {
    openKey = null;
    box.replaceChildren();
    button.setAttribute('aria-expanded', 'false');
    button.focus();
  };
  let ask = () => {};
  const show = (focus) => {
    box.replaceChildren(oddsPanel(rv, replies.get(keyOf(rv, current)) ?? null, {
      what: what(current), onClose: close, retry: () => ask(current),
      decisions, decision: current.decision ?? null, onDecision: (d) => ask({ ...current, decision: d }), body: current,
    }));
    button.setAttribute('aria-expanded', 'true');
    if (focus) box.querySelector('h3')?.focus();
  };
  ask = (next) => {
    current = next;
    const key = keyOf(rv, current);
    openKey = key;
    replies.delete(key);
    show(true);
    Promise.resolve()
      .then(() => api.realism('odds', current))
      .catch((e) => ({ reply: e?.message || 'The odds could not be asked just now.', refused: true }))
      .then((out) => {
        replies.set(key, out);
        if (openKey === key && box.isConnected) show(true);
      });
  };
  button.addEventListener('click', () => {
    const key = keyOf(rv, current);
    if (openKey === key) return close();
    const had = replies.get(key);
    if (had && !had.refused) {
      openKey = key;
      return show(true);
    }
    return ask(current);
  });
  // drawn again while a panel for this request, or for another of its battle's decisions, is open
  const asked = [body, ...decisions.map((d) => ({ ...body, decision: d }))].find((b) => keyOf(rv, b) === openKey);
  if (asked) {
    current = asked;
    show(false);
  }
  return { button, box };
}
