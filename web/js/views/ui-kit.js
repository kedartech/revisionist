// The console's shared parts: pure builders through h(), one look for every panel that uses
// them. A tone is a word (ok, info, warn, danger, intel, quiet), never a colour; ui-kit.css
// turns `tone-<word>` into the part's --c accent. Every state carries a word as well.
// Nothing here touches the page on import.

import { h, icon } from '../dom.js';
import { stepLine } from '../realism-rules.js';

export const TONES = Object.freeze(['ok', 'info', 'warn', 'danger', 'intel', 'quiet']);

const toneOf = (tone) => `tone-${TONES.includes(tone) ? tone : 'quiet'}`;

/** A panel's title bar: the title, a count badge when `count` is a number, then `extra` nodes. */
export function panelHead(title, count = null, extra = []) {
  return h('div', { class: 'panel-head' },
    h('h2', {}, title),
    typeof count === 'number' ? h('span', { class: 'badge' }, String(count)) : null,
    h('span', { class: 'panel-gap', 'aria-hidden': 'true' }),
    extra);
}

/** A summary tile: a number, its label and an optional sub line; a button when `onPick` is given. */
export function tile(n, label, sub, tone, onPick) {
  const parts = [
    h('span', { class: 'tile-n' }, String(n)),
    h('span', { class: 'tile-text' },
      h('span', { class: 'tile-label' }, label),
      sub ? h('span', { class: 'tile-sub' }, sub) : null),
  ];
  return onPick
    ? h('button', { type: 'button', class: `tile ${toneOf(tone)}`, onclick: onPick }, parts)
    : h('div', { class: `tile ${toneOf(tone)}` }, parts);
}

/** A rounded status word with an outline (an order's state, a stance). */
export function chip(word, tone) {
  return h('span', { class: `chip ${toneOf(tone)}` }, word);
}

/** A small filled kind word (report, press, intercept, order, cable). */
export function tag(word, tone) {
  return h('span', { class: `tag ${toneOf(tone)}` }, word);
}

/**
 * A segmented filter: one pressed button per option `{ key, label, count? }`; a click calls
 * `onPick(key)`.
 */
export function seg(options, selected, onPick) {
  return h('div', { class: 'seg', role: 'group' },
    options.map((o) => h('button', {
      type: 'button',
      'aria-pressed': String(o.key === selected),
      onclick: () => onPick(o.key),
    }, o.label, typeof o.count === 'number' ? h('span', { class: 'n' }, ` ${o.count}`) : null)));
}

/**
 * An order's real steps by person (`StepLine`s): those acted on are done, the one at `at`
 * still waiting is here now, the rest are to come. Each says its state in words.
 */
export function stepper(steps, at) {
  return h('ol', { class: 'stepper' },
    steps.map((s) => {
      const state = s.action ? 'done' : s.step === at ? 'now' : 'next';
      return h('li', { class: `step ${state}`, 'aria-current': state === 'now' ? 'step' : null },
        h('span', { class: 'step-line' }, state === 'next' ? `${s.person}: to come` : stepLine(s)));
    }));
}

/** An alert box for a crisis: an icon, the title, the body and any action buttons. */
export function alertBox(title, body, actions = []) {
  return h('section', { class: 'alert', 'aria-label': title },
    h('span', { class: 'alert-icon', 'aria-hidden': 'true' }, icon('alert', 18)),
    h('strong', { class: 'alert-title' }, title),
    body ? h('p', { class: 'alert-body' }, body) : null,
    actions.length ? h('div', { class: 'alert-acts' }, actions) : null);
}
