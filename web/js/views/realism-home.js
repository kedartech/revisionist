// The home sheet and the floor (GRC): the nation's band in the top strip opens the home sheet;
// each of the seat's own groups with its support as a bar, what last moved it and when, the
// themes that move it, and its seats when it is a bloc; the floor: each bloc's seats and its
// expected vote on the seat's open measures, with the count; "Speak to the nation", which the
// room answers by opening the free-writing form under `speakNote` (the themes and the cap).
// Everything is read from the seat's `home` block: the server sends only the seat's own
// nation's groups, chambers and themes, and every other nation's band, so another nation's
// groups are never drawn. Nothing here touches the page on import.

import { h } from '../dom.js';
import { worldDate } from '../rules.js';

/** The home sheet's title in the map-first room. */
export const HOME_TITLE = 'At home';

/**
 * The cap on what writing moves a group: the engine's GROUP_DAY_CAP and GROUP_WEEK_CAP
 * (core/realism/effect.py, core/realism/groups.py). The home block does not carry them, so
 * they are stated here [proposed].
 */
export const DAY_CAP = 3;
export const WEEK_CAP = 6;

/** What moved a group, in words: GRP's causes. */
const CAUSES = {
  battle_won: 'a battle won',
  battle_lost: 'a battle lost',
  territory_taken: 'a territory taken',
  territory_lost: 'a territory lost',
  capital_threatened: 'the capital threatened',
  losses_at_sea: 'losses at sea',
  agreement_broken: 'an agreement broken',
  measure_passed: 'a measure passed',
  war_declared: 'a declaration of war',
  writing: 'your words',
  drift: 'the weekly drift',
};
const causeWords = (cause) => CAUSES[cause] ?? String(cause ?? '').replace(/_/g, ' ');

/** A change in points as words: "up 5", "down 2". */
const signed = (n) => (n < 0 ? `down ${-n}` : `up ${n}`);

/** A chamber's key as a name: "assembly" -> "the assembly". */
const chamberName = (key) => `the ${String(key).replace(/_/g, ' ')}`;
const capital = (s) => s.charAt(0).toUpperCase() + s.slice(1);

/** The yeas a measure needs to pass a vote: a majority of the members voting. */
export function needed(vote) {
  return Math.floor((Number(vote.yeas) + Number(vote.nays)) / 2) + 1;
}

/** The band in words: "steady at home"; a nation with no reading says so. */
const bandWords = (band) => (band ? `${band} at home` : 'no reading');

/**
 * The top strip's bands: one per nation, the seat's own a button that opens the home sheet
 * (`onOpen`), every other nation's plain text. `open` marks the own button expanded, and
 * `sheet`, when given, is drawn under the bands (today's room). `null` without a home block.
 */
export function homeStrip(rv, { open = false, onOpen, sheet = null } = {}) {
  const home = rv.home;
  if (!home?.standings?.length) return null;
  const chips = home.standings.map((s) => {
    const own = s.nation.relation === 'own';
    const label = `${own ? `${s.nation.name} (yours)` : s.nation.name}: ${bandWords(s.band)}`;
    return own
      ? h('button', {
        type: 'button', class: 'rl-home-chip rl-home-own', 'aria-expanded': String(open),
        'data-nation': s.nation.key, onclick: () => onOpen?.(),
      }, label)
      : h('span', { class: 'rl-home-chip rl-home-other', 'data-nation': s.nation.key }, label);
  });
  return h('div', { class: 'rl-home' },
    h('div', { class: 'rl-home-chips', role: 'group', 'aria-label': 'Standing at home by nation' }, chips),
    open ? sheet : null);
}

/** The status strip `strip` with the nation's bands appended (`homeStrip`'s options); answers `strip`. */
export function withHome(strip, rv, opts) {
  const bands = homeStrip(rv, opts);
  if (bands) strip.append(bands);
  return strip;
}

/** The themes that move group `key`: "The Levy Act (up 1)". */
function themesFor(home, key) {
  return (home.themes ?? []).filter((t) => t.moves?.[key]).map((t) => `${t.name} (${signed(t.moves[key])})`);
}

/** The chamber a bloc sits in, and its seats there. */
function seatsOf(home, key) {
  for (const c of home.chambers ?? []) {
    const bloc = c.blocs.find((b) => b.group === key);
    if (bloc) return { chamber: c.key, seats: bloc.seats };
  }
  return null;
}

function groupItem(home, g) {
  const moved = g.last_moved;
  const themes = themesFor(home, g.key);
  const bloc = seatsOf(home, g.key);
  return h('li', { class: 'rl-home-group', 'data-group': g.key },
    h('div', { class: 'rl-home-grouphead' },
      h('strong', {}, g.name), ' ', h('span', { class: 'rl-home-kind muted' }, g.kind)),
    h('div', { class: 'rl-home-support' },
      h('meter', { min: 0, max: 100, value: g.support, 'aria-label': `${g.name}: support ${g.support} of 100` }),
      h('span', {}, `Support ${g.support} of 100`)),
    h('p', { class: 'rl-home-moved' }, moved
      ? `Last moved ${signed(moved.change)} on ${worldDate(moved.on)}, by ${causeWords(moved.cause)}`
      : 'Not moved yet'),
    h('p', { class: 'rl-home-themes' }, themes.length ? `Moved by: ${themes.join(', ')}` : 'No theme moves it'),
    bloc ? h('p', { class: 'rl-home-seats' }, `${bloc.seats} seats in ${chamberName(bloc.chamber)}`) : null);
}

