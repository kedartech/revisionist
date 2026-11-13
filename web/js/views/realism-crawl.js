// The opening crawl (split out of realism-intro.js): the scene-setting paragraphs shown
// while the host's Begin runs and to every other player on first entry, and the phrases
// that say what Begin is doing.

import { h } from '../dom.js';

const CRAWL_MAX = 3;

const lines = (xs) => (Array.isArray(xs) ? xs.filter((x) => typeof x === 'string' && x.trim()).map((x) => x.trim()) : []);

/** The setting's crawl paragraphs: trimmed, empty ones dropped, at most three. */
export function crawlParagraphs(setting) {
  return lines(setting?.crawl).slice(0, CRAWL_MAX);
}

// How long a paragraph holds before the next comes in, by length: about 3.5 words a
// second, at least 4 s and at most 14 s. Provisional until Josh has read a crawl at pace.
export const SHORT_MAX_WORDS = 14;
export const MEDIUM_MAX_WORDS = 28;
export const LONG_MAX_WORDS = 42;
export const HOLD_SECONDS = Object.freeze({ short: 4, medium: 8, long: 12, xlong: 14 });

/** The hold class for a paragraph of `words` words: `short`, `medium`, `long` or `xlong`. */
export function holdClass(words) {
  if (!(words > SHORT_MAX_WORDS)) return 'short';
  if (words <= MEDIUM_MAX_WORDS) return 'medium';
  if (words <= LONG_MAX_WORDS) return 'long';
  return 'xlong';
}

// Each paragraph starts once the ones before it have held: `rl-at-<s>` names that start,
// and the stylesheet carries one delay rule for each start three paragraphs can reach.
function timed(paragraphs) {
  let at = 0;
  return paragraphs.map((p) => {
    const hold = holdClass(p.split(/\s+/).filter(Boolean).length);
    const el = h('p', { class: `rl-hold-${hold} rl-at-${at}` }, p);
    at += HOLD_SECONDS[hold];
    return el;
  });
}

/**
 * `<dialog class="rl-intro" aria-labelledby="rl-intro-title">`: an h2 `title` (the game's
 * name), the paragraphs inside `.rl-intro-crawl`, a `p.rl-intro-status[role=status]` the
 * caller writes progress into, and a "Continue" button. Continue, and the dialog's `cancel`
 * (Esc), call `onDone()` once, and only once the dialog is ready: `ready: false` holds both
 * until `markReady(dialog)`. A click or key on the dialog shows every paragraph at once
 * (`data-shown`); it does not touch Continue. Under reduced motion the text is static (CSS).
 */
export function introCrawl({ title, paragraphs = [], ready = true, onDone } = {}) {
  let done = false;
  const finish = () => {
    if (done) return;
    done = true;
    onDone?.();
  };
  const showAll = () => dialog.setAttribute('data-shown', '');
  const dialog = h('dialog', {
    class: 'rl-intro',
    'aria-labelledby': 'rl-intro-title',
    'data-ready': ready ? '' : undefined,
    oncancel: (e) => {
      e.preventDefault();
      if (dialog.hasAttribute('data-ready')) finish();
    },
    onclick: showAll,
    onkeydown: showAll,
  },
    h('h2', { id: 'rl-intro-title' }, title ?? ''),
    h('div', { class: 'rl-intro-crawl' }, timed(paragraphs)),
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
