// The season on one timeline: in the map-first room, a strip along the foot of the map draws
// the season from today to its end as one line, with a mark at each dated thing the seat's view
// already carries, shaped by its kind (the seat's own, a conference, a contest, the season's
// end). A tap or Enter opens it to the same things as a list in date order; a row opens its item
// where it lives. The client works out no day: a mark's place is the difference of two days it
// was sent, or a count of days left it was sent. Nothing here touches the page on import.

import { h, svg } from '../dom.js';
import { markKey, shortDate } from '../realism-rules.js';
import { cameDue, cameDueIn, lastDrawn, play } from '../motion.js';
import { DUE_FLASH } from './realism-tracks.js';
import { dayKey } from './realism-wake.js';

/** The strip's words [proposed]. */
export const TIMELINE_TITLE = 'The season';
export const NO_END = 'Last dated day';
/** The most of the map's height the open list may cover [proposed]. */
export const TL_SHARE = 0.4;

/** The kinds a mark can be, in the order a tie on one day is listed. */
export const KINDS = ['own', 'conf', 'contest', 'end'];
const KIND_WORDS = { own: 'Yours', conf: 'Conference', contest: 'Contest', end: 'Season' };

const DAY = 86400000;
/** Whole days from `from` to `to` (ISO or in words); null when either cannot be read. */
export function daysBetween(from, to) {
  const a = dayKey(from);
  const b = dayKey(to);
  return a === null || b === null ? null : Math.round((b - a) / DAY);
}

/** A day as the list writes it: "26 Oct"; empty for none. */
function dayShort(day) {
  const key = dayKey(day);
  if (key === null) return '';
  return shortDate(new Date(key).toISOString().slice(0, 10));
}

const daysWord = (n) => (n === 0 ? 'Today' : `${n} d`);
const daysLong = (n) => (n === 0 ? 'today' : n === 1 ? 'in 1 day' : `in ${n} days`);

/** The seat's own pieces with a dated step: under way (the day it arrives) or an order still with a holder (the day its step falls due). */
function pieceMarks(rv, today) {
  const out = [];
  for (const m of rv.map?.marks ?? []) {
    if (m.side !== 'own' || !m.piece) continue;
    const course = m.piece.under_way;
    const wait = m.piece.waiting;
    const to = course?.path?.at(-1)?.name;
    const [day, what] = course?.arrives
      ? [course.arrives, to ? `${m.name} arrives at ${to}` : `${m.name} arrives`]
      : wait?.until ? [wait.until, wait.with_person ? `${m.name}: the order is with ${wait.with_person} to this day` : `${m.name}: the order's step is due`] : [];
    const days = day ? daysBetween(today, day) : null;
    if (days === null) continue;
    out.push({ kind: 'own', key: markKey(m), days, day, what, open: { to: 'piece', name: m.name } });
  }
  return out;
}

/** The conferences still to sit: the day one opens, when that is ahead, and its voting day. */
function conferenceMarks(rv, today) {
  const out = [];
  for (const c of rv.conferences?.conferences ?? []) {
    if (c.tallied) continue;
    const opens = daysBetween(today, c.called);
    if (opens !== null && opens > 0) out.push({ kind: 'conf', key: `conf-open:${c.key}`, days: opens, day: c.called, what: `Conference opens: ${c.text}`, open: { to: 'sheet', sheet: 'diplomacy' } });
    const votes = daysBetween(today, c.voting_day);
    if (votes !== null && votes >= 0) out.push({ kind: 'conf', key: `conf:${c.key}`, days: votes, day: c.voting_day, what: `Conference votes: ${c.text}`, open: { to: 'sheet', sheet: 'diplomacy' } });
  }
  return out;
}

/**
 * Every dated thing of the seat's view, as `{ marks, span, ended }`: each mark is `{ kind, key,
 * days, day, what, open }`, `days` from today (a count the view sent, or the difference of two
 * days it sent), `day` the date when the view sent one, `open` where its item lives. `span` is
 * the days to the season's end, or to the latest mark when the view sends no end (`ended`
 * false). `lines` are the room's lines of "What needs you".
 */
