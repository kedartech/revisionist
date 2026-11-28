// The piece's card (KPB): an own piece's kind as the server sends it with `kinds_in_battle` on. Its
// picture, the kind's name, the five figures as five-step meters (here, beside the kind's own),
// what is changing each one where it stands, and one line of the weather in its region this month
// and next with what that does to this kind. A lit area's comparison sets the figures as they would
// stand there beside the figures now. An enemy report's head shows its kind's picture and name
// only when the report names it, with its source and age. Every figure, cause and day is the
// server's: nothing here works one out, and nothing is drawn for a piece that is not the seat's own.
// Nothing here touches the page on import.

import { h } from '../dom.js';
import { stepLeft } from '../motion.js';
import { reportAge, reportAgoWords, reportWhat, sourceWord } from '../realism-rules.js';
import { markSwatch } from './realism-map.js';

/** The five figures, in the order the card draws them, each with its name. */
export const FIGURES = Object.freeze([
  ['attack', 'Attack'], ['defence', 'Defence'], ['speed', 'Speed'], ['reach', 'Reach'], ['hidden', 'Hidden'],
]);
const FIGURE_NAME = Object.fromEntries(FIGURES);
const STEPS = 5;

/** Each cause's fixed words, the server's own (map_api.CAUSE_WORDS). */
const CAUSE = Object.freeze({
  terrain: 'the ground', weather: 'the weather', out_of_supply: 'out of supply', out_of_fuel: 'out of fuel',
  air_cover: 'air cover', enemy_kind: 'an enemy kind reported there',
});

const MONTH = Object.freeze({
  jan: 'January', feb: 'February', mar: 'March', apr: 'April', may: 'May', jun: 'June',
  jul: 'July', aug: 'August', sep: 'September', oct: 'October', nov: 'November', dec: 'December',
});

const step = (n) => (Number.isInteger(n) ? Math.max(0, Math.min(STEPS, n)) : null);

/** The kind the server sent for an own piece's mark; null for any other mark, or with the switch off. */
export function ownKind(mark) {
  if (mark?.side !== 'own') return null;
  const kind = mark.piece?.figures;
  return kind?.here && kind.figures ? kind : null;
}

/**
 * A figure as five steps, `value` of them on; the steps between it and `base` drawn as lost (under
 * `base`) or gained (over it). `said` is its name for a reader; the number is drawn beside it.
 * Kept as `keep`, a step moved since it was last drawn shows the step it left for a moment.
 */
function figureMeter(key, value, base, said, keep = null) {
  const differs = base !== null && base !== value;
  const cls = (i) => {
    if (i < value) return differs && i >= base ? 'rl-mark-step on rl-pc-gained' : 'rl-mark-step on';
    return differs && i < base ? 'rl-mark-step rl-pc-lost' : 'rl-mark-step';
  };
  const steps = h('span', { class: 'rl-mark-steps', 'aria-hidden': 'true' }, Array.from({ length: STEPS }, (_, i) => h('span', { class: cls(i) })));
  if (keep) stepLeft(steps.children, keep, value);
  return h('span', { class: 'rl-mark rl-mark-meter rl-mark-own rl-pc-meter', role: 'img', 'data-figure': key, 'aria-label': said },
    steps, h('span', { class: 'rl-mark-num', 'aria-hidden': 'true' }, String(value)));
}

/** The figures the server sent, in the card's order, each with its step and the step beside it. */
function sentFigures(values, bases) {
  return FIGURES.map(([key, name]) => ({ key, name, value: step(values?.[key]), base: step(bases?.[key]) }))
    .filter((f) => f.value !== null);
}

/** A cause in words: its fixed words, with the server's own name for it where that says more. */
export function causeWords(cause, words) {
  const fixed = CAUSE[cause] ?? '';
  return words && words !== fixed ? (fixed ? `${fixed} (${words})` : words) : fixed;
}

/** One change as a line: its figure, its direction and its cause; a change naming no figure is not drawn. */
function changeLine(c) {
  const figure = FIGURE_NAME[c?.figure];
  if (!figure || (c.direction !== 'up' && c.direction !== 'down')) return null;
  const said = causeWords(c.cause, c.words);
  if (!said) return null;
  // its arrow is drawn by the stylesheet from `data-direction`
  return h('li', { 'data-figure': c.figure, 'data-direction': c.direction, 'data-cause': c.cause }, `${figure} ${c.direction}: ${said}`);
}

function changeList(changes) {
  const lines = (changes ?? []).map(changeLine).filter(Boolean);
  return lines.length ? h('ul', { class: 'rl-pc-changes', role: 'list' }, lines) : null;
}

/** The weather row for `region`: its own, else that of the nearest region it lies in that has one. */
function weatherRow(map, region) {
  const parent = new Map((map.regions ?? []).map((r) => [r.key, r.parent ?? null]));
  const seen = new Set();
  for (let at = region; at && !seen.has(at); at = parent.get(at)) {
    const row = (map.weather.regions ?? []).find((r) => r.region === at && (r.now || r.next));
    if (row) return row;
    seen.add(at);
  }
  return null;
}

const listWords = (items) => items.join(', ').replace(/, ([^,]*)$/, ' and $1');
const terrainWords = (keys) => listWords(keys.map((k) => k.replace(/_/g, ' ')));
const aKind = (name) => (/^[aeiou]/i.test(name) ? `an ${name}` : `a ${name}`);

