// "What needs you" (WNY): in the map-first room, the one list of every matter that waits on the
// seat, sorted by due day and then by arrival, with Done at its foot. Each kind of matter is a
// builder in a registry, so a later item adds battles, offers or votes with `addNeedKind` and
// does not edit `needLines`. A line is plain data built from the seat's own view, so it reads
// the same whether any other seat is present or away; a routine receipt is never a line.
// Nothing here touches the page on import.

import { h } from '../dom.js';
import { worldDate } from '../rules.js';
import { boxOf, holderRelation, territoryProjection } from '../realism-rules.js';
import { DONE_HINT, dayKey, dayWords, itemHeading } from './realism-wake.js';
import { floorMeasures } from './realism-home.js';

/** The list's heading and its empty line [proposed]. */
export const NEEDS_TITLE = 'What needs you';
export const NEEDS_NONE = 'Nothing waits on you. Press Done when you are.';
/** The due words of a matter decided when the open wake closes. */
export const AT_CLOSE = 'Due at this wake\'s close';
/** The due words of a matter with no set day. */
export const NO_DAY = 'No set day';

/**
 * The registry: kind -> `build(rv)`, which answers that kind's lines over the room's data, each
 * `{ key, label, what, from, due, arrived, action, at?, paper? }`. `due` and `arrived` are world
 * days (ISO or in words) or null; `at: 'close'` words the due day as the wake's close; `paper` is
 * the id of the paper the matter came on; `action` is `{ word, to, ... }`, where `to` is
 * 'matter' (with the agenda item's `id`), 'sheet' (with its `sheet`), 'map' (with its `area`),
 * 'battle' (with the battle's `area`) or 'commit'. Kinds are listed in registry order where due day and arrival tie.
 */
const KINDS = new Map();

/** Add kind `kind` with its builder; answers a function that takes it out again. */
export function addNeedKind(kind, build) {
  KINDS.set(kind, build);
  return () => { if (KINDS.get(kind) === build) KINDS.delete(kind); };
}

const SEALED = new Set(['Request', 'Decision']);
const items = (rv) => rv.agenda?.items ?? [];

/** An agenda item as a line: `label`, and its paper when it came on one. */
const itemLine = (item, label, word) => ({
  key: item.id, label, what: item.text, from: item.issuer || 'Your desk',
  due: item.deadline || null, arrived: item.issued || null, paper: SEALED.has(item.kind) ? item.id : null,
  action: { word, to: 'matter', id: item.id },
});

// a mandate on the seat's own agenda: from its principal, or the state of the world
addNeedKind('agenda', (rv) => items(rv).filter((i) => !SEALED.has(i.kind))
  .map((i) => itemLine(i, `Agenda: ${i.kind}`, 'Answer')));
// another seat's request put to the seat's person, on the paper that brought it
addNeedKind('request', (rv) => items(rv).filter((i) => i.kind === 'Request').map((i) => itemLine(i, 'Asks you', 'Answer')));
// a step the seat's person holds on another seat's order
addNeedKind('decision', (rv) => items(rv).filter((i) => i.kind === 'Decision').map((i) => itemLine(i, 'Your decision', 'Decide')));
// the seat's own order, waiting at a step its own person holds
addNeedKind('order', (rv) => (rv.orders?.orders ?? []).filter((o) => o.decision_needed).map((o) => ({
  key: o.id, label: 'Your order', what: `${o.label}: it waits on your decision`,
  from: `Your own order, filed ${worldDate(o.filed)}`, due: null, arrived: o.since || o.filed || null,
  action: { word: 'Decide', to: 'sheet', sheet: 'orders' },
})));
// a paper that asks: a territory the seat's side holds is marked to fall at this wake's close,
// named by the paper that warned the seat (a seat without the paper is told nothing)
addNeedKind('paper', (rv) => {
  const docs = rv.documents?.documents ?? [];
  return (rv.map?.areas ?? []).filter((a) => a.falling && holderRelation(a) === 'own').flatMap((a) => {
    // the paper holders.py files for it: a report from the holder, on the day it was marked,
    // titled "<area> will fall at the next close" (cut to 60 characters, so a long name is matched by its start)
    const doc = docs.find((d) => d.kind === 'report' && d.issued === a.falling && d.author === a.holder.name
      && d.title.startsWith(a.name.slice(0, 40)));
    return doc ? [{
      key: doc.id, label: 'Paper', what: doc.title, from: doc.author, due: rv.clock?.world_date ?? null, at: 'close',
      arrived: doc.arrives, paper: doc.id, action: { word: 'Show on map', to: 'map', area: a.key },
    }] : [];
  });
});

// a battle the seat's nation is in that it may decide and has not this wake: due at the close
addNeedKind('battle', (rv) => (rv.battles ?? []).filter((b) => (b.decisions ?? []).length && !b.decided).map((b) => ({
  key: b.area, label: 'Battle', what: `The battle at ${b.name}: your decision for this wake`,
  from: `Your forces against ${b.enemy}`, due: rv.clock?.world_date ?? null, at: 'close',
  arrived: b.rounds?.at(-1)?.on ?? b.opened ?? null, action: { word: 'Decide', to: 'battle', area: b.area },
})));

// a measure of the seat's on its own floor: its count against what it needs; the home sheet shows the floor
addNeedKind('floor', (rv) => floorMeasures(rv.home).map((m) => ({
  key: m.key, label: 'Your measure', what: m.what, from: 'the floor at home', due: null, arrived: null,
  action: { word: 'Show the floor', to: 'sheet', sheet: 'home' },
})));

