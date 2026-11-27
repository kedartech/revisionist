// The opening crawl (split out of realism-intro.js): the scene-setting paragraphs, typed
// out letter by letter while the host's Begin runs and to every other player on first
// entry, and the phrases that say what Begin is doing.

import { h } from '../dom.js';
import { motionMs, reducedMotion, timers } from '../motion.js';

const CRAWL_MAX = 3;

const lines = (xs) => (Array.isArray(xs) ? xs.filter((x) => typeof x === 'string' && x.trim()).map((x) => x.trim()) : []);

/** The setting's crawl paragraphs: trimmed, empty ones dropped, at most three. */
export function crawlParagraphs(setting) {
  return lines(setting?.crawl).slice(0, CRAWL_MAX);
}

// The typing pace, from the room's motion sheet. [proposed] until Josh has read a crawl at this pace.
export const CHARS_PER_SECOND = 1000 / motionMs('crawl-char');
export const PAUSE_MS = motionMs('crawl-pause');

const realTimers = timers;

// A paragraph is three spans: the whole text for a screen reader, then the typed part and
// the part still to type, both hidden from it. The part still to type keeps its place unseen,
// so lines do not reflow and nothing below moves while the text comes in.
function paragraph(text, whole) {
  const typed = h('span', { class: 'rl-intro-typed', 'aria-hidden': 'true' }, whole ? text : '');
  const rest = h('span', { class: 'rl-intro-untyped', 'aria-hidden': 'true' }, whole ? '' : text);
  const el = h('p', {}, h('span', { class: 'rl-intro-said sr-only' }, text), typed, rest);
  return { el, chars: [...text], typed, rest };
}

// Types each paragraph a character per timer at CHARS_PER_SECOND, with PAUSE_MS between
// paragraphs; one timer is out at a time. `skip()` finishes the paragraph being typed and
// starts the pause; `stop()` drops the pending timer.
function typist(paras, timers) {
  let i = 0;
  let n = 0;
  let timer = null;
  let typing = false;
  const later = (fn, ms) => {
    timer = timers.set(() => {
      timer = null;
      fn();
    }, ms);
  };
  const stop = () => {
    if (timer !== null) timers.clear(timer);
    timer = null;
  };
  const show = () => {
    const { chars, typed, rest } = paras[i];
    typed.textContent = chars.slice(0, n).join('');
    rest.textContent = chars.slice(n).join('');
  };
  const next = () => {
    typing = false;
    i += 1;
    n = 0;
    if (i < paras.length) later(type, PAUSE_MS);
  };
  function type() {
    typing = true;
    n += 1;
    show();
    if (n < paras[i].chars.length) later(type, 1000 / CHARS_PER_SECOND);
    else next();
  }
  const skip = () => {
    if (!typing) return;
    stop();
    n = paras[i].chars.length;
    show();
    next();
  };
  if (paras.length) later(type, 1000 / CHARS_PER_SECOND);
  return { skip, stop };
}

const SKIP_KEYS = new Set(['Enter', ' ']);

/**
 * `<dialog class="rl-intro" aria-labelledby="rl-intro-title">`: an h2 `title` (the game's
 * name), the paragraphs inside `.rl-intro-crawl`, a `p.rl-intro-status[role=status]` the
 * caller writes progress into, and a "Continue" button. Continue, and the dialog's `cancel`
 * (Esc), call `onDone()` once, and only once the dialog is ready: `ready: false` holds both
 * until `markReady(dialog)`. Each paragraph types itself out after the one before it; a
 * click, Enter or Space finishes the paragraph being typed and does not touch Continue.
 * Closing the dialog stops the typing. Under reduced motion every paragraph is whole at once
 * and no timer is set. `timers` is `{ set(fn, ms), clear(id) }`, the page's timers by default.
 */
export function introCrawl({ title, paragraphs = [], ready = true, onDone, timers = realTimers } = {}) {
  let done = false;
  const finish = () => {
    if (done) return;
    done = true;
    onDone?.();
  };
  const still = reducedMotion();
  const paras = paragraphs.map((text) => paragraph(text, still));
  const typing = still ? null : typist(paras, timers);
  const dialog = h('dialog', {
    class: 'rl-intro',
    'aria-labelledby': 'rl-intro-title',
    'data-ready': ready ? '' : undefined,
    oncancel: (e) => {
      e.preventDefault();
      if (dialog.hasAttribute('data-ready')) finish();
    },
    onclose: () => typing?.stop(),
    onclick: () => typing?.skip(),
    onkeydown: (e) => {
      if (SKIP_KEYS.has(e.key)) typing?.skip();
    },
  },
    h('h2', { id: 'rl-intro-title' }, title ?? ''),
    h('div', { class: 'rl-intro-crawl' }, paras.map((p) => p.el)),
    h('p', { class: 'rl-intro-status', role: 'status', 'aria-live': 'polite' }),
    h('button', { type: 'button', class: 'rl-intro-continue', disabled: !ready, onclick: finish }, 'Continue'));
  return dialog;
}

/** Begin has finished: enable Continue, say so in the status line, and drop the phrases. */
export function markReady(dialog, text = 'Ready. Continue when you are.') {
  if (!dialog) return;
  dialog.setAttribute('data-ready', '');
  const cont = dialog.querySelector('.rl-intro-continue');
  if (cont) cont.disabled = false;
  dialog.querySelector('.rl-intro-status')?.replaceChildren(text);
  dialog.querySelector('.rl-intro-phrases')?.remove();
  cont?.focus();
}

/** The phrases shown while Begin runs, one at a time in the stylesheet. */
export const BEGIN_PHRASES = Object.freeze([
  'Drawing up the opening papers.',
  'Seating the cabinet and the staff.',
  'Setting the calendar.',
  "Sorting the first day's in-tray.",
  'Briefing your aide.',
  'Opening the first day.',
]);

/** A list of `phrases` (the Begin phrases by default), hidden from screen readers. */
export function beginStatus(phrases = BEGIN_PHRASES) {
  return h('ul', { class: 'rl-intro-phrases', 'aria-hidden': 'true' },
    phrases.map((p) => h('li', {}, p)));
}
