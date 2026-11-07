// The wake on the desk (Phase 4 unit C1): the header, how you play, the agenda, initiative,
// commit, the order the aide read and how each order landed. Built from view.realism
// (realism_api.py). Counts only: nothing here says who has committed.

import { h, icon } from '../dom.js';
import { worldDate } from '../rules.js';

const RUNNING = 'The wake is running. New papers are being written; this can take a minute…';

/** Each play style: its value, its word, and what it does. */
export const STYLES = Object.freeze([
  ['beginner', 'Beginner', 'Your aide offers a few ready orders for each matter.'],
  ['guided', 'Guided', 'Your aide offers a plan for each matter; you write the orders.'],
  ['free', 'Free', 'You write every order yourself.'],
]);

/**
 * "Closes Monday 2 November, 9 pm". The deadline is a real-world time, read in `timeZone`:
 * the reader's own when left out.
 */
export function deadlineWords(iso, timeZone) {
  if (!iso) return null;
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return null;
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    weekday: 'long', day: 'numeric', month: 'long', hour: 'numeric', minute: '2-digit', hourCycle: 'h12', timeZone,
  }).formatToParts(at).map((p) => [p.type, p.value]));
  const minutes = parts.minute === '00' ? '' : `:${parts.minute}`;
  return `Closes ${parts.weekday} ${parts.day} ${parts.month}, ${parts.hour}${minutes} ${parts.dayPeriod.toLowerCase()}`;
}

export function commitCount(wake) {
  const tail = wake.humans === 1 ? 'player committed' : 'players committed';
  return `${wake.committed} of ${wake.humans} ${tail}`;
}

/** Shown under the header while the wake is open and you have not committed; the aide plays the rest. */
export function commitHint(wake) {
  if (!wake.deadline || wake.you_committed) return null;
  return 'Your aide plays any seat that has not committed when the wake closes.';
}

/** The busy line for a commit: the last one runs the wake. */
export function commitBusy(wake) {
  return wake.committed + 1 >= wake.humans ? RUNNING : 'Sealing your orders…';
}

// The server words its dates, and worldDate cannot read words: only a bare ISO day goes through it.
export function dayWords(day) {
  return /^\d{4}-\d{2}-\d{2}$/.test(day ?? '') ? worldDate(day) : day ?? '';
}

export function itemHeading(item) {
  return item.issuer ? `${item.kind} from ${item.issuer}` : item.kind;
}

export function itemDates(item) {
  const issued = dayWords(item.issued);
  const due = dayWords(item.deadline);
  return [issued ? `Issued ${issued}` : null, due ? `Due by ${due}` : null].filter(Boolean).join(' · ');
}

/** What an item offers under a style: a beginner's options, a guided plan, or nothing. */
export function agendaList(style, item) {
  if (style === 'beginner') return item.options;
  return style === 'guided' ? item.plan : [];
}

export function agendaItems(agenda) {
  return agenda.style === 'free' ? [] : agenda.items;
}

/** The desk's matters: those with no issuer. A leader's request is a paper in the tray. */
export function deskMatters(agenda) {
  return agendaItems(agenda).filter((item) => !item.issuer);
}

export function optionLines(o) {
  return [o.to ? `To ${o.to}` : null, o.risk ? `Risk: ${o.risk}` : null].filter(Boolean);
}

export function answerWord(accepted) {
  if (accepted === null || accepted === undefined) return null;
  return accepted ? 'Agreed' : 'Declined';
}

/** A part of an order in words, as far as it has gone. */
export function partLines(p) {
  const applied = dayWords(p.applied);
  return [
    p.to ? `To ${p.to}` : null, p.route, p.fidelity, p.refused_under, p.reason,
    answerWord(p.accepted), applied ? `Landed ${applied}` : null,
  ].filter(Boolean);
}

export function orderHeading(p) {
  return p.parts.length ? 'Ready to sign' : 'This cannot be sent';
}

/** Who an order goes to and how; `channel` is already in words. */
export function orderAddress(p) {
  if (!p.person) return null;
  const how = p.channel?.toLowerCase();
  if (!how) return `To ${p.person}`;
  return `To ${p.person}, ${how === 'in person' ? how : `by ${how}`}`;
}

function commitButton(wake, act) {
  return h('button', {
    type: 'button', class: 'primary', onclick: () => act(commitBusy(wake), 'commit', {}),
  }, 'Commit my orders');
}

/** Commit only while a wake is open; the text once committed. */
function commitControl(wake, act) {
  if (!wake.deadline) return null;
  return wake.you_committed ? committed() : commitButton(wake, act);
}

function committed() {
  return h('span', { class: 'rl-committed' }, icon('check'), 'Committed');
}

/** The host's close, behind a confirm: closing runs the wake. */
function closeWake(act) {
  const dialog = h('dialog', { class: 'sheet rl-close-wake', 'aria-labelledby': 'rl-close-wake-h' },
    h('h2', { id: 'rl-close-wake-h' }, 'Close this wake?'),
    h('p', {}, 'It runs now, with the orders as they stand. The aide plays any seat that has not committed. This can take a minute.'),
    h('div', { class: 'row end' },
      h('button', { type: 'button', class: 'ghost', onclick: () => dialog.close() }, 'Cancel'),
      h('button', {
        type: 'button', class: 'danger',
        onclick: () => { dialog.close(); act(RUNNING, 'close', {}); },
      }, 'Close it')));
  return [
    h('button', { type: 'button', 'aria-haspopup': 'dialog', onclick: () => dialog.showModal() }, 'Close the wake now'),
    dialog,
  ];
}