/** The papers that only acknowledge an order, and the papers an order's receipt names. */
function receipts(rv) {
  const out = new Set((rv.documents?.documents ?? []).filter((d) => d.ack).map((d) => d.id));
  for (const o of rv.record?.orders ?? []) if (o.receipt?.doc) out.add(o.receipt.doc);
  return out;
}

const later = (day) => dayKey(day) ?? Infinity;

/**
 * Every matter that waits on the seat in `rv`, from each registered kind, as `{ kind, ...line }`:
 * sorted by due day (none last), then by arrival, then in registry order. A line on a paper that
 * is a routine receipt is dropped, and a matter two kinds reach is listed once (by kind and key).
 */
export function needLines(rv) {
  const routine = receipts(rv);
  const seen = new Set();
  const out = [];
  for (const [kind, build] of KINDS) {
    for (const line of build(rv) ?? []) {
      const id = `${kind}:${line.key}`;
      if (seen.has(id) || (line.paper && routine.has(line.paper))) continue;
      seen.add(id);
      out.push({ kind, ...line });
    }
  }
  return out.map((line, n) => [line, n])
    .sort(([a, i], [b, j]) => later(a.due) - later(b.due) || later(a.arrived) - later(b.arrived) || i - j)
    .map(([line]) => line);
}

/** By when, in words: "Due 22 October 1941", "Due at this wake's close", or "No set day". */
export function dueWords(line) {
  if (!line.due) return NO_DAY;
  return line.at === 'close' ? AT_CLOSE : `Due ${dayWords(line.due)}`;
}

/** A matter due on or before `today` is urgent: its line carries the amber edge. */
const urgent = (line, today) => line.due && dayKey(today) !== null && later(line.due) <= dayKey(today);

/** The agenda item a 'matter' action opens, with its sheet's title; null when it is no longer there. */
export function matterOf(rv, id) {
  const item = items(rv).find((i) => i.id === id);
  return item ? { item, title: itemHeading(item) } : null;
}

/** The centre of area `key`'s label in the territory drawing's units, or null without its shape. */
export function areaCentre(map, shapes, key) {
  const label = shapes?.areas?.[key]?.label;
  if (!label) return null;
  const proj = territoryProjection(map.coords ?? shapes.coords, boxOf(map.box ?? shapes.box));
  return [proj.x(label[0]), proj.y(label[1])];
}

const badge = (n) => (n > 0 ? h('span', { class: 'badge tone-warn rl-needs-count' }, String(n)) : null);

/** Done for today, or that the seat is done: words that read nothing of any other seat. */
function doneControl(wake, onDone, cls) {
  return wake?.you_committed
    ? h('span', { class: `rl-needs-isdone ${cls}`, role: 'status' }, 'You are done for today.')
    : h('button', { type: 'button', class: `btn-1 ${cls}`, onclick: onDone }, 'Done for today');
}

/**
 * The list: its heading with one badge, a line per matter (what it is, from whom, by when, and
 * one action button calling `onAction(line)`), the empty line, and Done at its foot. From 1024 px
 * it is a rail beside the map; below that it is a half sheet, shown while `open`, which Escape or
 * Close shuts through `onClose`.
 */
export function needsList(rv, lines, { open = false, onAction, onDone, onClose } = {}) {
  const today = rv.clock?.world_date;
  return h('section', {
    class: `rl-needs${open ? ' open' : ''}`, id: 'rl-needs', 'aria-labelledby': 'rl-needs-h',
    onkeydown: (e) => { if (open && e.key === 'Escape') { e.preventDefault(); onClose?.(); } },
  },
  h('div', { class: 'rl-needs-head' },
    h('h2', { id: 'rl-needs-h', tabindex: '-1' }, NEEDS_TITLE, lines.length ? [' ', badge(lines.length)] : null),
    h('span', { class: 'rl-needs-order' }, 'By due day'),
    h('button', { type: 'button', class: 'rl-btn rl-needs-close', onclick: () => onClose?.() }, 'Close')),
  lines.length
    ? h('ul', { class: 'rl-needs-lines', role: 'list' }, lines.map((line) => h('li', {
      class: `rl-need${urgent(line, today) ? ' urgent' : ''}`, 'data-kind': line.kind, 'data-need': line.key,
    },
    h('p', { class: 'rl-need-top' },
      h('span', { class: 'rl-need-kind' }, line.label),
      h('span', { class: 'rl-need-due' }, dueWords(line))),
    h('p', { class: 'rl-need-what' }, line.what),
    h('p', { class: 'rl-need-from' }, `From ${line.from}`),
    h('button', {
      type: 'button', class: 'rl-btn rl-need-act', 'data-need': line.key, 'aria-label': `${line.action.word}: ${line.what}`,
      onclick: () => onAction?.(line),
    }, line.action.word))))
    : h('p', { class: 'rl-needs-none' }, NEEDS_NONE),
  h('div', { class: 'rl-needs-done' },
    h('p', { class: 'hint' }, `Press Done for today when you have answered what you want to. ${DONE_HINT}`),
    doneControl(rv.wake, onDone, 'rl-needs-commit')));
}

/** The phone's bottom bar: the Needs button with the list's badge, and Done for today. */
export function needsBar(rv, lines, { open = false, onToggle, onDone } = {}) {
  return h('nav', { class: 'rl-needsbar', 'aria-label': 'What needs you' },
    h('button', {
      type: 'button', class: 'rl-btn rl-needs-btn', 'aria-expanded': String(open), 'aria-controls': 'rl-needs', onclick: onToggle,
    }, 'Needs', lines.length ? [' ', badge(lines.length)] : null),
    doneControl(rv.wake, onDone, 'rl-needsbar-commit'));
}
