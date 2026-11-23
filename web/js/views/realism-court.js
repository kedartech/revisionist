// The Court board: the seat's own people along the paths its orders travel
// (view.realism.court). One track per path with the forms that use it: a stop per decision step
// in order, a small mark for a clerical step, each step as long as its days with the days under
// it, and each of the seat's orders in flight a marker on the step that holds it, named under
// the track. Under the paths, the circle and chain on no path, grouped by bloc; beside them, each
// chamber's seats by party with the line that carries a vote, and its public votes. A picked
// stop or chip shows that person's figure card with the two moves the seat already has on them:
// ask them a question, or write them an order. Nothing here touches the page on import.

import { h, svg } from '../dom.js';
import { worldDate } from '../rules.js';
import { channelWord } from '../realism-rules.js';
import { figureCard } from './realism-figure.js';
import { along, track } from './realism-tracks.js';

const ROSTER = ['yours', 'opponents', 'others'];

/** The People roster line for `person` and the tab it sits on, or null when the roster has none. */
function rosterLine(people, person) {
  for (const tab of ROSTER) {
    const line = (people?.[tab] ?? []).find((l) => l.person === person);
    if (line) return { line, tab };
  }
  return null;
}

/** The messenger's contact named `name`, from any reach group, or null. */
function contactFor(reach, name) {
  for (const key of ['inner_circle', 'government', 'foreign', 'other']) {
    const hit = (reach?.[key] ?? []).find((c) => c.name === name);
    if (hit) return hit;
  }
  return null;
}

/** "Send a bill to Congress, with Sam Rayburn: day 9 of about 8": the day it is on, counting the day it came as one. */
function token(o, step) {
  const on = `day ${o.held_days + 1}`;
  const of = Number.isInteger(step.days) ? `${on} of about ${step.days}` : `${on}; no time stated`;
  return h('li', { class: 'rl-court-tok' }, `${o.label}, with ${step.you ? 'you' : step.name}: ${of}`);
}

function tokens(path) {
  const all = path.steps.flatMap((s) => s.orders.map((o) => token(o, s)));
  return all.length ? h('ul', { class: 'rl-court-toks', 'aria-label': 'Your orders on this path' }, all) : null;
}

/** Only the waiting tokens on this seat's square contribute to its load. */
function load(step, limit) {
  if (!Number.isInteger(limit) || limit < 1) return null;
  const count = step.orders.length;
  const slow = count >= limit;
  return h('span', {
    class: 'rl-court-load', role: 'img',
    'aria-label': `${count} orders waiting; load limit ${limit}${slow ? '; slow' : ''}`,
  },
  h('span', { class: 'rl-court-pips', 'aria-hidden': 'true' },
    Array.from({ length: Math.max(count, limit) }, (_, i) => h('span', { class: `rl-court-pip${i < count ? ' on' : ''}` }))),
  h('span', { 'aria-hidden': 'true' }, `${count} of ${limit}${slow ? ' · slow' : ''}`));
}

/** A decision step's stop: a button that picks the person, or for the seat's own step a plain box. */
function square(step, selected, onPick, limit) {
  const holds = step.orders.length > 0;
  const name = step.you ? 'You' : step.name;
  const body = [
    h('span', { class: 'rl-court-name' }, name),
    step.office ? h('span', { class: 'rl-court-office' }, step.office) : null,
    load(step, limit),
  ];
  const cls = `rl-court-sq${holds ? ' holds' : ''}${step.you ? ' you' : ''}`;
  const title = step.office ? `${name}, ${step.office}` : name;
  if (step.you) return h('div', { class: cls, title }, body);
  return h('button', {
    type: 'button',
    class: cls,
    title,
    'aria-pressed': selected === step.person ? 'true' : 'false',
    onclick: () => onPick(step),
  }, body);
}

/** A clerical step: a small mark with who, never a person to pick. */
function clerk(step) {
  return h('span', { class: 'rl-court-clerk', title: step.name }, step.name);
}

