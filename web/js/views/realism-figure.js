// The figure card: one card for any person, opened from a People roster row (and, from the
// boards, the same call). Groups in a fixed order, each drawn only when it holds something:
// Now, Toward you, What they can do, Their record with you, What moves them, and for a leader,
// Between you. Anyone else's last answer sits in their record, and a war in the head line.
// A meter is the staff's five-step read with a word; with nothing to go on it shows the word only.
// Loyalty, competence and topics are drawn on the Your people tab only, whatever the line holds.

import { h } from '../dom.js';
import { worldDate } from '../rules.js';
import { channelWord } from '../realism-rules.js';
import { portraitNode } from './realism-dossier.js';

const TREND = Object.freeze({ worse: 'Hardening', better: 'Easing', steady: 'No change' });
const AGE = Object.freeze({ firm: 'firm', dated: 'some weeks old', old: 'old news: it may have changed' });
const STANCE = Object.freeze({ opponents: 'Set against you', yours: 'One of your people' });
const TALLY = Object.freeze(['passed', 'hurried', 'held', 'amended', 'refused', 'leaked']);

const isMeter = (v) => Boolean(v) && typeof v === 'object' && typeof v.word === 'string';
const stepOf = (v) => (Number.isInteger(v.step) && v.step >= 1 && v.step <= 5 ? v.step : null);
const days = (n) => `${n} ${n === 1 ? 'day' : 'days'}`;
const texts = (xs) => (Array.isArray(xs) ? xs.filter((x) => typeof x === 'string' && x.trim()) : []);

/** "Hardening, as of 1 September 1941, some weeks old": the trend, then when the staff knew it. */
function when(m, trend) {
  const known = m.as_of ? `as of ${worldDate(m.as_of)}${m.confidence ? `, ${AGE[m.confidence] ?? m.confidence}` : ''}` : '';
  return [trend ? TREND[trend] : null, known].filter(Boolean).join(', ');
}

/** One row: label, a five-cell bar when the staff hold a step (no bar without), the word and when. */
function meterRow(label, m, trend = null) {
  const step = stepOf(m);
  const note = when(m, trend);
  return h('div', { class: `rl-fc-row${step ? '' : ' none'}` },
    h('span', { class: 'rl-fc-label' }, label),
    ' ',
    step
      ? h('span', { class: `rl-pp-bar step-${step}`, 'aria-hidden': 'true' },
        [1, 2, 3, 4, 5].map((n) => h('span', { class: n <= step ? 'rl-pp-cell on' : 'rl-pp-cell' })))
      : h('span', { class: 'rl-fc-nobar', 'aria-hidden': 'true' }),
    h('span', { class: 'rl-fc-word' }, m.word, note ? h('span', { class: 'rl-fc-when' }, ` · ${note}`) : null));
}

/** A row with words and no meter (load). */
function plainRow(label, text) {
  return h('div', { class: 'rl-fc-row plain' },
    h('span', { class: 'rl-fc-label' }, label),
    ' ',
    h('span', { class: 'rl-fc-nobar', 'aria-hidden': 'true' }),
    h('span', { class: 'rl-fc-word' }, text));
}

/** A labelled line of words: "At odds over" then its text. */
function fact(label, text) {
  return h('div', { class: 'rl-fc-fact' }, h('span', { class: 'rl-fc-label' }, label), ' ', h('span', {}, text));
}

function tags(label, xs) {
  return h('div', { class: 'rl-fc-fact' },
    h('span', { class: 'rl-fc-label' }, label),
    h('ul', { class: 'rl-fc-tags' }, xs.map((x) => h('li', { class: 'rl-fc-tag' }, x))));
}

/** A group with a heading, or null when none of `parts` holds anything. */
function grp(id, title, parts) {
  const body = parts.filter(Boolean);
  if (!body.length) return null;
  return h('section', { class: 'rl-fc-grp', 'aria-labelledby': id }, h('h3', { id, class: 'rl-fc-h' }, title), body);
}

function hold(o) {
  const stated = Number.isInteger(o.days) ? `; the step takes about ${days(o.days)}` : '';
  return h('li', { class: 'rl-fc-now' },
    h('strong', {}, `Holds your order: ${o.label}`),
    h('span', { class: 'rl-fc-when' }, ` since ${worldDate(o.since)}, ${days(o.held_days)}${stated}`),
    o.read ? h('span', { class: 'rl-fc-read' }, 'Staff read: ', h('strong', {}, o.read), ' · a read, not a promise') : null);
}

