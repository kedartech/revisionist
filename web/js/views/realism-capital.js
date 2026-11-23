// The Capital board (CBD): the map's twin for the seat's politics. In the map-first room a switch
// of two, Map and Capital, sits at the top left of the board, and the Capital takes the map's
// place. Its head holds both chambers at a glance; the left column lists the nation's live
// questions (its measures on the floor, its held orders and the asks put before it, the
// conferences it is invited to, the contests and mandates it carries); the middle draws the
// picked one (a vote as a track over the chamber's blocs, a held order as its chain, a
// conference as a table, one person who decides with those who have access, a council as a
// table); the right column shows the picked piece and what the seat holds and owes; the seat's
// own moves are a row under the board, and picking one lights what it would move.
// Everything drawn is a count, a line or a day the seat's view sent: the line that carries a
// vote is the one the server sends with it, and only the seat's own nation's blocs and groups are
// read. Nothing here touches the page on import.

import { h, svg } from '../dom.js';
import { flagBadge } from '../flags.js';
import { askedForFull, browserFull } from '../map/view.js';
import { worldDate } from '../rules.js';
import { moveWords, supportStep, themesFor } from './realism-home.js';
import { personToken } from './realism-people.js';
import { daysBetween } from './realism-timeline.js';

/** The two boards and their names on the switch `[proposed]`. */
export const BOARDS = Object.freeze([['map', 'Map'], ['capital', 'Capital']]);

/** Where the board last chosen on this device is kept. */
export const BOARD_KEY = 'revisionist.board';

/** What the right column says until the priced move sends offers and promises. */
export const OWED_NONE = 'No offer is live and no promise is owed.';

const chamberName = (key) => `the ${String(key).replace(/_/g, ' ')}`;
const capital = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const signed = (n) => (n < 0 ? `down ${-n}` : `up ${n}`);
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** The seat's own home block; null for none, or for a block of any nation but the seat's own. */
const ownHome = (rv) => (rv?.home?.nation?.relation === 'own' ? rv.home : null);

/** The seats of chamber `key` in `home`, summed from its blocs; 0 when the block has no such chamber. */
function seatsIn(home, key) {
  const c = (home?.chambers ?? []).find((x) => x.key === key);
  return c ? c.blocs.reduce((n, b) => n + b.seats, 0) : 0;
}

/** Each of the seat's measures on the floor once, with the chamber that lists it first. */
function measures(home) {
  const seen = new Map();
  for (const c of home?.chambers ?? []) {
    for (const m of c.measures ?? []) if (!seen.has(m.order_id)) seen.set(m.order_id, { m, chamber: c });
  }
  return [...seen.values()];
}

/** The seat's own nation's name, from its home block, else from a standing that is its own. */
const ownName = (rv) => ownHome(rv)?.nation.name ?? (rv?.home?.standings ?? []).find((s) => s.nation.relation === 'own')?.nation.name ?? null;

/** The conferences still to be counted that the seat's nation is invited to. */
function conferences(rv) {
  const me = ownName(rv);
  return (rv?.conferences?.conferences ?? []).filter((c) => !c.tallied && !c.result
    && (me ? (c.invited ?? []).includes(me) : (c.can_vote || Boolean(c.vote))));
}

/**
 * The nation's live questions, in the left column's order: each `{ key, kind, kindWords, title,
 * decides, count, days }` and the block it came from. `count` is `{ yeas, carries, total }` for a
 * vote whose line the server sent, else null; `days` is the days left the view gives, else null.
 */