/** A bloc's expected vote on one measure: "71 yea, 29 nay", summed over its votes in the chamber. */
function blocVote(measure, group) {
  let yeas = 0;
  let nays = 0;
  for (const v of measure.votes) {
    const b = v.blocs.find((x) => x.group === group);
    if (b) { yeas += b.yeas; nays += b.nays; }
  }
  return `${yeas} yea, ${nays} nay`;
}

/** One chamber of the floor: each bloc's seats and its expected vote on each open measure, then the counts. */
function chamberBlock(chamber) {
  const name = chamberName(chamber.key);
  const counts = chamber.measures.flatMap((m) => m.votes.map((v) => h('p', { class: 'rl-home-count', 'data-order': m.order_id },
    `${m.title}${m.votes.length > 1 ? ` (${v.vote})` : ''}: ${v.yeas} yea, ${v.nays} nay. ${needed(v)} needed to pass.`)));
  return h('section', { class: 'rl-home-chamber', 'data-chamber': chamber.key, 'aria-label': capital(name) },
    h('h4', {}, capital(name)),
    h('div', { class: 'rl-home-table-wrap' },
      h('table', { class: 'rl-home-table' },
        h('thead', {}, h('tr', {},
          h('th', { scope: 'col' }, 'Bloc'), h('th', { scope: 'col' }, 'Seats'),
          chamber.measures.map((m) => h('th', { scope: 'col' }, m.title)))),
        h('tbody', {}, chamber.blocs.map((b) => h('tr', { 'data-group': b.group },
          h('th', { scope: 'row' }, b.name), h('td', {}, String(b.seats)),
          chamber.measures.map((m) => h('td', {}, blocVote(m, b.group)))))))),
    counts.length ? counts : h('p', { class: 'rl-home-nomeasure muted' }, `No measure of yours is before ${name}.`));
}

/**
 * The home sheet for the seat's `home` block: its standing, each group, the floor (when the
 * nation has a chamber) and "Speak to the nation" (`onSpeak`).
 */
export function homeSheet(home, { onSpeak } = {}) {
  const chambers = home.chambers ?? [];
  const own = (home.standings ?? []).find((s) => s.nation.relation === 'own');
  return h('section', { class: 'rl-home-sheet', 'aria-label': `${home.nation.name} at home`, 'data-nation': home.nation.key },
    h('h3', {}, `${home.nation.name} at home`),
    h('p', { class: 'muted' }, `Counted for ${worldDate(home.day)}.`),
    home.standing === null || home.standing === undefined ? null
      : h('p', { class: 'rl-home-standing' }, `Standing at home ${home.standing}${own?.band ? `: ${own.band}` : ''}`),
    h('button', { type: 'button', class: 'rl-btn rl-home-speak-btn', onclick: () => onSpeak?.() }, 'Speak to the nation'),
    h('h4', {}, 'Groups'),
    h('ul', { class: 'rl-home-groups' }, (home.groups ?? []).map((g) => groupItem(home, g))),
    chambers.length
      ? h('section', { class: 'rl-home-floor', 'aria-label': 'The floor' }, h('h4', {}, 'The floor'), chambers.map(chamberBlock))
      : null);
}

/** "The Norra Public up 2, The Smiths' Guild down 1": the groups a theme moves, by name. */
function movesWords(home, theme) {
  const names = new Map((home.groups ?? []).map((g) => [g.key, g.name]));
  return Object.entries(theme.moves ?? {}).map(([key, n]) => `${names.get(key) ?? key} ${signed(n)}`).join(', ');
}

/** What stands above the free-writing form when the seat speaks to the nation: the themes and the cap. */
export function speakNote(home) {
  const themes = home.themes ?? [];
  return h('section', { class: 'rl-home-speak', 'aria-label': 'Speak to the nation' },
    h('h3', {}, 'Speak to the nation'),
    themes.length
      ? [h('p', {}, 'A statement that takes up one of these themes moves the groups it names:'),
        h('ul', {}, themes.map((t) => h('li', { class: 'rl-home-theme', 'data-key': t.key }, `${t.name}: ${movesWords(home, t)}`)))]
      : h('p', {}, 'Your nation has no themes listed.'),
    h('p', { class: 'rl-home-cap' },
      `However much you write, your words move each group at most ${DAY_CAP} points a day, and at most ${WEEK_CAP} in any seven days.`));
}

/**
 * What needs you: each of the seat's measures on its floor, with its count against what it
 * needs in each vote: `{ key, what, chamber }` per measure.
 */
export function floorMeasures(home) {
  const out = [];
  for (const c of home?.chambers ?? []) {
    for (const m of c.measures ?? []) {
      const counts = m.votes.map((v) => `${v.yeas} yea of the ${needed(v)} needed in ${m.votes.length > 1 ? `the ${v.vote} vote of ` : ''}${chamberName(c.key)}`);
      out.push({ key: `${c.key}:${m.order_id}`, what: `${m.title}: ${counts.join('; ')}`, chamber: c.key });
    }
  }
  return out;
}