/** The wake in the room's header: its number, when it closes, the count, commit and close. */
export function wakeHeader(wake, { act }) {
  const closes = deadlineWords(wake.deadline);
  return h('div', { class: 'rl-wake' },
    h('div', { class: 'stack' },
      h('span', { class: 'title' }, `Wake ${wake.wake}`),
      closes ? h('span', { class: 'muted rl-wake-line' }, closes) : null,
      h('span', { class: 'muted rl-wake-line', role: 'status', 'aria-live': 'polite' }, commitCount(wake))),
    commitControl(wake, act),
    wake.can_close ? closeWake(act) : null);
}

/** How the seat plays. Offers are made as a wake opens, so a change shows from the next. */
export function stylePicker(style, { act }) {
  return h('fieldset', { class: 'rl-style' },
    h('legend', {}, 'How you play'),
    STYLES.map(([value, word, note]) => {
      const id = `rl-style-${value}`;
      return h('div', { class: 'rl-style-choice' },
        h('label', { for: id },
          h('input', {
            type: 'radio', id, name: 'rl-style', value, checked: value === style, 'aria-describedby': `${id}-note`,
            onchange: () => act('Changing how you play…', 'style', { style: value }),
          }), word),
        h('p', { id: `${id}-note`, class: 'rl-style-note' }, note));
    }));
}

function optionBody(o) {
  return [
    h('p', { class: 'rl-offer-head' }, h('strong', {}, o.label),
      o.historical ? h('span', { class: 'rl-as-it-happened' }, 'As it happened') : null),
    optionLines(o).map((line) => h('p', { class: 'rl-offer-line' }, line)),
  ];
}

function optionList(options, act) {
  return h('ul', { class: 'rl-offers', role: 'list' }, options.map((o) => h('li', { class: 'rl-offer' },
    optionBody(o),
    h('button', {
      type: 'button', class: 'rl-btn', 'aria-label': `Choose: ${o.label}`,
      onclick: () => act('Filing it…', 'option', { pick: o.pick }),
    }, 'Choose'))));
}

function planSteps(steps) {
  return h('ol', { class: 'rl-plan' }, steps.map((o) => h('li', { class: 'rl-offer' }, optionBody(o))));
}

function agendaItem(item, style, act) {
  const listed = agendaList(style, item);
  let offered = null;
  if (listed.length) offered = style === 'beginner' ? optionList(listed, act) : planSteps(listed);
  return h('li', { class: 'rl-matter' },
    h('h3', {}, itemHeading(item)),
    h('p', { class: 'rl-matter-text' }, item.text),
    h('p', { class: 'rl-matter-dates' }, itemDates(item)),
    offered);
}

/** Each matter with no issuer, with its options or plan; hidden for a free player or when there is none. */
export function agendaPanel(agenda, { act }) {
  const items = deskMatters(agenda);
  if (!items.length) return null;
  return h('section', { class: 'rl-agenda', 'aria-labelledby': 'rl-agenda-h' },
    h('h2', { id: 'rl-agenda-h' }, 'Agenda'),
    h('ul', { class: 'rl-matters', role: 'list' }, items.map((item) => agendaItem(item, agenda.style, act))));
}

/** The options offered outside the agenda. A guided offer is one plan, so it has no buttons. */
export function initiativePanel(agenda, { act }) {
  if (!agenda.initiative.length) return null;
  return h('section', { class: 'rl-agenda', 'aria-labelledby': 'rl-initiative-h' },
    h('h2', { id: 'rl-initiative-h' }, 'Your own initiative'),
    agenda.style === 'guided' ? planSteps(agenda.initiative) : optionList(agenda.initiative, act));
}

/** The commit again at the foot of the desk; the stylesheet shows it on narrow screens only. */
export function commitPanel(wake, { act }) {
  return h('div', { class: 'rl-commit-foot' },
    h('p', { role: 'status', 'aria-live': 'polite' }, commitCount(wake)),
    commitHint(wake) ? h('p', { class: 'muted rl-wake-hint' }, commitHint(wake)) : null,
    commitControl(wake, act));
}

/** The order the aide read free text as, to sign or revise; or why there is none. */
export function orderCard(p, { onSign, onRevise } = {}) {
  const address = orderAddress(p);
  const ready = p.parts.length > 0;
  return h('section', { class: 'rl-desk-block rl-proposal', 'aria-labelledby': 'rl-proposal-h' },
    h('h3', { id: 'rl-proposal-h' }, orderHeading(p)),
    address ? h('p', { class: 'rl-address' }, address) : null,
    h('blockquote', { class: 'rl-words' }, p.text),
    ready
      ? [h('p', {}, 'Your aide reads this as:'), h('ul', { class: 'rl-terms' }, p.parts.map((t) => h('li', {}, t)))]
      : h('p', { class: 'rl-reason' }, p.reason),
    h('div', { class: 'rl-actions' },
      ready ? h('button', { type: 'button', class: 'rl-submit', onclick: () => onSign?.(p) }, 'Sign and send') : null,
      h('button', { type: 'button', class: 'rl-btn', onclick: () => onRevise?.(p) }, 'Revise')));
}

/** How each routed order landed, under the pending orders; hidden until there is one. */
export function resultsPanel(results) {
  if (!results.length) return null;
  return h('section', { class: 'rl-results', 'aria-labelledby': 'rl-results-h' },
    h('h2', { id: 'rl-results-h' }, 'How your orders landed'),
    h('ul', { class: 'rl-orders', role: 'list' }, results.map((r) => h('li', { class: 'rl-order' },
      h('p', { class: 'rl-order-head' }, `Filed ${dayWords(r.filed)}`),
      h('ul', { class: 'rl-result-parts', role: 'list' }, r.parts.map((p) => h('li', {},
        h('strong', {}, p.ask),
        partLines(p).map((line) => h('p', { class: 'rl-offer-line' }, line)))))))));
}