export function capitalQuestions(rv) {
  const out = [];
  const home = ownHome(rv);
  for (const { m, chamber } of measures(home)) {
    const v = m.votes?.[0] ?? null;
    const total = v ? seatsIn(home, v.vote) || seatsIn(home, chamber.key) : 0;
    out.push({
      key: `vote:${m.order_id}`, kind: 'vote', kindWords: 'A vote', title: m.title,
      decides: capital((m.votes ?? []).map((x) => chamberName(x.vote)).join(', then ') || chamberName(chamber.key)),
      count: v && Number.isFinite(v.carries) ? { yeas: v.yeas, carries: v.carries, total } : null,
      days: null, measure: m, chamber,
    });
  }
  for (const l of rv?.locks?.held ?? []) {
    out.push({ key: `held:${l.id}`, kind: 'held', kindWords: 'A held order', title: l.words, decides: l.who, count: null, days: null, held: l });
  }
  for (const a of rv?.locks?.asks ?? []) {
    out.push({ key: `ask:${a.id}`, kind: 'ask', kindWords: 'Asked of you', title: a.words, decides: 'You', count: null, days: null, ask: a });
  }
  const today = rv?.clock?.world_date ?? null;
  for (const c of conferences(rv)) {
    const days = today && c.voting_day ? daysBetween(today, c.voting_day) : null;
    out.push({ key: `conf:${c.key}`, kind: 'conference', kindWords: 'A conference', title: c.text, decides: (c.invited ?? []).join(', '), count: null, days, conference: c });
  }
  (rv?.stakes?.contests ?? []).forEach((s, i) => {
    out.push({ key: `contest:${i}`, kind: 'contest', kindWords: 'A contest', title: s.name, decides: (s.sides ?? []).join(', '), count: null, days: s.days_left ?? null, contest: s });
  });
  (rv?.stakes?.mandates ?? []).forEach((s, i) => {
    out.push({ key: `mandate:${i}`, kind: 'mandate', kindWords: 'Your mandate', title: s.text, decides: 'You', count: null, days: s.days_left ?? null, mandate: s });
  });
  return out;
}

/** Whether the board has anything to show: with nothing, the switch is not drawn. */
export const hasCapital = (rv) => capitalQuestions(rv).length > 0;

/**
 * The board the room opens on: the one chosen on this device (`stored`), else the Capital for a
 * seat whose path is the political one, else the map.
 */
export function startBoard({ stored = null, path = null } = {}) {
  if (BOARDS.some(([key]) => key === stored)) return stored;
  return path === 'political' ? 'capital' : 'map';
}

/** The switch of two at the board's top left: `onPick(key)`; the board shown is pressed. */
export function boardSwitch(board, onPick) {
  return h('div', { class: 'rl-board-switch', role: 'group', 'aria-label': 'Board' },
    BOARDS.map(([key, word]) => h('button', {
      type: 'button', 'data-board': key, 'aria-pressed': String(board === key), onclick: () => onPick?.(key),
    }, word)));
}

// --- marks ------------------------------------------------------------------------------------

/** A share of a 100-wide box: `n` of `total`, held between 0 and 100. */
const share = (n, total) => (total > 0 ? Math.max(0, Math.min(100, (100 * Number(n)) / total)) : 0);

/** The five steps of a support figure, the step and those under it on. */
const steps = (step) => h('span', { class: 'rl-cap-steps5', 'aria-hidden': 'true', 'data-step': String(step) },
  [1, 2, 3, 4, 5].map((i) => h('span', { class: `rl-cap-step${i <= step ? ' on' : ''}` })));

/** The line at the count that carries a vote, on a bar of `total`; null with no count sent. */
const carryLine = (carries, total, y2 = 10) => (Number.isFinite(carries)
  ? svg('line', { class: 'rl-cap-carry', x1: share(carries, total), x2: share(carries, total), y1: 0, y2 }) : null);

/** A row's count against its line: the yeas as a bar of the seats, with the line that carries it. */
const rowBar = ({ yeas, carries, total }) => svg('svg', {
  class: 'rl-cap-rowbar', viewBox: '0 0 100 6', preserveAspectRatio: 'none', 'aria-hidden': 'true', focusable: 'false',
}, svg('rect', { class: 'rl-cap-track', x: 0, y: 0, width: 100, height: 6 }),
svg('rect', { class: 'rl-cap-fill', x: 0, y: 0, width: share(yeas, total), height: 6 }),
carryLine(carries, total, 6));

// --- the left column: the questions ---------------------------------------------------------------

