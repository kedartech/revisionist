// The wake player: once a wake has run, its steps from the catch-up reply (the server's
// playback feed, `steps` on each page) play on the seat's own map as a clock of world days.
// Every own piece that moved moves at once, each for the days its step took; a refused step
// stops short; a battle's rounds, a territory changing hands, a piece raised and every paper,
// order and stake line come on their own days. Several wakes play in turn and end on the "when
// you come back" line. Reduced motion shows every frame still; Skip ends it. Nothing here reads
// or writes storage, and nothing touches the page on import.

import { h, svg } from '../dom.js';
import { fillIn, placeMark, worldClock } from '../map/motion.js';
import { markKey } from '../realism-rules.js';
import { territoryDrawing } from './realism-territory.js';
import { dayWords } from './realism-wake.js';

/** How long one world day of a wake takes on screen. [proposed] */
export const DAY_MS = 400;
/** The longest a wake's playback runs: a longer wake runs its clock faster. [proposed] */
export const WAKE_MS = 20_000;
/** How far toward its area a refused step carries the piece before it stops. [proposed] */
export const HALT_SHARE = 1 / 3;

/** The time one world day takes in a wake of `days` days. */
export const msPerDay = (days) => (days > 0 ? Math.min(DAY_MS, WAKE_MS / days) : DAY_MS);

const text = (v) => (typeof v === 'string' && v.trim() ? v : null);
const DAY = 86_400_000;
const dayOf = (iso) => (typeof iso === 'string' && /^\d{4}-\d{2}-\d{2}/.test(iso) ? Date.parse(`${iso.slice(0, 10)}T00:00:00Z`) / DAY : null);
const isoOf = (n) => new Date(Math.floor(n + 1e-6) * DAY).toISOString().slice(0, 10);

/** The order a wake's steps play in on one day: what moved against the seat, then its own, then the stakes. */
export const PLAY_GROUPS = Object.freeze({ paper: 0, holder: 0, round: 1, order: 1, move: 1, halt: 1, raised: 1, held: 1, stake: 2 });

/**
 * A wake's steps in play order, each group in the order the server gave; a kind not named in
 * `PLAY_GROUPS` is not played, nor is a `held` step with no line to show.
 */
export function playOrder(steps) {
  return (Array.isArray(steps) ? steps : [])
    .map((step, i) => ({ step, i, group: PLAY_GROUPS[step?.kind] }))
    .filter((x) => x.group !== undefined && (x.step.kind !== 'held' || text(x.step.line)))
    .sort((a, b) => a.group - b.group || a.i - b.i)
    .map((x) => x.step);
}

/** The day a step starts to play: a move its step's days before it entered, a refused step the day before. */
function startOf(step) {
  const on = dayOf(step.on);
  if (on === null) return null;
  if (step.kind === 'move') return on - (Number.isInteger(step.days) && step.days > 0 ? step.days : 1);
  return step.kind === 'halt' ? on - 1 : on;
}

/**
 * The world days page `page` plays over: { start, end }, from the first day a step of it starts
 * (or the wake's own days before its last step, when more) to its last step's day. Null when no
 * step has a day.
 */
export function wakeDays(page) {
  const steps = playOrder(page?.steps);
  const days = steps.map((s) => dayOf(s.on)).filter((d) => d !== null);
  if (!days.length) return null;
  const end = Math.max(...days);
  const starts = steps.map(startOf).filter((d) => d !== null);
  const passed = Number.isInteger(page.days_passed) && page.days_passed > 0 ? end - page.days_passed : end;
  return { start: Math.min(passed, ...starts), end };
}

/** Each round of the seat's own `battles` fought within `span`, as a step at its area. */
function roundSteps(battles, span) {
  if (!span) return [];
  return (Array.isArray(battles) ? battles : []).flatMap((b) => (b.rounds ?? [])
    .filter((r) => dayOf(r.on) !== null && dayOf(r.on) >= span.start && dayOf(r.on) <= span.end)
    .map((r) => ({ kind: 'round', on: r.on, area: b.area, name: b.name, own_lost: r.own_lost, enemy_lost: r.enemy_lost })));
}