/** What weather `w` does to `kind`, from the server's own lines for it. */
function weatherDoes(w, kind) {
  const does = (w.does ?? []).filter((d) => d.kind === kind.key && FIGURE_NAME[d.figure]);
  if (!does.length) return `${w.name}: nothing to ${aKind(kind.name)}.`;
  const said = does.map((d) => {
    const on = d.terrain?.length ? terrainWords(d.terrain) : '';
    if (d.direction === 'closed') return `${on || 'every area'} closed to it`;
    return `${FIGURE_NAME[d.figure].toLowerCase()} ${d.direction}${on ? ` on ${on}` : ''}`;
  });
  return `${w.name}: ${said.join('; ')}.`;
}

/**
 * The weather line for an own piece: its region's weather this month and next, and what each does
 * to its kind. Null with the weather off, or when the map does not say where the piece stands.
 */
export function weatherLine(map, mark) {
  const kind = ownKind(mark);
  if (!kind || !map?.weather) return null;
  const region = (map.areas ?? []).find((a) => a.key === mark.piece.area?.key)?.region ?? null;
  if (!region) return null;
  const name = (key) => (map.regions ?? []).find((r) => r.key === key)?.name ?? key;
  const row = weatherRow(map, region);
  if (!row) return h('p', { class: 'rl-pc-weather' }, `Weather in ${name(region)}: none given.`);
  const kinds = new Map((map.weather.kinds ?? []).map((w) => [w.key, w]));
  const when = [[row.now, map.weather.month], [row.next, map.weather.next_month]].filter(([w]) => kinds.has(w));
  const held = when.map(([w, m]) => `${kinds.get(w).name} in ${MONTH[m] ?? m}`);
  const what = [...new Set(when.map(([w]) => w))].map((w) => weatherDoes(kinds.get(w), kind));
  return h('p', { class: 'rl-pc-weather' }, `Weather in ${name(row.region)}: ${held.join(', ')}. ${what.join(' ')}`);
}

/**
 * An own piece's card: `<section class="rl-pc-card">`, or null for another's mark, a mark with no
 * kind the world names, or with `kinds_in_battle` off. `map` is the seat's map block.
 */
export function pieceCard(map, mark) {
  const kind = ownKind(mark);
  if (!kind) return null;
  const rows = sentFigures(kind.here, kind.figures).map((f) => h('div', { class: 'rl-pc-row', 'data-figure': f.key },
    h('span', { class: 'rl-pc-fig' }, f.name),
    figureMeter(f.key, f.value, f.base,
      `${f.name}: ${f.value} of ${STEPS}${f.base !== null && f.base !== f.value ? ` here, ${f.base} for its kind` : ''}`,
      `pc:${mark.key ?? mark.name}:${f.key}`)));
  return h('section', { class: 'rl-pc-card', 'aria-label': `${kind.name}: its figures` },
    h('p', { class: 'rl-pc-head' }, markSwatch(mark), h('span', { class: 'rl-pc-kind' }, kind.name), h('span', { class: 'rl-pc-its' }, 'its figures')),
    h('div', { class: 'rl-pc-figs' }, rows),
    h('h4', { class: 'rl-pc-sub' }, 'What is changing them here'),
    changeList(kind.changes) ?? h('p', { class: 'muted rl-pc-none' }, 'Nothing here changes its figures.'),
    weatherLine(map, mark));
}

/**
 * The figures as they would stand in a lit area beside the figures now, for an own piece's move
 * `mv`: `<section class="rl-pc-there">`, or null when the server sent no figures for the move.
 */
export function figuresThere(mark, mv) {
  const kind = ownKind(mark);
  if (!kind || !mv?.figures) return null;
  const where = mv.area?.name ?? 'there';
  const rows = sentFigures(mv.figures, kind.here).map((f) => {
    const now = f.base ?? f.value;
    return h('div', { class: 'rl-pc-row', 'data-figure': f.key },
      h('span', { class: 'rl-pc-fig' }, f.name),
      figureMeter(f.key, now, null, `${f.name} now: ${now} of ${STEPS}`),
      figureMeter(f.key, f.value, now, `${f.name} in ${where}: ${f.value} of ${STEPS}${now !== f.value ? `, ${now} now` : ''}`));
  });
  return h('section', { class: 'rl-pc-there', 'aria-label': `${kind.name} in ${where}, beside now` },
    h('h4', {}, `${kind.name} in ${where}, beside now`),
    h('p', { class: 'rl-pc-cols', 'aria-hidden': 'true' }, h('span', {}, 'Now'), h('span', {}, 'There')),
    h('div', { class: 'rl-pc-figs rl-pc-pair' }, rows),
    changeList(mv.changes));
}

/**
 * An enemy report's head: its kind's picture and name only when the report names the kind, with
 * its source and age. Never a figure. `<p class="rl-pc-report">`.
 */
export function reportHead(r, today) {
  const named = Boolean(r.kind && r.kind_name && r.kind_name !== 'unknown');
  const picture = named ? r.picture ?? null : null;
  return h('p', { class: 'rl-pc-report' },
    picture ? markSwatch({ side: 'other', kind: null, certainty: 'reported', picture }) : null,
    h('span', { class: 'rl-pc-kind' }, reportWhat(r)),
    h('span', { class: 'rl-pc-said' }, `${sourceWord(r.source)}, ${reportAgoWords(reportAge(r.seen, today))}`));
}