function questionRow(q, picked, onPick) {
  const count = q.count ? `${q.count.yeas} yea, ${q.count.carries} carry it` : null;
  const days = Number.isInteger(q.days) ? `${plural(q.days, 'day')} left` : null;
  return h('li', {},
    h('button', {
      type: 'button', class: `rl-cap-q k-${q.kind}`, 'data-key': q.key, 'aria-pressed': String(picked),
      'aria-label': [`${q.kindWords}: ${q.title}`, `decided by ${q.decides}`, count, days].filter(Boolean).join('. '),
      onclick: () => onPick(q.key),
    },
    h('span', { class: 'rl-cap-qkind' }, q.kindWords, ' · ', q.decides),
    h('span', { class: 'rl-cap-qtitle' }, q.title),
    q.count ? rowBar(q.count) : null,
    count || days ? h('span', { class: 'rl-cap-qline' }, [count, days].filter(Boolean).join(' · ')) : null,
    ));
}

// --- the head: both chambers at a glance -----------------------------------------------------------

/** The count that carries question `q`'s picked vote in chamber `key`, as the server sent it; null otherwise. */
function carriesIn(q, vote, key) {
  const v = q?.kind === 'vote' ? q.measure.votes?.[vote] : null;
  return v && v.vote === key && Number.isFinite(v.carries) ? v.carries : null;
}

function chamberBar(home, c, carries, picked, onPick) {
  const total = c.blocs.reduce((n, b) => n + b.seats, 0);
  let at = 0;
  const segs = c.blocs.map((b, i) => {
    const w = share(b.seats, total);
    const x = at;
    at += w;
    return svg('rect', { class: `rl-cap-seg b${i % 7}`, 'data-group': b.group, x, y: 0, width: w, height: 10 });
  });
  const name = capital(chamberName(c.key));
  const said = c.blocs.map((b) => `${b.name} ${b.seats}`).join(', ');
  return h('button', {
    type: 'button', class: 'rl-cap-chamber', 'data-key': `chamber:${c.key}`, 'aria-pressed': String(picked),
    'aria-label': `${name}: ${said}${carries === null ? '' : `; ${carries} carry the vote picked`}. Show its blocs`,
    onclick: onPick,
  },
  h('span', { class: 'rl-cap-chname' }, name),
  svg('svg', { class: 'rl-cap-chbar', viewBox: '0 0 100 10', preserveAspectRatio: 'none', 'aria-hidden': 'true', focusable: 'false' },
    segs, carryLine(carries, total)),
  h('span', { class: 'rl-cap-chseats', 'aria-hidden': 'true' }, c.blocs.map((b) => b.seats).join(' · ')));
}

// --- the middle: the pieces ---------------------------------------------------------------------

/** How a theme picked in the moves row moves group `key`: `{ n, words }`, or null. */
function lit(theme, key) {
  const n = theme?.moves?.[key];
  return Number.isFinite(n) && n !== 0 ? { n, words: signed(n) } : null;
}

/** A piece's share of its row in twelfths, never under one: its seats against the chamber's. */
export const grow = (seats, total) => Math.max(1, Math.round((12 * seats) / Math.max(1, total)));

function piece({ key, name, sub, support, size, theme, picked, onPick }) {
  const step = supportStep(support);
  const moved = lit(theme, key);
  return h('button', {
    type: 'button', class: `rl-cap-piece${size ? ` g${size}` : ''}${moved ? ` lit ${moved.n < 0 ? 'down' : 'up'}` : ''}`,
    'data-key': `piece:${key}`, 'data-group': key, 'aria-pressed': String(picked),
    'aria-label': `${name}${sub ? `, ${sub}` : ''}, support ${step} of 5${moved ? `; ${theme.name} moves it ${moved.words}` : ''}. Pick it`,
    onclick: () => onPick(key),
  },
  h('span', { class: 'rl-cap-pname' }, name),
  sub ? h('span', { class: 'rl-cap-psub' }, sub) : null,
  steps(step),
  moved ? h('span', { class: 'rl-cap-plit', 'aria-hidden': 'true' }, `${moved.n < 0 ? '↓' : '↑'} ${Math.abs(moved.n)}`) : null);
}