/** "Reached in person, within a day" or "Reached by cable, the same day". */
function reach(ch) {
  if (!ch?.channel) return null;
  const how = channelWord(ch.channel).toLowerCase();
  const time = ch.days === 0 ? 'the same day' : ch.days === 1 ? 'within a day' : `in ${days(ch.days)}`;
  return `Reached ${ch.channel === 'in_person' ? how : `by ${how}`}, ${time}`;
}

/**
 * The card for `line` (a People roster line) as seen from roster tab `tab` ('opponents' for a
 * leader weighed against the seat, 'yours' for the seat's own people, 'others'): a
 * `<dialog class="rl-dos rl-fc">` named by the person's name. `opts`: `{ dossier, onClose }`;
 * `dossier` (`{ portrait, credit }`) draws a portrait, else a tile with the initials.
 */
export function figureCard(line, tab, { dossier = null, onClose } = {}) {
  const id = 'rl-fc';
  const n = (s) => `${id}-${s}`;
  const own = tab === 'yours';
  const leader = tab === 'opponents';
  const meter = (key, label, trend) => (isMeter(line[key]) ? meterRow(label, line[key], trend) : null);
  const wants = own ? texts(line.wants) : [];
  const holdsTo = own ? texts(line.holds_to) : [];
  const holds = Array.isArray(line.holds) ? line.holds : [];
  const load = Number.isInteger(line.load) ? line.load : 0;
  const tally = line.tally && TALLY.some((k) => line.tally[k] > 0)
    ? h('p', { class: 'rl-fc-tally' }, TALLY.flatMap((k, i) => [i ? ' ' : null, h('span', {}, h('b', {}, String(line.tally[k] ?? 0)), ` ${k}`)]))
    : null;
  const over = texts(line.over);
  const answer = line.last_answer ? fact('Last answer', line.last_answer) : null;
  const war = !leader && line.at_war ? 'At war with you' : null;
  const sub = [line.bloc, STANCE[tab], war, reach(line.channel)].filter(Boolean).join(' · ');

  const dialog = h('dialog', { class: 'rl-dos rl-fc', 'aria-labelledby': n('title'), onclose: () => onClose?.() },
    h('header', { class: 'rl-dos-head rl-fc-head' },
      portraitNode(line.name, dossier, 'rl-fc'),
      h('div', { class: 'rl-fc-who' },
        h('h2', { id: n('title'), class: 'rl-dos-name' }, line.name),
        line.office ? h('p', { class: 'rl-fc-office' }, line.office) : null,
        sub ? h('p', { class: 'rl-fc-sub' }, sub) : null)),
    grp(n('now'), 'Now', [holds.length ? h('ul', { class: 'rl-fc-list' }, holds.map(hold)) : null]),
    grp(n('toward'), 'Toward you', [
      leader ? meter('stance', 'Stance', line.trend) : null,
      own ? meter('loyalty', 'Loyalty') : null,
      meter('regard', 'Regard'),
    ]),
    grp(n('can'), 'What they can do', [
      leader ? meter('power', 'Power') : null,
      own ? meter('competence', 'Competence') : null,
      leader && isMeter(line.power) ? null : meter('standing', 'Standing'),
      own || load > 0 ? plainRow('Load', load ? `${load} of your orders` : 'none of your orders') : null,
    ]),
    grp(n('record'), 'Their record with you', [
      meter('reliability', 'Reliability'), meter('pace', 'Pace'), tally, leader ? null : answer,
    ]),
    grp(n('moves'), 'What moves them', [
      wants.length ? tags('Wants', wants) : null,
      holdsTo.length ? tags('Holds to', holdsTo) : null,
    ]),
    leader
      ? grp(n('between'), 'Between you', [
        over.length ? fact('At odds over', over.join('; ')) : null,
        fact('War', line.at_war ? 'At war with you.' : 'Not at war with you.'),
        answer,
      ])
      : null,
    h('div', { class: 'rl-dos-foot' },
      h('button', { type: 'button', class: 'ghost', onclick: () => dialog.close() }, 'Close')));
  return dialog;
}
