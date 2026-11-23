// The People roster (view.realism.people): the leaders weighed against the seat, the seat's own
// people and everyone else with an office, each as the seat's staff know them. A meter is a staff
// assessment in five steps with a word, never the engine's number; a meter with nothing to go on
// shows only its word. A tile opens the person's figure card with everything the view holds on them.

import { h } from '../dom.js';
import { panelHead, seg } from './ui-kit.js';
import { figureCard } from './realism-figure.js';
import { monogram, portraitSrc } from './realism-dossier.js';

export const PEOPLE_TABS = Object.freeze([
  { key: 'opponents', label: 'Opponents', empty: 'Nobody is set against you that your staff know of.' },
  { key: 'yours', label: 'Your people', empty: 'None of your own people are on file.' },
  { key: 'others', label: 'Others', empty: 'Nobody else is on file.' },
]);

const LABEL = Object.freeze({
  stance: 'Stance', loyalty: 'Loyalty', competence: 'Competence', reliability: 'Reliability', regard: 'Regard',
});

/** The meters a row shows, by tab. Loyalty and competence are card values the seat holds only on its own people. */
const ROW = Object.freeze({
  opponents: ['stance', 'regard', 'reliability'],
  yours: ['loyalty', 'competence', 'reliability', 'regard'],
  others: ['regard', 'reliability'],
});

const isMeter = (v) => Boolean(v) && typeof v === 'object' && typeof v.word === 'string';
const stepOf = (v) => (Number.isInteger(v.step) && v.step >= 1 && v.step <= 5 ? v.step : null);

/** `[{ key, label, meter }]`: the row's meters for `tab`, in order, each only where the line holds one. */
export function rowMeters(line, tab) {
  return (ROW[tab] ?? []).filter((k) => isMeter(line?.[k])).map((k) => ({ key: k, label: LABEL[k], meter: line[k] }));
}

/** One meter: its label and word, and a five-cell bar with the step as a class when the staff hold a step. */
export function meter(label, m) {
  const step = stepOf(m);
  return h('span', { class: `rl-pp-meter${step ? '' : ' none'}` },
    h('span', { class: 'rl-pp-label' }, label),
    ' ',
    h('span', { class: 'rl-pp-word' }, m.word),
    step
      ? h('span', { class: `rl-pp-bar step-${step}`, 'aria-hidden': 'true' },
        [1, 2, 3, 4, 5].map((n) => h('span', { class: n <= step ? 'rl-pp-cell on' : 'rl-pp-cell' })))
      : null);
}

/** The portrait the roster line names, or the person's own initials. */
function face(line) {
  const src = portraitSrc(line.portrait);
  return src
    ? h('img', { class: 'rl-pp-portrait', src, alt: line.name, loading: 'lazy' })
    : h('span', { class: 'rl-pp-mono', 'aria-hidden': 'true' }, monogram(line.name));
}

function tile(line, tab, onOpen) {
  return h('li', {},
    h('button', { type: 'button', class: 'rl-pp-row rl-pp-tile', onclick: () => onOpen?.(line, tab) },
      h('span', { class: 'rl-pp-face' }, face(line)),
      h('span', { class: 'rl-pp-who' },
        h('span', { class: 'rl-pp-name' }, line.name),
        h('span', { class: 'rl-pp-office' }, line.office)),
      h('span', { class: 'rl-pp-meters' }, rowMeters(line, tab).map((x) => meter(x.label, x.meter)))));
}

/**
 * The roster panel. `opts`: `{ tab, onTab(key), onOpen(line, tab) }`; `tab` is one of
 * PEOPLE_TABS' keys (anything else shows Opponents). An empty tab shows one plain line.
 */
export function peopleRoster(people, { tab, onTab, onOpen } = {}) {
  const on = PEOPLE_TABS.find((t) => t.key === tab) ?? PEOPLE_TABS[0];
  const lines = people?.[on.key] ?? [];
  return h('section', { class: 'rl-people panel', 'aria-label': 'People' },
    panelHead('People'),
    seg(PEOPLE_TABS.map((t) => ({ key: t.key, label: t.label, count: (people?.[t.key] ?? []).length })), on.key,
      (key) => onTab?.(key)),
    lines.length
      ? h('ul', { class: 'rl-pp-list rl-pp-tiles', 'aria-label': on.label }, lines.map((l) => tile(l, on.key, onOpen)))
      : h('p', { class: 'rl-none' }, on.empty));
}

/**
 * The person's figure card (`figureCard` in realism-figure.js): a `<dialog class="rl-dos rl-fc">`
 * with every group the row's tab allows; `dossier` gives it a portrait. Close calls `onClose`.
 */
export function personDossier(line, tab, { dossier = null, onClose } = {}) {
  return figureCard(line, tab, { dossier, onClose });
}