/** The chamber's blocs as pieces sized by seats, then the groups outside every chamber as a second row. */
function pieces(home, chamber, { theme, pick, onPick }) {
  const total = chamber.blocs.reduce((n, b) => n + b.seats, 0);
  const seated = new Set((home.chambers ?? []).flatMap((c) => c.blocs.map((b) => b.group)));
  const outside = (home.groups ?? []).filter((g) => !seated.has(g.key));
  return [
    h('h4', { class: 'rl-cap-h' }, 'Blocs in the chamber, by seats'),
    h('div', { class: 'rl-cap-pieces rl-cap-blocs' }, chamber.blocs.map((b) => piece({
      key: b.group, name: b.name, sub: plural(b.seats, 'seat'), support: b.support, size: grow(b.seats, total), theme, picked: pick === b.group, onPick,
    }))),
    outside.length ? [
      h('h4', { class: 'rl-cap-h' }, 'Outside the chamber: they move the blocs'),
      h('div', { class: 'rl-cap-pieces rl-cap-groups' }, outside.map((g) => piece({
        key: g.key, name: g.name, sub: g.kind, support: g.support, theme, picked: pick === g.key, onPick,
      }))),
    ] : null,
  ];
}

/** A vote as a track: yeas from the left by bloc, nays from the right, those not yet counted between, and the line that carries it. */
function track(chamber, v) {
  const total = chamber.blocs.reduce((n, b) => n + b.seats, 0);
  const order = chamber.blocs.map((b) => b.group);
  const counts = new Map((v.blocs ?? []).map((b) => [b.group, b]));
  const named = new Map(chamber.blocs.map((b) => [b.group, b.name]));
  const yeas = [];
  let at = 0;
  order.forEach((g, i) => {
    const w = share(counts.get(g)?.yeas ?? 0, total);
    if (w > 0) yeas.push(svg('rect', { class: `rl-cap-yea b${i % 7}`, 'data-group': g, x: at, y: 0, width: w, height: 10 }));
    at += w;
  });
  const nays = [];
  let right = 100;
  order.forEach((g, i) => {
    const w = share(counts.get(g)?.nays ?? 0, total);
    right -= w;
    if (w > 0) nays.push(svg('rect', { class: `rl-cap-nay b${i % 7}`, 'data-group': g, x: right, y: 0, width: w, height: 10 }));
  });
  const open = Math.max(0, right - at);
  const line = Number.isFinite(v.carries);
  const byBloc = (v.blocs ?? []).map((b) => `${named.get(b.group) ?? b.group} ${b.yeas} yea, ${b.nays} nay`).join('; ');
  return h('div', { class: 'rl-cap-trackbox' },
    line ? h('p', { class: 'rl-cap-carryword' }, `${v.carries} carry it`) : null,
    svg('svg', {
      class: 'rl-cap-track', viewBox: '0 0 100 10', preserveAspectRatio: 'none', role: 'img', focusable: 'false',
      'aria-label': `${v.yeas} yea and ${v.nays} nay of ${total} seats, the rest not yet counted${line ? `; ${v.carries} carry it` : ''}. By bloc: ${byBloc}`,
    }, yeas, open > 0 ? svg('rect', { class: 'rl-cap-open', x: at, y: 0, width: open, height: 10 }) : null, nays, carryLine(v.carries, total)),
    h('p', { class: 'rl-cap-count' }, `${v.yeas} yea · ${v.nays} nay`));
}

// --- the middle: who decides -------------------------------------------------------------------

/** A roster line by name: `{ line, tab }`, or null when the roster has nobody of that name. */
function rosterLine(rv, name) {
  for (const tab of ['yours', 'others', 'opponents']) {
    const line = (rv?.people?.[tab] ?? []).find((l) => l.name === name);
    if (line) return { line, tab };
  }
  return null;
}

/** The people a vote passes through: the decision steps of the seat's order, as the orders log names them, found in the roster. */
function stepsOf(rv, orderId) {
  const order = (rv?.orders?.orders ?? []).find((o) => o.id === orderId);
  const names = [...new Set((order?.steps ?? []).filter((s) => s.kind === 'decision').map((s) => s.person))];
  return names.map((n) => rosterLine(rv, n)).filter(Boolean);
}

