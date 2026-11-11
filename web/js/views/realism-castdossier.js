// The dossier behind a cast card or a listed figure, on the character-select screen
// (Train 3 unit P3): full for a person with sidecar text, short for anyone else; "Play
// <name>" and Close.

import { h } from '../dom.js';
import { portraitNode } from './realism-dossier.js';

export const DRAW_NOTE = 'Drawing up their papers takes about a minute.';

const QUOTE = 'In their words';
const HISTORY = 'As history had it';
const NOT_BINDING = 'Not binding: you may do otherwise.';

const text = (x) => (typeof x === 'string' && x.trim() ? x : null);
const lines = (xs) => xs.map(text).filter(Boolean);
const one = (x) => lines([x]);

/**
 * The model for `person`, a roster entry (name, pitch, reach, taken, sides, dossier) or a
 * listed figure (name, title, side, power), with its `dossier` (a Dossier, or null):
 * `{ name, full, listed, sections }`.
 * - `full`: the dossier has a bio. `listed`: `person` is a listed figure, not a roster entry
 *   (it has `power` and no `pitch`).
 * - `sections`, `{ heading, lines }`, only those with content, in this order:
 *   Side (roster: the distinct `sides[].side` joined by " and "; figure: `side`),
 *   Title (figure only), Kind of power (figure only), Who they are (`pitch`),
 *   Their reach (`reach`), Your arena (`arena`), Biography (`bio`),
 *   As history had it (the `history` lines, then the line "Not binding: you may do otherwise."),
 *   In their words (“<quote>” then "— <source>"; left out when the quote has no source),
 *   A fact (`fact`).
 */
export function castDossierModel(person, dossier) {
  const p = person ?? {};
  const d = dossier ?? {};
  const listed = Boolean(text(p.power)) && !text(p.pitch);
  const sides = Array.isArray(p.sides) ? [...new Set(lines(p.sides.map((s) => s?.side)))] : [];
  const history = lines(Array.isArray(d.history) ? d.history : []);
  const quote = text(d.quote);
  const source = text(d.source);
  const words = quote && source ? [`“${quote}”`, `— ${source}`] : [];
  const sections = [
    ['Side', listed ? one(p.side) : one(sides.join(' and '))],
    ['Title', listed ? one(p.title) : []],
    ['Kind of power', listed ? one(p.power) : []],
    ['Who they are', one(p.pitch)],
    ['Their reach', one(p.reach)],
    ['Your arena', one(d.arena)],
    ['Biography', one(d.bio)],
    [HISTORY, history.length ? [...history, NOT_BINDING] : []],
    [QUOTE, words],
    ['A fact', one(d.fact)],
  ];
  return {
    name: text(p.name) ?? '',
    full: Boolean(text(d.bio)),
    listed,
    sections: sections.filter(([, ls]) => ls.length).map(([heading, ls]) => ({ heading, lines: ls })),
  };
}

function sectionNode(i, heading, ls) {
  const id = `rl-cd-h-${i}`;
  return h('section', { class: 'rl-cd-sec', 'aria-labelledby': id },
    h('h3', { id, class: 'rl-cd-h' }, heading),
    heading === QUOTE
      ? ls.map((line, j) => h('p', { class: j ? 'rl-cd-source' : 'rl-cd-quote' }, line))
      : heading === HISTORY
        ? [h('ul', { class: 'rl-cd-list' }, ls.slice(0, -1).map((line) => h('li', {}, line))),
          h('p', { class: 'rl-cd-note' }, ls.at(-1))]
      : ls.length > 1
        ? h('ul', { class: 'rl-cd-list' }, ls.map((line) => h('li', {}, line)))
        : h('p', {}, ls[0]));
}

/** The foot's transitions: `read` shows Play; a Play asks first (`confirm`), then Yes goes. */
export function playStep(step, event) {
  if (step === 'read' && event === 'play') return 'confirm';
  if (step === 'confirm' && event === 'back') return 'read';
  if (step === 'confirm' && event === 'yes') return 'go';
  return step;
}

/**
 * `<dialog class="rl-cd" aria-labelledby="rl-cd-title">`: `portraitNode(name, dossier, 'rl-cd')`,
 * the h2 name (`#rl-cd-title`), each section as an h3 plus a paragraph or a list, then the
 * foot. The foot reads: when `canPlay`, a primary button "Play <name>" that asks first; for a
 * listed figure, the `DRAW_NOTE` line beside it; and a Close button calling `onClose()`. Asking
 * swaps the foot for "Play <name>?", the `confirmNote` line when given, the `DRAW_NOTE` line for
 * a listed figure, a primary "Yes, play <name>" calling `onPlay(person)` once, and "Not yet",
 * which swaps back. Focus follows the primary button after each swap. The dialog's `close`
 * event (Esc) also calls `onClose()`.
 */
export function castDossier({ person, dossier = null, canPlay = true, confirmNote = null, onPlay, onClose } = {}) {
  const model = castDossierModel(person, dossier);
  let done = false;
  let step = 'read';
  const finish = () => {
    if (done) return;
    done = true;
    if (dialog.open) dialog.close();
    onClose?.();
  };
  const swap = (event) => {
    const next = playStep(step, event);
    if (next === step) return;
    step = next;
    if (next === 'go') {
      onPlay(person);
      return;
    }
    foot.replaceChildren(...(next === 'confirm' ? askFoot() : readFoot()).filter(Boolean));
    foot.querySelector('button.primary').focus();
  };
  const readFoot = () => [
    canPlay ? h('button', { type: 'button', class: 'primary', onclick: () => swap('play') }, `Play ${model.name}`) : null,
    canPlay && model.listed ? h('p', { class: 'rl-cd-note' }, DRAW_NOTE) : null,
    h('button', { type: 'button', class: 'ghost', onclick: finish }, 'Close'),
  ];
  const askFoot = () => [
    h('p', { class: 'rl-cd-ask' }, `Play ${model.name}?`),
    confirmNote ? h('p', { class: 'rl-cd-note' }, confirmNote) : null,
    model.listed ? h('p', { class: 'rl-cd-note' }, DRAW_NOTE) : null,
    h('button', { type: 'button', class: 'primary', onclick: () => swap('yes') }, `Yes, play ${model.name}`),
    h('button', { type: 'button', class: 'ghost', onclick: () => swap('back') }, 'Not yet'),
    h('button', { type: 'button', class: 'ghost', onclick: finish }, 'Close'),
  ];
  const foot = h('div', { class: 'rl-cd-foot' }, readFoot());
  const dialog = h('dialog', { class: 'rl-cd', 'aria-labelledby': 'rl-cd-title', onclose: finish },
    h('header', { class: 'rl-cd-head' },
      portraitNode(model.name, dossier, 'rl-cd'),
      h('h2', { id: 'rl-cd-title', class: 'rl-cd-name' }, model.name)),
    model.sections.map(({ heading, lines: ls }, i) => sectionNode(i, heading, ls)),
    foot);
  return dialog;
}
