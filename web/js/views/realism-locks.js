// Locks on the map, and the ask (LKM). With the game's `locks` rule on, the seat's data carries a
// `locks` block: its own held orders and the asks put before it. Whether an order would be held is
// the server's to say: each check is the `check` call's answer (allowed, locked or beyond), kept for
// the room's data it was asked under, so a re-read of the room asks again. The client works nothing
// out. A held order and an ask are drawn from the block alone, as text. Nothing here touches the
// page on import.

import { api } from '../api.js';
import { h, svg } from '../dom.js';
import { worldDate } from '../rules.js';

/** Whether the game has the `locks` rule on: the server sends the block only then. */
export const locksOn = (rv) => Boolean(rv?.locks);

/** The seat's own held orders, as the server sent them. */
export const heldLines = (rv) => rv?.locks?.held ?? [];

/** The asks put before the seat, as the server sent them. */
export const askLines = (rv) => rv?.locks?.asks ?? [];

/** The seat's held orders on map mark `mark`: those whose `piece` the server set to the mark's piece key. */
export function heldOn(rv, mark) {
  const key = mark?.piece?.key;
  return key ? heldLines(rv).filter((l) => l.piece === key) : [];
}

/** A held order's ask, in a word. */
export const heldStatus = (l) => (l.asked ? 'Asked' : 'Not asked');

/** A held order in words, as a map mark's label says it. */
export const heldWords = (l) => `Held order: ${l.words}, ${l.who} can allow it, ${l.asked ? 'asked' : 'not asked'}`;

/** A locked check in words: who can allow it. */
export const lockWords = (c) => `Locked: ${c.who} can allow it`;

const PADLOCK = 'M-3.5 -1V-3.2A3.5 3.5 0 0 1 3.5 -3.2V-1';

/** The padlock glyph, centred on (0, 0), `size` pixels high. */
function padlock(size) {
  const k = size / 12;
  return svg('g', { class: 'rl-lock-glyph', transform: `scale(${Math.round(k * 100) / 100})` },
    svg('path', { d: PADLOCK, class: 'rl-lock-shackle' }),
    svg('rect', { x: -5, y: -1, width: 10, height: 7, rx: 1.5, class: 'rl-lock-body' }));
}

/** The lock mark in a page: the padlock, then who can allow it as text. */
export function lockTag(who) {
  return h('span', { class: 'rl-lock' },
    svg('svg', { class: 'rl-lock-icon', width: 14, height: 14, viewBox: '-7 -7 14 14', 'aria-hidden': 'true', focusable: 'false' }, padlock(12)),
    h('span', { class: 'sr-only' }, 'Locked: '),
    h('span', { class: 'rl-lock-who' }, who));
}

/** The lock mark on the map, at (x, y) in pixels from a lit area's or a piece's centre: the padlock, and who when given. */
export function lockMark(who, x, y, fontSize) {
  return svg('g', { class: 'rl-tm-lock', transform: `translate(${x} ${y})`, 'aria-hidden': 'true' },
    padlock(fontSize),
    who ? svg('text', { x: fontSize * 0.75, y: fontSize * 0.35, 'font-size': fontSize, class: 'rl-lock-note' }, who) : null);
}

// --- the check: the server's answer, kept for the room's data it was asked under -------------

let checked = new WeakMap();

const keyOf = ({ lever, params }) => JSON.stringify([lever, Object.entries(params ?? {}).sort(([a], [b]) => (a < b ? -1 : 1))]);

/** Forget every check (tests). */
export function forgetChecks() { checked = new WeakMap(); }

/**
 * The server's check of filing `body` ({ lever, params }) now: `{ check, who, reason }`, or null
 * while it is out, when it failed, or with `locks` off (then nothing is asked). The first call for
 * a body asks the server once; `onArrive(changed)` is called when the answer is in, `changed`
 * saying whether it differs from the answer kept before. `fresh` asks again
 * even when an answer is kept (choosing an order runs the check).
 */
export function lockCheck(rv, body, onArrive, { fresh = false } = {}) {
  if (!locksOn(rv) || !body?.lever) return null;
  if (!checked.has(rv)) checked.set(rv, new Map());
  const kept = checked.get(rv);
  const key = keyOf(body);
  const was = kept.get(key);
  if (was?.out) {
    if (onArrive) was.waiting.push(onArrive);
    return was.answer ?? null;
  }
  if (was && !fresh) return was.answer;
  // a fresh check keeps the last answer shown until the new one is in
  const entry = { out: true, answer: was?.answer ?? null, waiting: onArrive ? [onArrive] : [] };
  kept.set(key, entry);
  const before = JSON.stringify(entry.answer);
  checkNow(body)
    .then((answer) => { entry.answer = answer; })
    .finally(() => {
      entry.out = false;
      // each waiting caller is told whether the answer differs from the one it was shown
      const changed = JSON.stringify(entry.answer) !== before;
      for (const fn of entry.waiting.splice(0)) fn(changed);
    });
  return entry.answer;
}