export function timelineMarks(rv, lines = []) {
  const today = rv.clock?.world_date ?? null;
  const conf = conferenceMarks(rv, today);
  const confKeys = new Set(conf.map((m) => m.key));
  const own = [];
  for (const line of lines) {
    if (!line.due || confKeys.has(`conf:${line.key}`)) continue; // a conference's vote is the conference's mark
    const days = daysBetween(today, line.due);
    if (days === null) continue;
    own.push({ kind: 'own', key: `need:${line.kind}:${line.key}`, days: Math.max(0, days), day: line.due, what: line.what, due: true, open: { to: 'need', line } });
  }
  const stakes = rv.stakes ?? {};
  for (const m of stakes.mandates ?? []) {
    // a mandate on the agenda is already a line of the list, on the same day
    if (own.some((o) => o.what === m.text && o.days === m.days_left)) continue;
    own.push({ kind: 'own', key: `mandate:${m.text}`, days: m.days_left, day: null, what: m.text, due: true, open: { to: 'aims' } });
  }
  const contests = (stakes.contests ?? []).map((c) => ({ kind: 'contest', key: `contest:${c.name}`, days: c.days_left, day: null, what: `${c.name} is decided`, open: { to: 'aims' } }));
  const ended = Number.isFinite(stakes.season_days_left);
  const end = ended ? [{ kind: 'end', key: 'end', days: stakes.season_days_left, day: null, what: 'The season ends', open: { to: 'aims' } }] : [];
  const marks = [...own, ...pieceMarks(rv, today), ...conf, ...contests, ...end]
    .filter((m) => Number.isFinite(m.days) && m.days >= 0)
    .map((m, i) => [m, i])
    .sort(([a, i], [b, j]) => a.days - b.days || KINDS.indexOf(a.kind) - KINDS.indexOf(b.kind) || i - j)
    .map(([m]) => m);
  const span = ended ? stakes.season_days_left : Math.max(0, ...marks.map((m) => m.days));
  return { marks, span, ended };
}

/** A mark's shape, drawn round (0, 0): a square for the seat's own, a diamond, a dot, a bar. */
function shape(kind) {
  if (kind === 'conf') return svg('polygon', { points: '0,-6 6,0 0,6 -6,0' });
  if (kind === 'contest') return svg('circle', { r: 5 });
  if (kind === 'end') return svg('rect', { x: -2, y: -7, width: 4, height: 14 });
  return svg('rect', { x: -5, y: -5, width: 10, height: 10 });
}

const markCls = (m) => `rl-tl-mark k-${m.kind}${m.due ? ' due' : ''}`;
const pct = (days, span) => `${span > 0 ? Math.min(100, (100 * days) / span).toFixed(2) : 0}%`;

/**
 * Whether mark `m` came due since the strip last drew it: by its day where it was sent one,
 * else by its days left reaching nought.
 */
const markCameDue = (m, today) => (m.day ? cameDue(`tl:${m.key}`, m.day, today) : cameDueIn(`tl:${m.key}`, m.days));

/**
 * One mark on the line. A mark that came due since the strip last drew marks itself once (a
 * promise's as the promise does on the Capital board); a mark new to the strip (`fresh`) drops
 * into its place.
 */
function axisMark(m, span, today, fresh) {
  const due = markCameDue(m, today);
  const el = svg('svg', { class: markCls(m), x: pct(m.days, span), y: '50%', overflow: 'visible', 'data-tl-key': m.key, 'data-came-due': due }, shape(m.kind));
  if (due) play(el, DUE_FLASH, m.key.startsWith('need:promise:') ? 'promise-due' : 'timeline-due');
  else if (fresh) play(el, [{ opacity: 0, transform: 'translateY(-10px)' }, { opacity: 1, transform: 'none' }], 'timeline-new', 'ease-out');
  return el;
}

/** The line: today's tick, then one mark per dated thing at its share of the span. */
function axis(found, today) {
  const was = lastDrawn('tl:keys', new Set(found.marks.map((m) => m.key)));
  return svg('svg', { class: 'rl-tl-axis', 'aria-hidden': 'true', focusable: 'false' },
    svg('line', { class: 'rl-tl-rule', x1: '0', x2: '100%', y1: '50%', y2: '50%' }),
    svg('svg', { class: 'rl-tl-today', x: '0', y: '50%', overflow: 'visible' }, svg('rect', { x: -1, y: -9, width: 2, height: 18 })),
    found.marks.map((m) => axisMark(m, found.span, today, Boolean(was) && !was.has(m.key))));
}

const rowMark = (m) => svg('svg', { class: markCls(m), viewBox: '-7 -7 14 14', width: 14, height: 14, 'aria-hidden': 'true', focusable: 'false' }, shape(m.kind));

