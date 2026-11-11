// The opening of a game (Train 3 unit P4): the crawl (realism-crawl.js), then the player's
// own splash. Once per game per browser; never blocks a player whose storage is blocked.

import { h } from '../dom.js';
import { portraitNode } from './realism-dossier.js';

export const INTRO_PREFIX = 'rv.intro.';
export const TAKE_DESK = 'Take your desk';
export const NOT_BINDING = 'As history had it. You are not bound by it.';

const lines = (xs) => (Array.isArray(xs) ? xs.filter((x) => typeof x === 'string' && x.trim()).map((x) => x.trim()) : []);
const text = (x) => (typeof x === 'string' && x.trim() ? x.trim() : null);

const FORCE_KINDS = ['fleet', 'army', 'air'];
const finite = (x) => typeof x === 'number' && Number.isFinite(x);

/** What the seat starts with, for the splash: own forces, the figures on the desk, the first matter. */
export function startOverview({ map, situation, agenda } = {}) {
  const marks = Array.isArray(map?.marks) ? map.marks : [];
  const orders = Array.isArray(map?.orders) ? map.orders : [];
  const forces = marks
    .filter((m) => m?.side === 'own' && FORCE_KINDS.includes(m.kind) && text(m.name))
    .slice(0, 3)
    .map((m) => {
      const place = text(m.places?.[0]?.name);
      const base = place ? `${m.name}: ${place}` : m.name;
      const order = orders.find((o) => o?.status === 'under_way' && o.mark === m.name && text(o.to?.name));
      return order ? `${base} to ${order.to.name}` : base;
    });
  const figures = (Array.isArray(situation?.figures) ? situation.figures : [])
    .filter((f) => text(f?.label) && finite(f.sources?.[0]?.value))
    .slice(0, 3)
    .map((f) => {
      const unit = text(f.unit);
      return `${f.label}: ${f.sources[0].value.toLocaleString('en-US')}${unit ? ` ${unit}` : ''}`;
    });
  const item = (Array.isArray(agenda?.items) ? agenda.items : []).find((i) => text(i?.text));
  const firstText = item ? text(item.text).replace(/\.$/, '') : null;
  const due = item ? text(item.deadline) : null;
  const first = item ? `${firstText}${due && !firstText.includes(due) ? ` (due ${due})` : ''}` : null;
  return { forces, figures, first };
}

/**
 * The splash for the seat named `name`, from the desk and the dossier:
 * `{ title, office, answersTo, arena, history, note, action }`. `title` is "You are <name>";
 * `office` the desk's office or null; `answersTo` "Answers to <principals joined by ', '>" or
 * null with none; `arena` the dossier's arena or null; `history` its lines (may be []);
 * `note` NOT_BINDING when there are history lines, else null; `action` TAKE_DESK; `overview`
 * the `startOverview` result when any part is non-empty, else null.
 */
export function splashModel(name, desk, dossier, overview = null) {
  const principals = lines(desk?.principals);
  const history = lines(dossier?.history);
  const hasOverview = Boolean(overview && (overview.forces?.length || overview.figures?.length || overview.first));
  return {
    title: `You are ${name}`,
    office: text(desk?.office),
    answersTo: principals.length ? `Answers to ${principals.join(', ')}` : null,
    arena: text(dossier?.arena),
    history,
    note: history.length ? NOT_BINDING : null,
    action: TAKE_DESK,
    overview: hasOverview ? overview : null,
  };
}

/**
 * What to show now for campaign `campaignId`: 'crawl', 'splash' or null. `fresh` is false
 * once the seat has filed an order (an old game gets no intro): then null. The stored value
 * under `INTRO_PREFIX + campaignId` is 'crawl' once the crawl was seen and 'done' once the
 * splash was taken: nothing stored gives 'crawl', 'crawl' gives 'splash', 'done' gives null.
 * A store that throws gives null.
 */
export function introStage(store, campaignId, fresh) {
  if (!store || !fresh) return null;
  try {
    const seen = store.getItem(INTRO_PREFIX + campaignId);
    if (seen === 'done') return null;
    return seen === 'crawl' ? 'splash' : 'crawl';
  } catch {
    return null;
  }
}

/**
 * Record that `stage` ('crawl' or 'splash') was seen: stores 'crawl' or 'done'. Swallows a
 * throwing store. A later Begin must not pull a finished splash back to the crawl.
 */
export function markIntro(store, campaignId, stage) {
  if (!store) return;
  const key = INTRO_PREFIX + campaignId;
  try {
    if (stage === 'splash') store.setItem(key, 'done');
    else if (store.getItem(key) !== 'done') store.setItem(key, 'crawl');
  } catch {
    // a blocked store never blocks the player
  }
}

/** The "How you start" section of a splash overview; each part shows only when non-empty. */
function overviewSection(o) {
  const parts = [];
  if (o.forces?.length) parts.push(h('h4', {}, 'Your forces'), h('ul', {}, o.forces.map((x) => h('li', {}, x))));
  if (o.figures?.length) parts.push(h('h4', {}, 'On your desk'), h('ul', {}, o.figures.map((x) => h('li', {}, x))));
  if (o.first) parts.push(h('h4', {}, 'First matter'), h('p', { class: 'rl-intro-first' }, o.first));
  return h('section', { class: 'rl-intro-overview', 'aria-labelledby': 'rl-intro-overview-title' },
    h('h3', { id: 'rl-intro-overview-title' }, 'How you start'),
    ...parts);
}

/**
 * `<dialog class="rl-intro rl-intro-splash" aria-labelledby="rl-intro-splash-title">` from a
 * `splashModel`: `portraitNode(name, dossier, 'rl-intro')`, the h2 title, the office and
 * answers-to lines, the arena paragraph, the "How you start" section (h4 parts, each only when
 * non-empty), the history list under an h3 "As history had it" with the note, and a primary
 * "Take your desk" button. The button and Esc call `onDone()` once.
 */
export function seatSplash({ name, model, dossier = null, onDone } = {}) {
  let done = false;
  const finish = () => {
    if (done) return;
    done = true;
    onDone?.();
  };
  const m = model ?? {};
  const history = m.history ?? [];
  return h('dialog', {
    class: 'rl-intro rl-intro-splash',
    'aria-labelledby': 'rl-intro-splash-title',
    oncancel: (e) => { e.preventDefault(); finish(); },
  },
    h('header', { class: 'rl-intro-splash-head' },
      portraitNode(name, dossier, 'rl-intro'),
      h('h2', { id: 'rl-intro-splash-title' }, m.title ?? '')),
    m.office ? h('p', { class: 'rl-intro-office' }, m.office) : null,
    m.answersTo ? h('p', { class: 'rl-intro-answers' }, m.answersTo) : null,
    m.arena ? h('p', { class: 'rl-intro-arena' }, m.arena) : null,
    m.overview ? overviewSection(m.overview) : null,
    history.length
      ? h('section', { class: 'rl-intro-history', 'aria-labelledby': 'rl-intro-history-title' },
        h('h3', { id: 'rl-intro-history-title' }, 'As history had it'),
        h('ul', {}, history.map((x) => h('li', {}, x))),
        m.note ? h('p', { class: 'rl-intro-note' }, m.note) : null)
      : null,
    h('button', { type: 'button', class: 'rl-intro-take', onclick: finish }, m.action ?? TAKE_DESK));
}
