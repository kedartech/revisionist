// The opponents list: who is set against the seat, as its staff believe it (view.realism.threats).
// The stance is as of the last day the staff had evidence, so every line says how old that is.

import { h } from '../dom.js';
import { worldDate } from '../rules.js';
import { chip } from './ui-kit.js';

const TREND = { worse: 'Hardening', better: 'Easing', steady: '' };
const ARROW = { worse: '↗', better: '↘' };
const AGE = { firm: '', dated: ' Some weeks old.', old: ' Old news: it may have changed.' };
const CONFIDENCE = { firm: ['Firm', 3], dated: ['Dated', 2], old: ['Old', 1] };

/** One plain record per threat, in the order the server sent them (most hostile first). */
export function threatLines(threats) {
  return (threats ?? []).map((t) => ({
    person: t.person,
    name: t.name,
    office: t.office,
    stance: t.stance,
    label: t.stance_label,
    trend: TREND[t.trend] ?? '',
    known: `As of ${worldDate(t.as_of)}.${AGE[t.confidence] ?? ''}`,
    over: t.over.length ? `Over: ${t.over.join('; ')}` : '',
    cause: t.cause,
  }));
}

/** The panel for the top of the orders column, or null when nobody is set against the seat. */
export function threatsPanel(threats) {
  const lines = threatLines(threats);
  if (!lines.length) return null;
  return h('section', { class: 'rl-threats', 'aria-labelledby': 'rl-threats-h' },
    h('h2', { id: 'rl-threats-h' }, 'Opponents'),
    h('ul', { class: 'rl-threat-list' }, lines.map((l, i) => {
      const [word, pips] = CONFIDENCE[threats[i].confidence] ?? ['', 0];
      return h('li', { class: 'rl-threat' },
        h('p', { class: 'rl-threat-who' }, h('strong', null, l.name), ' ', h('span', { class: 'rl-threat-office' }, l.office)),
        h('p', { class: 'rl-threat-how' },
          h('span', { class: `rl-threat-stance rl-threat-${l.stance}` },
            chip(l.label, l.stance === 'hostile' ? 'danger' : 'warn')),
          l.trend ? ' ' : null,
          l.trend ? h('span', { class: 'rl-threat-trend' },
            h('span', { class: 'rl-threat-arrow', 'aria-hidden': 'true' }, ARROW[threats[i].trend]), ` ${l.trend}`) : null),
        l.over ? h('p', { class: 'rl-threat-over' }, l.over) : null,
        h('p', { class: 'rl-threat-known' }, `${l.known} ${l.cause}`),
        h('p', { class: 'rl-threat-conf' },
          h('span', { class: 'rl-pips', 'aria-hidden': 'true' },
            [1, 2, 3].map((n) => h('span', { class: n <= pips ? 'rl-pip on' : 'rl-pip' }))),
          ` ${word}`));
    })));
}
