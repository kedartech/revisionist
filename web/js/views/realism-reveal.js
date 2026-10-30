// The end-of-game reveal (Phase 4 unit C5): the route #reveal/<id>, from me.finished.

import { api } from '../api.js';
import { h } from '../dom.js';
import { worldDate } from '../rules.js';
import { header } from './frame.js';

const text = (v) => (typeof v === 'string' ? v.trim() : '');

/** A seat's parts in reading order, each with its heading; empty parts are dropped. */
export function revealParts(seat) {
  const list = (items) => (items ?? []).map(text).filter(Boolean);
  const rulings = (seat?.rulings ?? [])
    .map((r) => ({ when: r.on ? worldDate(r.on) : '', ask: text(r.ask), rationale: text(r.rationale) }))
    .filter((r) => r.ask || r.rationale);
  return [
    { key: 'goals', title: 'Their secret goals', items: list(seat?.goals) },
    { key: 'covert', title: 'What they did in secret', items: list(seat?.covert) },
    { key: 'styles', title: 'How they played', items: list(seat?.styles) },
    { key: 'rulings', title: "The estimator's rulings", items: rulings },
  ].filter((p) => p.items.length);
}

/** The seats with something to show, in the order the server sent them. */
export function revealSeats(reveal) {
  return (reveal?.seats ?? [])
    .map((seat) => ({ person: text(seat.person), parts: revealParts(seat) }))
    .filter((s) => s.person || s.parts.length);
}

/** The heading over a game's reveal. */
export const revealHeading = (name) => `${name}: what was hidden`;

/** The link wording for an ended game on the home screen. */
export const revealLinkLabel = (name) => `See the reveal of ${name}`;

function ruling(r) {
  return h('li', { class: 'rv-ruling' },
    r.when ? h('span', { class: 'rv-when' }, r.when) : null,
    r.ask ? h('span', { class: 'rv-ask' }, r.ask) : null,
    r.rationale ? h('blockquote', { class: 'rv-quote' }, h('p', {}, r.rationale)) : null);
}

function seatFile(seat, index) {
  const id = `rv-seat-${index}`;
  return h('section', { class: 'rv-file', 'aria-labelledby': id },
    h('h2', { id, class: 'rv-tab' }, seat.person),
    h('div', { class: 'rv-sheet' }, seat.parts.map((part) => {
      const pid = `${id}-${part.key}`;
      return h('section', { class: 'rv-part', 'aria-labelledby': pid },
        h('h3', { id: pid }, part.title),
        h('ul', { class: part.key === 'rulings' ? 'rv-list rv-rulings' : 'rv-list' },
          part.items.map((it) => (part.key === 'rulings' ? ruling(it) : h('li', {}, it)))));
    })));
}

/** The reveal of `finished` ({ id, name }), fetched with api.reveal. */
export function realismReveal({ me, finished, go, signOut, refresh }) {
  const status = h('p', { class: 'rv-status', role: 'status', 'aria-live': 'polite' }, 'Opening the files…');
  const files = h('div', { class: 'rv-files' });
  api.reveal(finished.id).then((res) => {
    const seats = res?.refused ? [] : revealSeats(res);
    if (res?.refused || !res?.seats) {
      status.textContent = text(res?.reply) || 'The files could not be opened.';
      status.classList.add('error');
      return;
    }
    status.textContent = seats.length ? '' : 'Nothing was hidden.';
    files.append(...seats.map(seatFile));
  }).catch((e) => {
    status.textContent = text(e?.message) || 'The files could not be opened.';
    status.classList.add('error');
  });
  return h('div', { class: 'screen rv-screen' },
    header({ me, game: finished, role: 'The reveal', refresh, signOut }),
    h('main', { class: 'rv-main', 'aria-labelledby': 'rv-title' },
      h('h1', { id: 'rv-title' }, revealHeading(finished.name)),
      status,
      files,
      h('a', {
        class: 'rv-back', href: '#home',
        onclick: (e) => { e.preventDefault(); go('home'); },
      }, 'Back to your games')));
}

/** The account's ended games on its home screen, each with its reveal. */
export function finishedList({ me, go }) {
  const frag = document.createDocumentFragment();
  const games = me?.finished ?? [];
  if (!games.length) return frag;
  frag.append(h('section', { class: 'rv-ended', 'aria-labelledby': 'rv-ended-title' },
    h('h2', { id: 'rv-ended-title' }, 'Ended games'),
    h('ul', { class: 'rv-list' }, games.map((g) => h('li', {},
      h('span', { class: 'rv-name' }, g.name),
      h('a', {
        href: `#reveal/${g.id}`, 'aria-label': revealLinkLabel(g.name),
        onclick: (e) => { e.preventDefault(); go(`reveal/${g.id}`); },
      }, 'See the reveal'))))));
  return frag;
}
