// The wake player: once a wake has run, its steps from the catch-up reply (the server's
// playback feed, `steps` on each page) play on the seat's own map, one frame at a time: what
// moved against the seat first (papers, holders), then its own orders and pieces, then the
// stakes. Several wakes play in turn and end on the "when you come back" line. Reduced motion
// shows every frame still; Skip ends it. Nothing here reads or writes storage, and nothing
// touches the page on import.

import { h } from '../dom.js';
import { markKey } from '../realism-rules.js';
import { territoryDrawing } from './realism-territory.js';
import { dayWords } from './realism-wake.js';

/** How long each frame of the wake player is on screen, as the reel before it held each step. */
export const STEP_SECONDS = 4;

const text = (v) => (typeof v === 'string' && v.trim() ? v : null);

/** The order a wake's steps play in: what moved against the seat, then its own, then the stakes. */
export const PLAY_GROUPS = Object.freeze({ paper: 0, holder: 0, order: 1, move: 1, halt: 1, stake: 2 });

/** A wake's steps in play order, each group in the order the server gave; a kind not named in `PLAY_GROUPS` is not played. */
export function playOrder(steps) {
  return (Array.isArray(steps) ? steps : [])
    .map((step, i) => ({ step, i, group: PLAY_GROUPS[step?.kind] }))
    .filter((x) => x.group !== undefined)
    .sort((a, b) => a.group - b.group || a.i - b.i)
    .map((x) => x.step);
}

/** Every page's steps in play order, oldest wake first: `[{ page, step }]`. */
export function playFrames(pages) {
  const sorted = (Array.isArray(pages) ? pages : []).filter((p) => Number.isInteger(p?.number)).sort((a, b) => a.number - b.number);
  return sorted.flatMap((page) => playOrder(page.steps).map((step) => ({ page, step })));
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
    case 'stake': return `${step.name}: ${words(step.what)}`;
    default: return '';
  }
}

/** The areas a step lights on the map: where a piece left and entered, where it held, what changed hands. */
function lights(step) {
  if (step.kind === 'move') return { from: step.left, to: step.entered, piece: step.piece };
  if (step.kind === 'halt') return { from: step.area, to: step.to, piece: step.piece };
  if (step.kind === 'holder') return { to: step.area };
  return {};
}

/** The seat's own territory map, still, when it is a territory map and its shapes are here. */
function playMap(map, shapes) {
  if (!map?.areas?.length || !shapes?.areas) return null;
  return h('figure', { class: 'rl-plb-map', 'aria-label': 'Where forces moved' },
    territoryDrawing(map, shapes, { still: true, label: 'Where forces moved' }));
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
 * The wake player: `<section class="rl-plb">` with the seat's map (`map` over `shapes`, a
 * territory map only), the frames of `pages` (`playFrames`, each wake headed by its number
 * and day), the `comeBack` line last, and Skip. With motion, one frame more every
 * `STEP_SECONDS` (`tick(fn, ms)`, setTimeout by default), each move lit on the map; under
 * `reduced` motion every frame stands still at once. Skip, or the last frame, shows every
 * frame. Skip, and "To the map" after it, call `onEnd()`; with no `onEnd` (the What you missed
 * sheet, which has its own way out) the button goes once all is shown. Null when no page has a
 * step. Nothing here reads or writes storage.
 */
export function wakePlayer({ pages, map, shapes, record, comeBack, reduced = false, tick = setTimeout, onEnd } = {}) {
  const frames = playFrames(pages);
  if (!frames.length) return null;
  const fig = playMap(map, shapes);
  const items = [];
  const steps = [];
  let wake = null;
  for (const { page, step } of frames) {
    if (page !== wake) {
      wake = page;
      items.push(h('li', { class: 'rl-plb-wake', 'data-wake': String(page.number) }, page.opened ? `Wake ${page.number}: ${page.opened}` : `Wake ${page.number}`));
    }
    const li = h('li', { class: 'rl-plb-step', 'data-kind': step.kind, 'data-wake': String(page.number) },
      h('span', { class: 'rl-plb-on' }, dayWords(step.on)),
      h('span', { class: 'rl-plb-cap' }, stepLine(step, { map, record })));
    items.push(li);
    steps.push({ li, step });
  }
  items.push(h('li', { class: 'rl-plb-end' }, text(comeBack) ?? 'That is everything since you were last here.'));
  const now = h('p', { class: 'rl-plb-now', 'aria-live': 'polite' });
  const btn = h('button', { type: 'button', class: 'rl-plb-skip' }, 'Skip');
  const el = h('section', { class: `rl-plb${reduced ? ' still' : ''}`, 'aria-label': 'Each wake you have not watched, step by step' },
    fig, h('ol', { class: 'rl-plb-frames' }, items), now, h('div', { class: 'rl-plb-actions' }, btn));
  let at = 0;
  let done = reduced;
  const show = (li, on) => (on ? li.removeAttribute('hidden') : li.setAttribute('hidden', ''));
  const finish = () => {
    done = true;
    for (const li of items) show(li, true);
    for (const { li } of steps) li.removeAttribute('aria-current');
    light(fig, null);
    // in a sheet that has its own way out (no onEnd), nothing is left for the button to do
    if (onEnd) btn.textContent = 'To the map';
    else (btn.closest('.rl-plb-actions') ?? btn).remove();
  };
  const step = () => {
    if (done) return;
    if (at >= steps.length) { finish(); return; }
    const { li, step: s } = steps[at];
    for (const x of items.slice(0, items.indexOf(li) + 1)) show(x, true);
    for (const x of steps) x.li.removeAttribute('aria-current');
    li.setAttribute('aria-current', 'step');
    if (li.isConnected) li.scrollIntoView?.({ block: 'nearest' }); // a long playback keeps the frame now playing in sight
    now.textContent = li.querySelector('.rl-plb-cap')?.textContent ?? '';
    light(fig, s);
    at += 1;
    tick(step, STEP_SECONDS * 1000);
  };
  btn.addEventListener('click', () => {
    const ending = !done || btn.textContent === 'To the map';
    finish();
    if (ending) onEnd?.();
  });
  if (reduced) finish();
  else {
    for (const li of items) show(li, false);
    step();
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