function tokens(found, onPerson, label = 'Who it passes through', cls = 'rl-cap-people') {
  if (!found.length) return null;
  return h('section', { class: cls, 'aria-label': label },
    h('h4', { class: 'rl-cap-h' }, label),
    h('ul', { class: 'rl-cap-tokens', role: 'list' }, found.map(({ line, tab }) => h('li', {}, personToken(line, tab, { onOpen: onPerson })))));
}

// --- the middle: each kind of question ---------------------------------------------------------------

function voteMiddle(rv, q, state, on) {
  const home = ownHome(rv);
  const votes = q.measure.votes ?? [];
  const at = Math.min(state.vote ?? 0, Math.max(0, votes.length - 1));
  const v = votes[at];
  const chamber = (home.chambers ?? []).find((c) => c.key === v?.vote) ?? q.chamber;
  return [
    votes.length > 1 ? h('div', { class: 'rl-cap-votesteps', role: 'group', 'aria-label': 'Its votes' }, votes.map((x, i) => h('button', {
      type: 'button', class: 'rl-cap-votestep', 'data-key': `vote-step:${i}`, 'aria-pressed': String(i === at), onclick: () => on.vote(i),
    }, h('span', {}, capital(chamberName(x.vote))),
    h('span', { class: 'rl-cap-stepcount' }, `${x.yeas} yea${Number.isFinite(x.carries) ? ` · ${x.carries} carry it` : ''}`)))) : null,
    tokens(stepsOf(rv, q.measure.order_id), on.person),
    v ? track(chamber, v) : null,
    pieces(home, chamber, { theme: on.theme, pick: state.pick, onPick: on.pick }),
  ];
}

function chamberMiddle(rv, key, state, on) {
  const home = ownHome(rv);
  const chamber = (home?.chambers ?? []).find((c) => c.key === key);
  if (!chamber) return null;
  return [h('h3', { class: 'rl-cap-title' }, capital(chamberName(key))), pieces(home, chamber, { theme: on.theme, pick: state.pick, onPick: on.pick })];
}

/** The map's mark for a held order's piece, as the server keyed it; null for none. */
const markFor = (rv, key) => (key ? (rv?.map?.marks ?? []).find((m) => m.piece?.key === key) ?? null : null);

/** The words between two links of a chain. */
const link = (word) => h('p', { class: 'rl-cap-link' }, word);

/** Who decides a held order, as its shape: one person and those with access, or a council at its table, or the chambers above. */
function deciderShape(rv, l, onPerson) {
  const one = rosterLine(rv, l.who);
  if (one) {
    const access = (rv?.people?.yours ?? []).filter((p) => p.name !== l.who).map((line) => ({ line, tab: 'yours' }));
    return h('section', { class: 'rl-cap-one', 'aria-label': 'One person decides' },
      h('h4', { class: 'rl-cap-h' }, 'One person decides'),
      h('ul', { class: 'rl-cap-tokens', role: 'list' }, h('li', {}, personToken(one.line, one.tab, { onOpen: onPerson }))),
      tokens(access, onPerson, 'Those with access', 'rl-cap-people rl-cap-access'));
  }
  if (ownHome(rv)?.chambers?.length) return null; // the chambers are in the head
  return h('section', { class: 'rl-cap-council', 'aria-label': 'A council decides' },
    h('h4', { class: 'rl-cap-h' }, 'A council decides'),
    h('div', { class: 'rl-cap-table' }, h('p', { class: 'rl-cap-tablename' }, l.who)),
    h('p', { class: 'rl-cap-note' }, 'Who sits on it is not in your view.'));
}

