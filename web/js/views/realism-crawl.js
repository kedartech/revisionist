// The opening crawl (split out of realism-intro.js): the scene-setting paragraphs shown
// while the host's Begin runs and to every other player on first entry, and the phrases
// that say what Begin is doing. Unit Q5 builds the fade, the held Continue and the phrases.

import { h } from '../dom.js';

const CRAWL_MAX = 3;

const lines = (xs) => (Array.isArray(xs) ? xs.filter((x) => typeof x === 'string' && x.trim()).map((x) => x.trim()) : []);

/** The setting's crawl paragraphs: trimmed, empty ones dropped, at most three. */
export function crawlParagraphs(setting) {
  return lines(setting?.crawl).slice(0, CRAWL_MAX);
}

/**
 * `<dialog class="rl-intro" aria-labelledby="rl-intro-title">`: an h2 `title` (the game's
 * name), the paragraphs inside `.rl-intro-crawl`, a `p.rl-intro-status[role=status]` the
 * caller writes progress into, and a "Continue" button. Continue, and the dialog's `cancel`
 * (Esc), call `onDone()` once. Under reduced motion the text is static (CSS).
 * `ready` (default true): see unit Q5.
 */
// contract stub: `ready` is accepted and not yet acted on (unit Q5)
export function introCrawl({ title, paragraphs = [], ready = true, onDone } = {}) {
  void ready;
  let done = false;
  const finish = () => {
    if (done) return;
    done = true;
    onDone?.();
  };
  return h('dialog', {
    class: 'rl-intro',
    'aria-labelledby': 'rl-intro-title',
    oncancel: (e) => { e.preventDefault(); finish(); },
  },
    h('h2', { id: 'rl-intro-title' }, title ?? ''),
    h('div', { class: 'rl-intro-crawl' }, paragraphs.map((p) => h('p', {}, p))),
    h('p', { class: 'rl-intro-status', role: 'status', 'aria-live': 'polite' }),
    h('button', { type: 'button', class: 'rl-intro-continue', onclick: finish }, 'Continue'));
}

/** Begin has finished: let the player continue (unit Q5). */
// contract stub: writes the status line only, as before the split (unit Q5)
export function markReady(dialog, text = 'Ready. Continue when you are.') {
  dialog?.querySelector('.rl-intro-status')?.replaceChildren(text);
}

/** The phrases shown while Begin runs (unit Q5). */
// contract stub: an empty list (unit Q5)
export function beginStatus() {
  return h('ul', { class: 'rl-intro-phrases', 'aria-hidden': 'true' });
}