function pathRow(path, selected, onPick, limit) {
  const segs = path.steps.map((s) => ({
    name: s.you ? 'You' : s.name,
    kind: s.kind === 'clerical' ? 'mark' : 'stop',
    days: s.days,
    body: s.kind === 'clerical' ? clerk(s) : square(s, selected, onPick, limit),
    markers: s.orders.map((o) => ({ id: o.id, at: along(o.held_days, s.days) })),
  }));
  return h('li', { class: 'rl-court-path' },
    h('h3', { class: 'rl-court-path-name' }, path.name),
    path.forms.length ? h('p', { class: 'rl-court-forms' }, `Forms: ${path.forms.join(', ')}`) : null,
    segs.length
      ? track(`${path.name}: its steps`, segs)
      : h('p', { class: 'muted' }, 'No step is known on this path.'),
    tokens(path));
}

/** "in person" or "by cable": how the seat reaches someone. */
function how(channel) {
  if (!channel) return null;
  const word = channelWord(channel).toLowerCase();
  return channel === 'in_person' ? word : `by ${word}`;
}

/** The ring grouped by bloc in order of first appearance; a person the roster does not place is under Other, last. */
function ringGroups(ring, people) {
  const groups = new Map();
  for (const r of ring) {
    const bloc = rosterLine(people, r.person)?.line.bloc || 'Other';
    if (!groups.has(bloc)) groups.set(bloc, []);
    groups.get(bloc).push(r);
  }
  const other = groups.get('Other');
  if (other) {
    groups.delete('Other');
    groups.set('Other', other);
  }
  return [...groups];
}

function ringBlock(ring, people, selected, onPick) {
  if (!ring.length) return null;
  return h('section', { class: 'rl-court-ring', 'aria-labelledby': 'rl-court-ring-h' },
    h('h3', { id: 'rl-court-ring-h' }, 'Your circle, on no path today'),
    ringGroups(ring, people).map(([bloc, members]) => h('div', { class: 'rl-court-bloc' },
      h('h4', {}, bloc),
      h('ul', { class: 'rl-court-chips' }, members.map((r) => h('li', {},
        h('button', {
          type: 'button',
          class: 'rl-court-chip',
          'aria-pressed': selected === r.person ? 'true' : 'false',
          onclick: () => onPick(r),
        }, r.name, how(r.channel) ? h('span', { class: 'rl-court-how' }, ` · ${how(r.channel)}`) : null)))))));
}

/** A chamber: its seats by party as a bar with the line that carries a vote, then its public votes. */
function chamberBlock(c) {
  const total = c.seats.reduce((n, p) => n + p.seats, 0);
  let x = 0;
  const parts = c.seats.map((p, i) => {
    const rect = svg('rect', { class: `rl-court-party p${i}`, x, y: 0, width: p.seats, height: 10 });
    x += p.seats;
    return rect;
  });
  const label = `${c.seats.map((p) => `${p.seats} ${p.party}`).join(', ')}; ${c.carries} seats carry a vote`;
  const bar = svg('svg', {
    class: 'rl-court-seats', viewBox: `0 0 ${total} 10`, preserveAspectRatio: 'none', role: 'img', 'aria-label': label,
  }, parts, svg('line', { class: 'rl-court-carry', x1: c.carries, x2: c.carries, y1: 0, y2: 10 }));
  const votes = c.votes.length
    ? h('ul', { class: 'rl-court-votes' }, c.votes.map((v) => h('li', { class: 'rl-court-vote' },
      `${v.name}: ${v.yeas} yeas, ${v.nays} nays${v.as_of ? `, ${worldDate(v.as_of)}` : ''}`)))
    : h('p', { class: 'rl-court-votes muted' }, 'No public vote yet.');
  return h('section', { class: 'rl-court-chamber', 'aria-label': c.name },
    h('h3', {}, `${c.name} · ${total} seats`),
    bar,
    h('p', { class: 'rl-court-parties' }, [...c.seats.map((p) => `${p.seats} ${p.party}`), `${c.carries} carry a vote`].join(' · ')),
    votes);
}

/** Everyone the court names, by person id: each step's holder but the seat, and each ring member. */
function courtPeople(court) {
  const out = new Map();
  for (const p of court.paths) for (const s of p.steps) if (!s.you) out.set(s.person, s);
  for (const r of court.ring) out.set(r.person, r);
  return out;
}