function heldMiddle(rv, q, on) {
  const l = q.held;
  const mark = markFor(rv, l.piece);
  return [
    h('p', { class: 'rl-cap-note' }, 'A lock on the map and a question here are the same thing seen from two sides. Each opens the other.'),
    h('ol', { class: 'rl-cap-chain', 'aria-label': 'The chain' },
      h('li', { class: 'rl-cap-link-box' },
        h('p', { class: 'rl-cap-h' }, 'The order'),
        h('p', { class: 'rl-cap-qtitle' }, l.words),
        h('p', { class: 'rl-cap-note' }, `Held since ${worldDate(l.held)}`),
        mark ? h('button', { type: 'button', class: 'rl-cap-tomap', 'data-key': 'to-map', onclick: () => on.map(mark) }, `Show ${mark.name} on the map`) : null),
      h('li', {}, link('held by')),
      h('li', { class: 'rl-cap-link-box' },
        h('p', { class: 'rl-cap-h' }, 'What holds it'),
        h('p', { class: 'rl-cap-qtitle' }, l.who),
        l.reason ? h('p', { class: 'rl-cap-note' }, l.reason) : null),
      h('li', {}, link('released by')),
      h('li', { class: 'rl-cap-link-box' },
        h('p', { class: 'rl-cap-h' }, 'The question'),
        l.asked
          ? h('p', { class: 'rl-cap-qtitle' }, `You have asked ${l.who} for leave`)
          : [h('p', { class: 'rl-cap-qtitle' }, `Whether ${l.who} gives leave`),
            h('button', { type: 'button', class: 'primary rl-cap-ask', 'data-key': 'ask', onclick: () => on.ask(l) }, `Ask ${l.who}`)])),
    deciderShape(rv, l, on.person),
  ];
}

function askMiddle(rv, q, on) {
  const a = q.ask;
  return [
    h('section', { class: 'rl-cap-one', 'aria-label': 'One person decides' },
      h('h4', { class: 'rl-cap-h' }, 'One person decides: you'),
      tokens([rosterLine(rv, a.by)].filter(Boolean), on.person, 'Who asks')),
    h('p', {}, `${a.by} asks for your leave to send this order. Asked ${worldDate(a.asked)}.`),
    h('button', { type: 'button', class: 'primary rl-cap-openask', 'data-key': 'open-ask', onclick: () => on.openAsk(a) }, 'Answer the ask'),
  ];
}

/** What a member of a conference has filed, as the view sends it. */
function filed(c, nation, mine) {
  const counted = (c.votes ?? []).find((v) => v.nation === nation);
  if (counted) return `Filed ${counted.vote}`;
  if (nation === mine) return c.vote ? `Your choice: ${c.vote}` : 'Your choice: not filed';
  return 'Sealed until the count';
}

function conferenceMiddle(rv, q, on) {
  const c = q.conference;
  const me = ownName(rv);
  const byName = new Map((rv?.home?.standings ?? []).map((s) => [s.nation.name, s.nation]));
  return [
    h('ul', { class: 'rl-cap-table rl-cap-seats', role: 'list', 'aria-label': 'Around the table' },
      (c.invited ?? []).map((name) => {
        const n = byName.get(name);
        return h('li', { class: `rl-cap-seat${name === me ? ' own' : ''}`, 'data-nation': name },
          flagBadge({ world: rv.world_key, key: n ? rv.nation_keys?.[n.key] ?? null : null, name, relation: n?.relation ?? (name === me ? 'own' : 'neutral') }, { height: 24 }),
          h('span', { class: 'rl-cap-pname' }, name),
          h('span', { class: 'rl-cap-psub' }, filed(c, name, me)));
      })),
    h('p', { class: 'rl-cap-note' }, [`Called by ${c.called_by}`, c.voting_day ? `the vote is on ${worldDate(c.voting_day)}` : null].filter(Boolean).join(' · ')),
    c.can_vote ? h('button', { type: 'button', class: 'primary rl-cap-confvote', 'data-key': 'conf-vote', onclick: () => on.conference(c) }, 'File your choice') : null,
  ];
}

function stakeMiddle(q) {
  if (q.kind === 'mandate') return h('p', {}, Number.isInteger(q.days) ? `Yours to carry out, ${plural(q.days, 'day')} left.` : 'Yours to carry out.');
  const s = q.contest;
  return [
    s.prize ? h('p', {}, s.prize) : null,
    h('ul', { class: 'rl-cap-table rl-cap-seats', role: 'list', 'aria-label': 'The sides' },
      (s.sides ?? []).map((side) => h('li', { class: 'rl-cap-seat' }, h('span', { class: 'rl-cap-pname' }, side)))),
    s.lean?.favours ? h('p', { class: 'rl-cap-note' }, `Leans to ${s.lean.favours}`) : null,
  ];
}