/**
 * Every page's steps, oldest wake first, each wake in the order of its days (`playOrder` within a
 * day), with the rounds of the seat's own `battles` fought in its days: `[{ page, step }]`.
 */
export function playFrames(pages, battles = []) {
  const sorted = (Array.isArray(pages) ? pages : []).filter((p) => Number.isInteger(p?.number)).sort((a, b) => a.number - b.number);
  const day = (s) => dayOf(s.on) ?? -Infinity;
  return sorted.flatMap((page) => {
    const steps = playOrder(page.steps);
    if (!steps.length) return [];
    return [...steps, ...roundSteps(battles, wakeDays(page))].map((step, i) => ({ step, i }))
      .sort((a, b) => day(a.step) - day(b.step) || PLAY_GROUPS[a.step.kind] - PLAY_GROUPS[b.step.kind] || a.i - b.i)
      .map(({ step }) => ({ page, step }));
  });
}

const words = (s) => String(s ?? '').replaceAll('_', ' ');

/** One plain line for `step`, naming areas, pieces and orders as the seat's `map` and `record` do. */
export function stepLine(step, { map, record } = {}) {
  const area = (key) => (map?.areas ?? []).find((a) => a.key === key)?.name ?? null;
  const piece = (key) => (map?.marks ?? []).find((m) => markKey(m) === key || m.key === key)?.name ?? 'One of your forces';
  switch (step.kind) {
    case 'paper': return `A paper reached you: ${step.title}`;
    case 'holder': return `${area(step.area) ?? 'A territory'} passed to ${step.holder?.name}${step.was ? ` from ${step.was.name}` : ''}`;
    case 'order': {
      const asked = (record?.orders ?? []).find((o) => o.id === step.order)?.asked;
      return `${asked ? `Your order “${asked}”` : 'One of your orders'}: ${words(step.what)}`;
    }
    case 'move': {
      const from = area(step.left);
      const to = area(step.entered);
      return `${piece(step.piece)} moved${from ? ` from ${from}` : ''}${to ? ` to ${to}` : ''}`;
    }
    case 'halt': return `${piece(step.piece)} held in ${area(step.area) ?? 'its area'}: the step to ${area(step.to) ?? 'the next area'} was refused (${step.reason})`;
    case 'raised': return `${step.name} was raised at ${step.place}`;
    case 'round': return `A day's fighting at ${area(step.area) ?? step.name}`;
    case 'stake': return `${step.name}: ${words(step.what)}`;
    // one of the seat's own held orders, held or ended: the server writes the line from the seat's view
    case 'held': return text(step.line) ?? '';
    default: return '';
  }
}

/** A round's losses as pips: the seat's own lost, then what its report saw the enemy lose. */
function roundPips(step) {
  const pips = (n, cls) => Array.from({ length: Math.max(0, Math.trunc(Number(n) || 0)) }, () => h('span', { class: `rl-plb-pip ${cls}` }));
  return h('span', { class: 'rl-plb-pips', role: 'img', 'aria-label': `You lost ${step.own_lost}; the enemy was seen to lose ${step.enemy_lost}` },
    ...pips(step.own_lost, 'rl-plb-lost'), ...pips(step.enemy_lost, 'rl-plb-foe'));
}

/** The areas a step lights on the map: where a piece left and entered, where it held, what changed hands. */
function lights(step) {
  if (step.kind === 'move') return { from: step.left, to: step.entered, piece: step.piece };
  if (step.kind === 'halt') return { from: step.area, to: step.to, piece: step.piece };
  if (step.kind === 'holder' || step.kind === 'round') return { to: step.area };
  if (step.kind === 'raised') return { to: step.area, piece: step.piece };
  return {};
}