/** Ask: the messenger opens on their thread, as its Contacts tab does. */
function askThem(ui, pick, name) {
  ui.chat = { open: true, tab: 'chats', thread: name };
  pick?.({ tab: 'messages' });
}

/** Write: the order form beside the board is addressed to them, keeping any words typed. */
function writeThem(ui, pick, c) {
  ui.orderTo = c;
  ui.proposal = null;
  ui.draft = { to: c.name, channel: c.channel_keys[0], text: ui.draft?.text ?? '' };
  ui.chat = { ...ui.chat, open: false };
  pick?.({});
  document.body?.querySelector('.rl-board-side .rl-write textarea')?.focus();
}

function moves(rv, ui, pick, name) {
  const c = contactFor(rv.reach, name);
  const ask = (c?.channels ?? []).length > 0;
  const write = (c?.channel_keys ?? []).length > 0;
  return h('div', { class: 'rl-court-moves' },
    ask ? h('button', { type: 'button', class: 'rl-btn', onclick: () => askThem(ui, pick, name) }, 'Ask them a question') : null,
    write ? h('button', { type: 'button', class: 'rl-btn', onclick: () => writeThem(ui, pick, c) }, 'Write them an order') : null,
    ask || write ? null : h('p', { class: 'muted' }, 'You cannot reach them from here.'));
}

/** The picked person: their figure card's head and groups, or their name and office; then the moves. */
function selectedBlock(rv, ui, pick, who) {
  const found = rosterLine(rv.people, who.person);
  let card;
  if (found) {
    const dialog = figureCard(found.line, found.tab);
    card = [...dialog.children].filter((c) => !c.classList.contains('rl-dos-foot'));
  } else {
    card = [
      h('h3', { class: 'rl-court-sel-name' }, who.name),
      who.office ? h('p', { class: 'rl-fc-office' }, who.office) : null,
      h('p', { class: 'muted' }, 'Your staff hold no card on them.'),
    ];
  }
  return h('section', { class: 'rl-court-sel', 'aria-label': `Selected: ${who.name}` },
    card, moves(rv, ui, pick, who.name));
}

/**
 * `courtBoard(rv, ui, { pick, act })`: the Court, for the board's main area. A square or chip
 * picked is `pick({ piece: { kind: 'person', person, name } })`, and picked again
 * `pick({ piece: null })`. The two moves write the room's `ui.chat`, or `ui.orderTo` and
 * `ui.draft`, as the messenger's Contacts tab does, then `pick` redraws.
 */
export function courtBoard(rv, ui, { pick } = {}) {
  const court = rv?.court;
  const head = h('h2', { id: 'rl-court-h' }, 'Court');
  if (!court) {
    return h('section', { class: 'rl-court', 'aria-labelledby': 'rl-court-h' },
      head, h('p', { class: 'muted' }, 'No court has reached this view yet.'));
  }
  const selected = ui?.piece?.kind === 'person' ? ui.piece.person : null;
  const onPick = (p) => {
    pick?.({ piece: selected === p.person ? null : { kind: 'person', person: p.person, name: p.name } });
    document.body?.querySelector('.rl-court [aria-pressed="true"]')?.focus();
    // on a narrow screen the card sits under the paths, out of sight of the square tapped
    document.body?.querySelector('.rl-court-sel')?.scrollIntoView?.({ block: 'nearest' });
  };
  const who = selected ? courtPeople(court).get(selected) : null;
  const paths = court.paths.length
    ? h('ol', { class: 'rl-court-paths', 'aria-label': 'Paths' }, court.paths.map((p) => pathRow(p, selected, onPick, court.load_limit)))
    : h('p', { class: 'muted' }, 'None of your forms travels a path yet.');
  const chambers = court.chambers.length
    ? h('div', { class: 'rl-court-chambers' }, court.chambers.map(chamberBlock))
    : null;
  const side = who || chambers
    ? h('div', { class: 'rl-court-aside' }, who ? selectedBlock(rv, ui, pick, who) : null, chambers)
    : null;
  return h('section', { class: 'rl-court', 'aria-labelledby': 'rl-court-h' },
    head,
    h('div', { class: `rl-court-body${side ? '' : ' single'}` },
      h('div', { class: 'rl-court-main' }, paths, ringBlock(court.ring, rv.people, selected, onPick)),
      side));
}