// --- the right column, and the seat's moves -----------------------------------------------------

function pickedCard(rv, q, state, on) {
  const home = ownHome(rv);
  const key = state.pick;
  const g = (home?.groups ?? []).find((x) => x.key === key);
  const bloc = (home?.chambers ?? []).flatMap((c) => c.blocs).find((b) => b.group === key);
  if (!g && !bloc) return h('p', { class: 'rl-cap-note' }, 'Pick a bloc, a group or a person on the board.');
  const v = q?.kind === 'vote' ? q.measure.votes?.[Math.min(state.vote ?? 0, q.measure.votes.length - 1)] : null;
  const count = v ? (v.blocs ?? []).find((b) => b.group === key) : null;
  const themes = themesFor(home, key);
  return h('section', { class: 'rl-cap-card', 'data-group': key, 'aria-label': (g ?? bloc).name },
    h('h4', {}, (g ?? bloc).name),
    count ? h('p', { class: 'rl-cap-oncount' }, `On this vote: ${count.yeas} yea, ${count.nays} nay`) : null,
    bloc ? h('p', {}, `${bloc.seats} seats`) : null,
    h('p', { class: 'rl-cap-moved' }, g ? (moveWords(g.last_moved) ?? 'Not moved yet') : 'Not moved yet'),
    h('p', { class: 'rl-cap-themes' }, themes.length ? `Moved by: ${themes.join(', ')}` : 'No theme moves it'),
    h('button', { type: 'button', class: 'rl-cap-speak', 'data-key': 'speak-card', onclick: () => on.speak() }, 'Speak to the nation'));
}

function sideColumn(rv, q, state, on) {
  return h('aside', { class: 'rl-cap-side', 'aria-label': 'Picked, and what you hold and owe' },
    h('h3', { class: 'rl-cap-h' }, 'Picked'),
    pickedCard(rv, q, state, on),
    h('h3', { class: 'rl-cap-h' }, 'You hold and owe'),
    h('p', { class: 'rl-cap-owed' }, OWED_NONE));
}

function movesRow(home, state, on) {
  const themes = home?.themes ?? [];
  if (!themes.length) return null;
  return h('section', { class: 'rl-cap-moves', 'aria-label': 'Your moves' },
    h('h3', { class: 'rl-cap-h' }, 'Your moves: speak, and see what it would move'),
    h('div', { class: 'rl-cap-movecards' }, themes.map((t) => h('button', {
      type: 'button', class: 'rl-cap-move', 'data-key': `theme:${t.key}`, 'aria-pressed': String(state.theme === t.key),
      'aria-label': `${t.name}: moves ${plural(Object.keys(t.moves ?? {}).length, 'group')}. Show what it would move`,
      onclick: () => on.themePick(t.key),
    }, h('span', { class: 'rl-cap-pname' }, t.name), h('span', { class: 'rl-cap-psub' }, `moves ${plural(Object.keys(t.moves ?? {}).length, 'group')}`)))),
    state.theme ? h('button', { type: 'button', class: 'primary rl-cap-speak', 'data-key': 'speak-move', onclick: () => on.speak() }, 'Speak to the nation') : null);
}

// --- the board ----------------------------------------------------------------------------------

/** Whether the board stands in the room's full screen: the room marks its root. */
const isFull = (el) => Boolean(el?.closest?.('.rl-full'));

function fullControl(onToggle) {
  return h('button', { type: 'button', class: 'rl-cap-full', 'data-key': 'full', onclick: onToggle },
    svg('svg', { class: 'rl-cap-full-glyph', viewBox: '0 0 16 16', width: 16, height: 16, 'aria-hidden': 'true', focusable: 'false' },
      svg('path', { d: 'M1 5V1h4M11 1h4v4M15 11v4h-4M5 15H1v-4' })),
    h('span', { class: 'rl-cap-full-in' }, 'Full screen'),
    h('span', { class: 'rl-cap-full-out' }, 'Leave full screen'));
}

