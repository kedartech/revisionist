// The opening of a ready-made game on screen: a nation, then a path, then a person, each drawn
// from the server's `/api/new/opening` answer. A step with one choice is passed over and shown
// as chosen. Who can be taken, who is taken and how many seats are left are the server's; the
// client only lays them out. Taking a person is the cast screen's own pick by name.

import { api } from '../api.js';
import { h } from '../dom.js';
import { flagBadge, loadFlagIndex } from '../flags.js';
import { portraitNode } from './realism-dossier.js';

export const EVERYONE = 'Show everyone';
export const EVERYONE_OPEN = 'Hide everyone';
export const STEPS_LEAD = 'Choose a nation, then a path, then the person you will play.';
export const NOBODY_LEFT = 'Nobody in this game is left to play.';
export const UNLISTED = 'A nation with nobody to play is not listed; it appears the day its data gives it one.';

const STEPS = ['Nation', 'Path', 'Person'];
const PATH_WORDS = {
  political: { label: 'Political', line: 'Lead the nation: the floor, the home front, the orders.' },
  military: { label: 'Military', line: 'Command a force; your orders meet the locks above you.' },
};
const NO_POST = { label: 'Without a post', line: 'People the world gives no ladder of office.' };

const pathWords = (path) => PATH_WORDS[path] ?? (path ? { label: path, line: '' } : NO_POST);
const nationId = (n) => n.key ?? '';
const pathId = (p) => p.path ?? '';
const everyoneIn = (paths) => paths.flatMap((p) => p.persons ?? []);

function tally(persons) {
  const free = persons.filter((p) => !p.taken).length;
  return { free, total: persons.length, words: free ? `${free} to play` : 'all taken' };
}

/**
 * Where the opening stands for `choice` ({ nation, path }, ids as `nationId`/`pathId` give
 * them): `{ step, nations, nation, nationFixed, paths, path, pathFixed, persons, seatsLeft,
 * seatsMax }`. A list of one is chosen at once and marked fixed.
 */
export function openingModel(opening, choice = {}) {
  const nations = Array.isArray(opening?.nations) ? opening.nations : [];
  const nationFixed = nations.length === 1;
  const nation = nationFixed ? nations[0] : nations.find((n) => nationId(n) === choice.nation) ?? null;
  const paths = nation?.paths ?? [];
  const pathFixed = paths.length === 1;
  const path = !nation ? null : pathFixed ? paths[0] : paths.find((p) => pathId(p) === choice.path) ?? null;
  const step = !nation ? 'nation' : !path ? 'path' : 'person';
  return {
    step,
    nations,
    nation,
    nationFixed,
    paths,
    path,
    pathFixed,
    persons: path?.persons ?? [],
    seatsLeft: Number(opening?.seats_left) || 0,
    seatsMax: Number(opening?.seats_max) || 0,
  };
}

function pips(persons, cls) {
  return h('span', { class: `rl-op-pips ${cls}`, 'aria-hidden': 'true' },
    persons.map((p) => h('span', { class: p.taken ? 'rl-op-pip' : 'rl-op-pip on' })));
}

function seatsMeter(m) {
  const said = m.seatsLeft ? `${m.seatsLeft} of ${m.seatsMax} seats left` : 'No seats left';
  return h('div', {
    class: 'rl-op-seats',
    role: 'meter',
    'aria-label': 'Seats left',
    'aria-valuemin': 0,
    'aria-valuemax': m.seatsMax,
    'aria-valuenow': m.seatsLeft,
    'aria-valuetext': said,
  },
  h('span', { class: 'rl-op-seat-pips', 'aria-hidden': 'true' },
    Array.from({ length: m.seatsMax }, (_, i) => h('span', { class: i < m.seatsLeft ? 'rl-op-seat on' : 'rl-op-seat' }))),
  h('span', { class: 'rl-op-seat-words' }, said));
}

/**
 * The opening as a `section.rl-op`: the three steps, the seats left, and the choices of the
 * step being chosen. `onTake(name)` runs the claim; `onRead(name)` opens a roster person's
 * dossier. `roster` lends a portrait by name; `world` and `nationKeys` find each flag.
 */
