// The People roster (view.realism.people): the leaders weighed against the seat, the seat's own
// people and everyone else with an office, each as the seat's staff know them. A meter is a staff
// assessment in five steps with a word, never the engine's number; a meter with nothing to go on
// shows only its word. A row opens the person's dossier with everything the view holds on them.

import { h } from '../dom.js';
import { worldDate } from '../rules.js';
import { panelHead, seg } from './ui-kit.js';
import { portraitNode } from './realism-dossier.js';

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

const TREND = Object.freeze({ worse: 'Hardening', better: 'Easing', steady: 'No change' });
const AGE = Object.freeze({ firm: 'firm', dated: 'some weeks old', old: 'old news: it may have changed' });

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

function row(line, tab, onOpen) {
  return h('li', {},
    h('button', { type: 'button', class: 'rl-pp-row', onclick: () => onOpen?.(line, tab) },
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
      ? h('ul', { class: 'rl-pp-list', 'aria-label': on.label }, lines.map((l) => row(l, on.key, onOpen)))
      : h('p', { class: 'rl-none' }, on.empty));
}

/** "as of 1 September 1941, some weeks old", or '' with no date. */
function known(m) {
  if (!m.as_of) return '';
  return `as of ${worldDate(m.as_of)}${m.confidence ? `, ${AGE[m.confidence] ?? m.confidence}` : ''}`;
}

function section(id, heading, ...body) {
  return h('section', { class: 'rl-dos-sec', 'aria-labelledby': id },
    h('h3', { id, class: 'rl-dos-h' }, heading), body);
}

/**
 * The person's dossier: a `<dialog class="rl-dos rl-pp-dos">` with the office, every meter the
 * row's tab allows with its date and confidence, the stance's trend against the one the staff
 * knew before it, what the two are at odds over, war, and their last answer. Close calls `onClose`.
 */
export function personDossier(line, tab, { onClose } = {}) {
  const id = 'rl-pp-dos';
  const n = (s) => `${id}-${s}`;
  const parts = rowMeters(line, tab).map(({ key, label, meter: m }) => {
    const trend = key === 'stance' && line.trend ? TREND[line.trend] : null;
    const when = known(m);
    return h('li', { class: 'rl-pp-item' }, meter(label, m),
      trend || when ? h('span', { class: 'rl-pp-when' }, [trend, when].filter(Boolean).join(', ')) : null);
  });
  const dialog = h('dialog', { class: 'rl-dos rl-pp-dos', 'aria-labelledby': n('title'), onclose: () => onClose?.() },
    h('header', { class: 'rl-dos-head' },
      portraitNode(line.name, null, 'rl-dos'),
      h('h2', { id: n('title'), class: 'rl-dos-name' }, line.name)),
    line.office ? section(n('office'), 'Office', h('p', {}, line.office)) : null,
    parts.length ? section(n('staff'), 'As your staff judge them', h('ul', { class: 'rl-pp-items' }, parts)) : null,
    line.over?.length ? section(n('over'), 'At odds over', h('p', {}, line.over.join('; '))) : null,
    line.at_war ? section(n('war'), 'War', h('p', {}, 'At war with you.')) : null,
    line.last_answer ? section(n('answer'), 'Last answer', h('p', {}, line.last_answer)) : null,
    h('div', { class: 'rl-dos-foot' },
      h('button', { type: 'button', class: 'ghost', onclick: () => dialog.close() }, 'Close')));
  return dialog;
}