/** The pieces `frames` move or raise, by key: the drawing keeps them out of stacks. */
const movers = (frames) => new Set(frames.map(({ step }) => step).filter((s) => ['move', 'halt', 'raised'].includes(s.kind)).map((s) => s.piece));

/** The seat's own territory map, still, when it is a territory map and its shapes are here. */
function playMap(map, shapes, apart) {
  if (!map?.areas?.length || !shapes?.areas) return null;
  return h('figure', { class: 'rl-plb-map', 'aria-label': 'Where forces moved' },
    territoryDrawing(map, shapes, { still: true, label: 'Where forces moved', apart }));
}

function light(fig, step) {
  if (!fig) return;
  for (const c of ['rl-plb-from', 'rl-plb-to', 'rl-plb-piece']) for (const el of fig.querySelectorAll(`.${c}`)) el.classList.remove(c);
  const at = step ? lights(step) : {};
  if (at.from) for (const el of fig.querySelectorAll(`path.rl-area[data-area="${at.from}"]`)) el.classList.add('rl-plb-from');
  if (at.to) for (const el of fig.querySelectorAll(`path.rl-area[data-area="${at.to}"]`)) el.classList.add('rl-plb-to');
  if (at.piece) for (const el of fig.querySelectorAll(`[data-key="${at.piece}"]`)) el.classList.add('rl-plb-piece');
}

/**
 * Each piece's legs in a wake's `steps`, by key: [{ from, to, start, end, stop, halt }], in
 * the order of their days. A move runs its days to its area; a refused step runs a day toward
 * its area and stops `HALT_SHARE` of the way.
 */
function legsOf(steps) {
  const out = new Map();
  for (const s of steps) {
    if (s.kind !== 'move' && s.kind !== 'halt') continue;
    const end = dayOf(s.on);
    if (end === null) continue;
    const halt = s.kind === 'halt';
    const leg = { from: halt ? s.area : s.left, to: halt ? s.to : s.entered, start: startOf(s), end, stop: halt ? HALT_SHARE : 1, halt };
    out.set(s.piece, [...(out.get(s.piece) ?? []), leg]);
  }
  for (const legs of out.values()) legs.sort((a, b) => a.start - b.start || a.end - b.end);
  return out;
}

/** Where a piece on `legs` stands on world day `t`: { leg, share }; linear in time within a leg. */
function legAt(legs, t) {
  const now = legs.filter((l) => l.start <= t).at(-1);
  if (!now) return { leg: legs[0], share: 0 };
  const gone = now.end > now.start ? Math.min(1, (t - now.start) / (now.end - now.start)) : 1;
  return { leg: now, share: gone * now.stop };
}

/**
 * The wake player: `<section class="rl-plb">` with the seat's map (`map` over `shapes`, a
 * territory map only), the frames of `pages` (`playFrames`, with the rounds of the seat's own
 * `battles`, each wake headed by its number and day), the `comeBack` line last, and Skip. With
 * motion, each wake runs as a clock of world days (`msPerDay`, on `clock`: { now, frame }, the
 * page's by default) and the next follows it; under `reduced` motion every frame stands still
 * at once. Skip, or the last wake's end, shows every frame with every piece where the map stands
 * it. Skip, and "To the map" after it, call `onEnd()`; with no `onEnd` (the What you missed
 * sheet, which has its own way out) the button goes once all is shown. Null when no page has a
 * step. Nothing here reads or writes storage.
 */