export function openingView({ opening, roster = [], world = null, nationKeys = {}, onTake, onRead }) {
  const choice = { nation: null, path: null };
  const bar = h('nav', { class: 'rl-op-steps', 'aria-label': 'Steps' });
  const body = h('div', { class: 'rl-op-body' });
  const section = h('section', { class: 'rl-op', 'aria-label': 'Choose a nation, a path and a person' }, bar, body);
  const people = new Map((Array.isArray(roster) ? roster : []).map((c) => [c.name, c]));

  const go = (next) => {
    Object.assign(choice, next);
    draw(true);
  };

  function stepNode(i, m) {
    const chosen = [m.nation?.name, m.path ? pathWords(m.path.path).label : null][i] ?? null;
    const fixed = [m.nationFixed, m.pathFixed][i] ?? false;
    const current = ['nation', 'path', 'person'][i] === m.step;
    const text = !chosen ? `${i + 1}. ${STEPS[i]}` : `${i + 1}. ${STEPS[i]}: ${chosen}${fixed ? ' (the only one)' : ''}`;
    if (chosen && !fixed) {
      const back = i === 0 ? { nation: null, path: null } : { path: null };
      return h('button', { type: 'button', class: 'rl-op-step done', onclick: () => go(back) }, text);
    }
    return h('span', {
      class: `rl-op-step${fixed ? ' fixed done' : current ? ' current' : ' later'}`,
      'aria-current': current ? 'step' : null,
    }, text);
  }

  function nationCard(n) {
    const t = tally(everyoneIn(n.paths ?? []));
    const key = n.key == null ? null : nationKeys?.[n.key] ?? null;
    return h('button', {
      type: 'button',
      class: 'rl-op-card rl-op-nation',
      'aria-label': `${n.name}: ${t.words}`,
      onclick: () => go({ nation: nationId(n), path: null }),
    },
    flagBadge({ world, key, name: n.name, relation: 'neutral' }, { height: 40 }),
    h('span', { class: 'rl-op-name' }, n.name),
    h('span', { class: 'rl-op-count' }, pips(everyoneIn(n.paths ?? []), 'rl-op-people'), h('span', {}, t.words)));
  }

  function pathCard(p) {
    const w = pathWords(p.path);
    const t = tally(p.persons ?? []);
    return h('button', {
      type: 'button',
      class: 'rl-op-card rl-op-path',
      'aria-label': `${w.label}: ${t.words}`,
      onclick: () => go({ path: pathId(p) }),
    },
    h('span', { class: 'rl-op-name' }, w.label),
    w.line ? h('span', { class: 'rl-op-line' }, w.line) : null,
    h('span', { class: 'rl-op-count' }, pips(p.persons ?? [], 'rl-op-people'), h('span', {}, t.words)));
  }

  function personCard(p) {
    const known = people.get(p.name) ?? null;
    return h('article', { class: p.taken ? 'rl-op-card rl-op-person taken' : 'rl-op-card rl-op-person' },
      h('span', { class: 'rl-op-media' }, portraitNode(p.name, known?.dossier ?? null, 'rl-op')),
      h('span', { class: 'rl-op-text' },
        h('h3', { class: 'rl-op-who' }, p.name),
        p.office ? h('span', { class: 'rl-op-office' }, p.office) : null,
        p.pitch ? h('span', { class: 'rl-op-pitch' }, p.pitch) : null,
        known?.reach ? h('span', { class: 'rl-op-reach' }, known.reach) : null,
        p.taken ? h('span', { class: 'rl-op-taken' }, 'Taken') : null,
        h('span', { class: 'rl-op-acts' },
          p.taken ? null : h('button', {
            type: 'button',
            class: 'primary rl-op-take',
            'aria-label': `Take this seat: ${p.name}`,
            onclick: () => onTake?.(p.name),
          }, 'Take this seat'),
          known && onRead ? h('button', { type: 'button', class: 'rl-op-read', onclick: () => onRead(p.name) }, 'Read the dossier') : null)));
  }

  function backButton(m) {
    if (m.step === 'person' && !m.pathFixed) return h('button', { type: 'button', class: 'rl-op-back', onclick: () => go({ path: null }) }, '‹ Path');
    if (m.step !== 'nation' && !m.nationFixed) return h('button', { type: 'button', class: 'rl-op-back', onclick: () => go({ nation: null, path: null }) }, '‹ Nations');
    return null;
  }

  function draw(moved) {
    const m = openingModel(opening, choice);
    bar.replaceChildren(...STEPS.map((_, i) => stepNode(i, m)), seatsMeter(m));
    let cards;
    if (m.step === 'nation') cards = m.nations.map(nationCard);
    else if (m.step === 'path') cards = m.paths.map(pathCard);
    else cards = m.persons.map(personCard);
    body.replaceChildren(...[
      cards.length
        ? h('div', { class: `rl-op-grid rl-op-${m.step}s` }, cards)
        : h('p', { class: 'rl-op-none' }, NOBODY_LEFT),
      m.step === 'nation' && cards.length ? h('p', { class: 'hint rl-op-note' }, UNLISTED) : null,
      backButton(m),
    ].filter(Boolean));
    if (moved) body.querySelector('.rl-op-grid button')?.focus();
  }

  draw(false);
  return section;
}

/** "Show everyone": opens and closes the flat cast `flat` under the steps. */
function everyoneToggle(flat) {
  const button = h('button', { type: 'button', class: 'rl-op-everyone', 'aria-expanded': 'false' }, EVERYONE);
  button.addEventListener('click', () => {
    const open = flat.hasAttribute('hidden');
    flat.toggleAttribute('hidden', !open);
    button.setAttribute('aria-expanded', String(open));
    button.textContent = open ? EVERYONE_OPEN : EVERYONE;
  });
  return button;
}

/**
 * Ask the server for the opening and lay it out in `holder`. A ready-made game gets the three
 * steps, the lead line `lead` saying so, and the flat cast `flat` hidden behind "Show everyone". A pitched game, a refusal or
 * a failure leaves `flat` as the only view and calls `onPitched`, as the cast screen was before.
 */
export async function openingInto(holder, flat, { roster, lead = null, onTake, onRead, onPitched }) {
  const flags = loadFlagIndex();
  let r = null;
  try {
    r = await api.newGame('opening', {});
  } catch {
    r = null;
  }
  if (!r || r.refused || !r.opening || r.ready_made !== true) {
    holder.replaceChildren();
    flat.removeAttribute('hidden');
    onPitched?.();
    return;
  }
  await flags;
  flat.setAttribute('hidden', '');
  if (lead) lead.textContent = STEPS_LEAD;
  holder.replaceChildren(
    openingView({ opening: r.opening, roster, world: r.world ?? null, nationKeys: r.nation_keys ?? {}, onTake, onRead }),
    everyoneToggle(flat));
}