/**
 * The Capital board for the seat's view `rv`. `state` is the room's `{ q, vote, pick, theme }`,
 * kept across redraws. `on`: `board(key)` (the switch), `person(line, tab)` (a token's figure
 * card), `map(mark)` (a held order's piece on the map), `ask(held)` (ask for a held order),
 * `openAsk(ask)` (the ask put before the seat), `conference(c)` (its form), `speak()` (Speak to the
 * nation), `full(on)` (the room's full screen). Picks redraw the board in place.
 */
export function capitalBoard(rv, state, on = {}) {
  const section = h('section', { class: 'rl-cap', 'aria-label': 'The Capital', tabindex: '-1' });
  const draw = (focus) => {
    section.replaceChildren(...parts());
    if (focus) section.querySelector(`[data-key="${focus}"]`)?.focus();
  };
  const set = (change, focus) => { Object.assign(state, change); draw(focus); };
  const full = () => {
    const next = !isFull(section);
    browserFull(next);
    on.full?.(next);
  };
  const handlers = {
    vote: (i) => set({ vote: i }, `vote-step:${i}`),
    pick: (key) => set({ pick: state.pick === key ? null : key }, `piece:${key}`),
    themePick: (key) => set({ theme: state.theme === key ? null : key }, `theme:${key}`),
    person: (line, tab) => on.person?.(line, tab),
    map: (mark) => on.map?.(mark),
    ask: (l) => on.ask?.(l),
    openAsk: (a) => on.openAsk?.(a),
    conference: (c) => on.conference?.(c),
    speak: () => on.speak?.(),
  };
  function parts() {
    const home = ownHome(rv);
    const qs = capitalQuestions(rv);
    const chamberPick = String(state.q ?? '').startsWith('chamber:') ? state.q.slice(8) : null;
    const q = chamberPick ? null : qs.find((x) => x.key === state.q) ?? qs[0] ?? null;
    const theme = (home?.themes ?? []).find((t) => t.key === state.theme) ?? null;
    const ctx = { ...handlers, theme };
    const vote = state.vote ?? 0;
    const head = h('div', { class: 'rl-cap-head' },
      boardSwitch('capital', on.board),
      (home?.chambers ?? []).length ? h('div', { class: 'rl-cap-chambers', role: 'group', 'aria-label': 'The chambers' },
        home.chambers.map((c) => chamberBar(home, c, carriesIn(q, vote, c.key), chamberPick === c.key,
          () => set({ q: chamberPick === c.key ? null : `chamber:${c.key}`, pick: null }, `chamber:${c.key}`)))) : null,
      fullControl(full));
    const middle = chamberPick ? chamberMiddle(rv, chamberPick, state, ctx)
      : !q ? null
        : q.kind === 'vote' ? voteMiddle(rv, q, state, ctx)
          : q.kind === 'held' ? heldMiddle(rv, q, ctx)
            : q.kind === 'ask' ? askMiddle(rv, q, ctx)
              : q.kind === 'conference' ? conferenceMiddle(rv, q, ctx)
                : stakeMiddle(q);
    return [
      head,
      h('nav', { class: 'rl-cap-list', 'aria-label': 'Questions: the ground you hold or lose' },
        h('h3', { class: 'rl-cap-h' }, 'Questions: the ground you hold or lose'),
        h('ul', { role: 'list' }, qs.map((x) => questionRow(x, !chamberPick && x.key === q?.key, (key) => set({ q: key, vote: 0, pick: null }, key))))),
      h('div', { class: 'rl-cap-middle' },
        q && !chamberPick ? h('h3', { class: 'rl-cap-title' }, q.title) : null,
        q && !chamberPick ? h('p', { class: 'rl-cap-note' }, `${q.kindWords}, decided by ${q.decides}`) : null,
        middle,
        movesRow(home, state, ctx)),
      sideColumn(rv, chamberPick ? null : q, state, ctx),
    ];
  }
  section.addEventListener('keydown', (e) => {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key !== 'f' && e.key !== 'F') return;
    if (e.target?.closest?.('input, textarea, select')) return;
    e.preventDefault();
    full();
  });
  draw();
  // a browser full screen the board asked for is given back once the room has drawn it out of full screen (its Escape)
  const had = askedForFull();
  queueMicrotask(() => { if (had && section.isConnected && !isFull(section)) browserFull(false); });
  return section;
}