export function wakePlayer({ pages, map, shapes, record, comeBack, battles, reduced = false, clock, onEnd } = {}) {
  const frames = playFrames(pages, battles);
  if (!frames.length) return null;
  const fig = playMap(map, shapes, movers(frames));
  const drawing = fig?.querySelector('svg') ?? null;
  const items = [];
  const wakes = [];
  for (const { page, step } of frames) {
    if (wakes.at(-1)?.page !== page) {
      const head = h('li', { class: 'rl-plb-wake', 'data-wake': String(page.number) }, page.opened ? `Wake ${page.number}: ${page.opened}` : `Wake ${page.number}`);
      items.push(head);
      wakes.push({ page, head, steps: [], span: wakeDays(page) });
    }
    const li = h('li', { class: 'rl-plb-step', 'data-kind': step.kind, 'data-wake': String(page.number) },
      h('span', { class: 'rl-plb-on' }, dayWords(step.on)),
      h('span', { class: 'rl-plb-cap' }, stepLine(step, { map, record })),
      step.kind === 'round' ? roundPips(step) : null);
    items.push(li);
    wakes.at(-1).steps.push({ li, step, day: dayOf(step.on) });
  }
  items.push(h('li', { class: 'rl-plb-end' }, text(comeBack) ?? 'That is everything since you were last here.'));
  const now = h('p', { class: 'rl-plb-now', 'aria-live': 'polite' });
  const bar = svg('rect', { class: 'rl-plb-clock-fill', x: 0, y: 0, width: 0, height: 4 });
  const said = h('span', { class: 'rl-plb-day-words' });
  const day = reduced ? null : h('p', { class: 'rl-plb-day' }, said,
    svg('svg', { class: 'rl-plb-clock', viewBox: '0 0 100 4', preserveAspectRatio: 'none', 'aria-hidden': 'true' },
      svg('rect', { class: 'rl-plb-clock-track', x: 0, y: 0, width: 100, height: 4 }), bar));
  const btn = h('button', { type: 'button', class: 'rl-plb-skip' }, 'Skip');
  const el = h('section', { class: `rl-plb${reduced ? ' still' : ''}`, 'aria-label': 'Each wake you have not watched, step by step' },
    fig, day, h('ol', { class: 'rl-plb-frames' }, items), now, h('div', { class: 'rl-plb-actions' }, btn));
  const show = (li, on) => (on ? li.removeAttribute('hidden') : li.setAttribute('hidden', ''));
  const keyed = (sel, key, attr = 'data-key') => (drawing ? [...drawing.querySelectorAll(sel)].filter((g) => g.getAttribute(attr) === key) : []);
  // what the playback changes on the drawing, put back as the map stands it between wakes and at the end
  const marks = new Map();
  const touch = (key) => {
    const g = keyed('.rl-tm-mark', key)[0];
    if (g && !marks.has(key)) marks.set(key, { g, x: g.getAttribute('data-x'), y: g.getAttribute('data-y'), tf: g.getAttribute('transform') });
  };
  const fills = [];
  let running = null;
  let done = reduced;
  const restore = () => {
    for (const { g, x, y, tf } of marks.values()) {
      g.setAttribute('data-x', x);
      g.setAttribute('data-y', y);
      if (tf !== null) g.setAttribute('transform', tf);
      g.removeAttribute('visibility');
      g.classList.remove('rl-plb-moving');
      g.classList.remove('rl-plb-refused');
    }
    for (const f of fills.splice(0)) f.stop();
    for (const p of drawing?.querySelectorAll('.rl-hold') ?? []) p.removeAttribute('fill-opacity');
    for (const p of drawing?.querySelectorAll('.rl-plb-battle') ?? []) p.classList.remove('rl-plb-battle');
  };
  const finish = () => {
    done = true;
    running?.stop();
    restore();
    for (const li of items) show(li, true);
    for (const li of items) li.removeAttribute('aria-current');
    light(fig, null);
    day?.remove();
    // in a sheet that has its own way out (no onEnd), nothing is left for the button to do
    if (onEnd) btn.textContent = 'To the map';
    else (btn.closest('.rl-plb-actions') ?? btn).remove();
  };
  /** Wake `n` on its clock: its pieces at their first places, then each world day as it comes. */
  const playWake = (n) => {
    if (done) return;
    const wake = wakes[n];
    if (!wake) { finish(); return; }
    restore();
    show(wake.head, true);
    const span = wake.span ?? { start: 0, end: 0 };
    const total = Math.max(1, span.end - span.start);
    const legs = legsOf(wake.steps.map((s) => s.step));
    const raised = wake.steps.filter((s) => s.step.kind === 'raised' && s.day !== null);
    for (const key of [...legs.keys(), ...raised.map((s) => s.step.piece)]) touch(key);
    for (const s of raised) marks.get(s.step.piece)?.g.setAttribute('visibility', 'hidden');
    for (const s of wake.steps) if (s.step.kind === 'holder') for (const p of keyed('.rl-hold', s.step.area, 'data-area')) p.setAttribute('fill-opacity', '0');
    const fired = new Set();
    const onDay = (d) => {
      if (done) return;
      const t = span.start + d;
      for (const [key, pieceLegs] of legs) {
        const { leg, share } = legAt(pieceLegs, t);
        if (drawing) placeMark(drawing, key, leg.from, leg.to, share);
        const g = marks.get(key)?.g;
        g?.classList.toggle('rl-plb-moving', share > 0 && share < leg.stop);
        g?.classList.toggle('rl-plb-refused', leg.halt && share >= leg.stop);
      }
      let latest = null;
      for (const s of wake.steps) {
        if (fired.has(s) || (s.day ?? span.start) > t + 1e-6) continue;
        fired.add(s);
        latest = s;
        show(s.li, true);
        if (s.step.kind === 'raised') {
          marks.get(s.step.piece)?.g.removeAttribute('visibility');
          if (drawing && !legs.has(s.step.piece)) placeMark(drawing, s.step.piece, s.step.area, s.step.area, 0);
        }
        if (s.step.kind === 'holder') for (const p of keyed('.rl-hold', s.step.area, 'data-area')) fills.push(fillIn(p, clock ?? {}));
        if (s.step.kind === 'round') for (const p of keyed('path.rl-area', s.step.area, 'data-area')) p.classList.add('rl-plb-battle');
      }
      if (latest) {
        for (const li of items) li.removeAttribute('aria-current');
        latest.li.setAttribute('aria-current', 'step');
        if (latest.li.isConnected) latest.li.scrollIntoView?.({ block: 'nearest' }); // a long playback keeps the frame now playing in sight
        now.textContent = latest.li.querySelector('.rl-plb-cap')?.textContent ?? '';
        light(fig, latest.step);
      }
      said.textContent = `The wake runs: ${dayWords(isoOf(t))}, day ${Math.min(total, Math.floor(d + 1e-6) + 1)} of ${total}`;
      bar.setAttribute('width', String(Math.round((Math.min(d, total) / total) * 1000) / 10));
    };
    running = worldClock({ days: total, msPerDay: msPerDay(total), onDay, onEnd: () => playWake(n + 1) }, clock ?? {});
  };
  btn.addEventListener('click', () => {
    const ending = !done || btn.textContent === 'To the map';
    finish();
    if (ending) onEnd?.();
  });
  if (reduced) finish();
  else {
    for (const li of items) show(li, false);
    playWake(0);
  }
  return el;
}

/**
 * The wake player in its own `<dialog class="rl-plb-dialog">`, headed with the wakes it
 * plays: `play`, a player already under way (a redraw keeps its place), or a new one from the
 * rest of the arguments, whose Skip, or "To the map" once it has played, closes the dialog.
 * Closing calls `onClose()`. Null when nothing plays.
 */
export function playbackDialog({ play, onClose, ...args } = {}) {
  let d = null;
  const shown = play ?? wakePlayer({ ...args, onEnd: () => { if (d?.open) d.close(); } });
  if (!shown) return null;
  const nums = playFrames(args.pages).map((f) => f.page.number);
  const title = nums.length && nums[0] !== nums.at(-1) ? `Wakes ${nums[0]} to ${nums.at(-1)}, as they happened` : `Wake ${nums[0]}, as it happened`;
  d = h('dialog', { class: 'rl-plb-dialog', 'aria-labelledby': 'rl-plb-title' },
    h('h2', { id: 'rl-plb-title' }, title), shown);
  d.addEventListener('close', () => onClose?.());
  return d;
}