const answerOf = (r) => (r && !r.refused && typeof r.check === 'string' ? { check: r.check, who: r.who ?? null, reason: r.reason ?? '' } : null);

/** Ask the server's check of filing `body` now: a promise of `{ check, who, reason }`, or of null when it failed. */
export function checkNow(body) {
  return Promise.resolve()
    .then(() => api.realism('check', { lever: body.lever, params: { ...(body.params ?? {}) } }))
    .then(answerOf)
    .catch(() => null);
}

/** The check a form runs before it is sent, with `locks` on; null with it off (the form is sent as today). */
export const formCheck = (rv) => (locksOn(rv) ? checkNow : null);

/** The check kept for `body`, without asking. */
export const keptCheck = (rv, body) => (body?.lever ? checked.get(rv)?.get(keyOf(body))?.answer ?? null : null);

/** Whether a check says a lock holds the order. */
export const isLocked = (c) => c?.check === 'locked';

// --- choosing a locked order: file it to be held, or ask ---------------------------------------

/**
 * What a locked order offers: the reason the seat would be told, and two buttons, File it to be
 * held (`file()`) and Ask (`ask()`). `esc` is spread on each button.
 */
export function lockedChoice(c, { file, ask, esc = {} }) {
  return h('div', { class: 'rl-lock-choice', role: 'group', 'aria-label': lockWords(c) },
    h('p', { class: 'rl-lock-line' }, lockTag(c.who)),
    c.reason ? h('p', { class: 'rl-lock-reason' }, c.reason) : null,
    h('div', { class: 'rl-lock-acts' },
      h('button', { type: 'button', class: 'primary rl-lock-file', onclick: file, ...esc }, 'File it to be held'),
      h('button', { type: 'button', class: 'rl-lock-ask', onclick: ask, ...esc }, `Ask ${c.who}`)));
}

// --- the ask, as the decider opens it ------------------------------------------------------------

/** A form's terms in words, from the seat's desk: "Set watch (Zone Gulf, Order Guard)". */
export function termsWords(levers, form) {
  const lever = (levers ?? []).find((l) => l.name === form.lever);
  const terms = Object.entries(form.params ?? {}).map(([k, v]) => {
    const p = lever?.params?.find((x) => x.name === k);
    const choice = (p?.choices ?? []).find((c) => (c?.value ?? c) === v);
    return `${p?.label ?? k} ${choice?.label ?? v}`;
  });
  return terms.length ? `${form.label} (${terms.join(', ')})` : form.label;
}

/** The ask `id` put before the seat, or null once it is no longer there. */
export const askOf = (rv, id) => askLines(rv).find((a) => a.id === id) ?? null;

/** The ask sheet's title. */
export const ASK_TITLE = 'Asked for your leave';

/**
 * The ask `id` opened: who asks, the order's plain words, when it was asked, and each of the seat's
 * own forms that would allow it, each with a button that files it (`onFile({ lever, params })`);
 * where the seat has none, it says so. Null once the ask is gone.
 */
export function askSheet(rv, id, { onFile } = {}) {
  const a = askOf(rv, id);
  if (!a) return null;
  const forms = a.forms ?? [];
  return h('section', { class: 'rl-ask', 'data-ask': a.id, 'aria-label': `${a.by} asks for your leave` },
    h('p', { class: 'rl-ask-by' }, `${a.by} asks for your leave to send this order:`),
    h('p', { class: 'rl-ask-words' }, a.words),
    h('p', { class: 'rl-ask-when muted' }, `Asked ${worldDate(a.asked)}`),
    forms.length
      ? [h('p', { class: 'rl-ask-forms-h' }, forms.length === 1 ? 'Your own form that would allow it:' : 'Your own forms that would allow it:'),
        h('ul', { class: 'rl-ask-forms', role: 'list' }, forms.map((f) => {
          const said = termsWords(rv.desk?.levers, f);
          return h('li', { 'data-lever': f.lever },
            h('span', { class: 'rl-ask-form' }, said), ' ',
            h('button', {
              type: 'button', class: 'rl-btn rl-ask-file', 'aria-label': `File it: ${said}`,
              onclick: () => onFile?.({ lever: f.lever, params: { ...f.params } }),
            }, 'File it'));
        }))]
      : h('p', { class: 'rl-ask-none' }, 'None of your own forms allows it.'));
}