/** Ticks under the open line, in days from today: nothing here is a day the view did not send. */
function ticks(span) {
  if (!(span > 0)) return null;
  const step = Math.max(1, Math.ceil(span / 6 / 7) * 7);
  const at = [];
  for (let d = 0; d < span; d += step) at.push(d);
  return h('div', { class: 'rl-tl-ticks', 'aria-hidden': 'true' },
    at.map((d) => h('span', { class: 'rl-tl-tick', 'data-days': String(d) }, d ? `${d} d` : 'Today')));
}

/** One row of the open list: the mark, the date when the view sent one, the thing, the days from today. */
function row(m, onOpen) {
  return h('li', {},
    h('button', {
      type: 'button', class: 'rl-tl-row', 'data-kind': m.kind, 'data-tl-key': m.key,
      'aria-label': `${KIND_WORDS[m.kind]}: ${m.what}, ${m.day ? `${dayShort(m.day)}, ` : ''}${daysLong(m.days)}`,
      onclick: () => onOpen?.(m),
    },
    rowMark(m),
    h('span', { class: 'rl-tl-when' }, m.day ? dayShort(m.day) : ''),
    h('span', { class: 'rl-tl-what' }, m.what),
    h('span', { class: 'rl-tl-in' }, daysWord(m.days))));
}

/**
 * `timelineStrip(rv, lines, { open, onToggle, onOpen })`: the strip for the map's foot, or null
 * when nothing in the view is dated. Its head is one button (Enter or a tap opens and closes
 * it); open, it lists the marks in date order and a row calls `onOpen(mark)`.
 */
export function timelineStrip(rv, lines, { open = false, onToggle, onOpen } = {}) {
  const found = timelineMarks(rv, lines);
  if (!found.marks.length) return null;
  const n = found.marks.length;
  const cap = found.ended ? `Season · ${found.span} days` : `${NO_END} · ${found.span} days`;
  const said = found.ended ? `${found.span} days to the season's end` : `${found.span} days to the last dated day; the season's end is not given`;
  const id = 'rl-tl-body';
  return h('section', { class: `rl-tl${open ? ' open' : ''}`, 'aria-label': TIMELINE_TITLE },
    h('button', {
      type: 'button', class: 'rl-tl-head', 'aria-expanded': String(open), 'aria-controls': id,
      'aria-label': `${TIMELINE_TITLE}: ${n} dated ${n === 1 ? 'thing' : 'things'}, ${said}`, onclick: () => onToggle?.(),
    },
    h('span', { class: `rl-tl-cap${found.ended ? '' : ' no-end'}` }, cap),
    axis(found, rv.clock?.world_date ?? null),
    h('span', { class: 'rl-tl-chev', 'aria-hidden': 'true' }, open ? '▾' : '▴')),
    open ? h('div', { class: 'rl-tl-body', id },
      ticks(found.span),
      h('ul', { class: 'rl-tl-list', role: 'list' }, found.marks.map((m) => row(m, onOpen)))) : null);
}

/**
 * Light a piece's mark on the strip and the piece on the map together: a pointer over or focus
 * on either lights both, by the piece's key. `section` holds the map and the strip.
 */
export function lightTogether(section) {
  const keyOf = (t) => {
    const el = t?.closest?.('[data-tl-key], .rl-tm-mark[data-key]');
    return el ? el.getAttribute('data-tl-key') ?? el.getAttribute('data-key') : null;
  };
  let lit = null;
  const light = (key) => {
    if (key === lit) return;
    lit = key;
    for (const el of [...section.querySelectorAll('.rl-lit')]) el.classList.remove('rl-lit');
    if (!key) return;
    for (const el of [...section.querySelectorAll('.rl-tm-mark'), ...section.querySelectorAll('[data-tl-key]')]) {
      if ((el.getAttribute('data-key') ?? el.getAttribute('data-tl-key')) === key) el.classList.add('rl-lit');
    }
  };
  for (const type of ['pointerover', 'focusin']) section.addEventListener(type, (e) => light(keyOf(e.target)));
  for (const type of ['pointerout', 'focusout']) section.addEventListener(type, () => light(null));
  return section;
}

/**
 * Cap the open list at `TL_SHARE` of the map's drawing as it is laid out (the stylesheet's cap,
 * a share of the map's whole section, is the bound until this has run): `--rl-tl-cap` on `section`.
 */
export function fitStrip(section) {
  const height = section.querySelector('svg.rl-map-svg')?.getBoundingClientRect?.().height;
  if (height > 0) section.style?.setProperty('--rl-tl-cap', `${Math.floor(TL_SHARE * height)}px`);
  return section;
}
