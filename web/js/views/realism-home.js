// The home sheet and the floor (GRC): the nation's band in the top strip opens the home sheet;
// each of the seat's own groups as a token with its name, a five-step bar (the number on tap)
// and an arrow for its last move with the cause; each chamber as a seat bar split by bloc
// with the line that carries its vote, and each open measure as a bar of yeas, seats not yet counted and nays;
// what moved at the last close; what moved since the seat's last wake, one line a group as the
// server words it, heaviest first, each opening every move behind it with how it reached the
// public; each measure's count at the last wake beside its count now, the blocs that moved
// marked; each place of political weight with its holder, a threatened one marked; and
// "Speak to the nation", which the room answers by opening
// the free-writing form under `speakNote` (the themes and the cap). Once the aide has read a
// statement or a measure, `themeRead` shows which groups the theme it names speaks to, as the
// staff's read and not a promise.
// Everything is read from the seat's `home` block: the server sends only the seat's own
// nation's groups, chambers and themes, and every other nation's band, so another nation's
// groups are never drawn. Nothing here touches the page on import.

import { h, svg } from '../dom.js';
import { worldDate } from '../rules.js';

/** The home sheet's title in the map-first room. */
export const HOME_TITLE = 'At home';

/**
 * The cap on what writing moves a group: the engine's GROUP_DAY_CAP and GROUP_WEEK_CAP
 * (core/realism/effect.py, core/realism/groups.py). The home block does not carry them.
 */
export const DAY_CAP = 3;
export const WEEK_CAP = 6;

/** What moved a group, in words: GRP's causes (core/realism/groups.py Cause). */
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

/**
 * The step of a support figure on the five-step bar, 1 to 5: the lower bounds of GPD's five
 * public bands (engine/web/home_api.py BANDS: 20, 40, 60, 80), so a group's bar reads like a
 * nation's band.
 */
export function supportStep(support) {
  return 1 + [20, 40, 60, 80].filter((low) => support >= low).length;
}

/** GPD's five public bands, lowest first (engine/web/home_api.py BANDS). */
export const BANDS = Object.freeze(['collapsing', 'shaken', 'steady', 'firm', 'united']);

/** The band in words: "steady at home"; a nation with no reading says so. */
export const bandWords = (band) => (band ? `${band} at home` : 'no reading');

/**
 * The top strip's bands: the seat's own, a button that opens the home sheet (`onOpen`), with or
 * without a reading; every other nation's as plain text, and only when it has a reading. `open`
 * marks the own button expanded, and `sheet`, when given, is drawn under the bands (today's
 * room). `null` without a home block or when no band is left to show.
 */
export function homeStrip(rv, { open = false, onOpen, sheet = null } = {}) {
  const shown = (rv.home?.standings ?? []).filter((s) => s.nation.relation === 'own' || s.band);
  if (!shown.length) return null;
  const chips = shown.map((s) => {
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
export function themesFor(home, key) {
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

/** A group's five-step bar: a button whose tap shows the number beside it, and hides it again. */
function supportBar(g) {
  const step = supportStep(g.support);
  const num = h('span', { class: 'rl-home-num', hidden: true }, `${g.support} of 100`);
  const bar = h('button', {
    type: 'button', class: 'rl-home-bar', 'aria-expanded': 'false', 'data-step': String(step),
    'aria-label': `${g.name}: support ${step} of 5. Show the number`,
    onclick: () => {
      const show = bar.getAttribute('aria-expanded') !== 'true';
      bar.setAttribute('aria-expanded', String(show));
      num.toggleAttribute('hidden', !show);
    },
  }, [1, 2, 3, 4, 5].map((i) => h('span', { class: `rl-home-step${i <= step ? ' on' : ''}`, 'aria-hidden': 'true' })));
  return h('div', { class: 'rl-home-support' }, bar, num);
}

/** A last move in words: "Up 5 on 2 April 1900: a battle won"; null when nothing has moved it. */
export const moveWords = (moved) => (moved ? `${capital(signed(moved.change))} on ${worldDate(moved.on)}: ${causeWords(moved.cause)}` : null);

/** How a move reached the public, in words `[proposed]`. */
const REACH = { felt: 'felt at home', reported: 'by report' };

/** One move since the last wake in words: "Down 2 on 4 April 1900: territory lost, by report". */
export const sinceWords = (m) => `${capital(signed(m.change))} on ${worldDate(m.on)}: ${m.why}${REACH[m.reach] ? `, ${REACH[m.reach]}` : ''}`;

/**
 * The server's lines of what moved since the seat's last wake, each with the moves of its group
 * behind it: `[{ ...line, moves }]`. Only the lines the block sends; null when it sends none.
 */
export function movedSince(home) {
  if (!Array.isArray(home?.moved)) return null;
  const groups = new Map((home.groups ?? []).map((g) => [g.key, g]));
  return home.moved.map((m) => ({ ...m, moves: groups.get(m.group)?.since ?? [] }));
}

/** One line of what moved since the last wake: its arrow, its words and a bar of its size against the heaviest, which opens its moves. */
function sinceRow(m, heaviest) {
  const way = m.change < 0 ? 'down' : 'up';
  const list = h('ul', { class: 'rl-home-since-moves', hidden: true },
    m.moves.map((x) => h('li', { class: x.change < 0 ? 'down' : 'up' }, sinceWords(x))));
  const btn = h('button', {
    type: 'button', class: 'rl-home-since-btn', 'aria-expanded': 'false',
    'aria-label': `${m.line}. Show each move`,
    onclick: () => {
      const show = btn.getAttribute('aria-expanded') !== 'true';
      btn.setAttribute('aria-expanded', String(show));
      list.toggleAttribute('hidden', !show);
    },
  },
  h('span', { class: 'rl-home-arrow', 'aria-hidden': 'true' }, m.change < 0 ? '↓' : '↑'),
  h('span', { class: 'rl-home-since-line' }, m.line),
  svg('svg', { class: 'rl-home-since-bar', viewBox: '0 0 100 6', preserveAspectRatio: 'none', 'aria-hidden': 'true', focusable: 'false' },
    svg('rect', { class: 'rl-home-since-fill', x: 0, y: 0, width: share(Math.abs(m.change), heaviest), height: 6 })));
  return h('li', { class: `rl-home-since-row ${way}`, 'data-group': m.group }, btn, list);
}

/** What moved since the seat's last wake, heaviest first, as the server sent it; null when the block sends no list. */
function sinceSection(home) {
  const lines = movedSince(home);
  if (!lines) return null;
  const heaviest = Math.max(1, ...lines.map((m) => Math.abs(m.change)));
  return h('section', { class: 'rl-home-since', 'aria-label': 'Since your last wake' },
    h('h4', {}, 'Since your last wake'),
    lines.length
      ? h('ul', { role: 'list' }, lines.map((m) => sinceRow(m, heaviest)))
      : h('p', { class: 'muted' }, 'Nothing at home has moved since your last wake.'));
}

/** Who holds a place, in words. */
const holderWords = (holder) => `Held by ${holder?.name ?? 'no one'}`;

/** Each place of political weight with its holder, a threatened one marked; null with none. */
function placesSection(home) {
  const places = home.places ?? [];
  if (!places.length) return null;
  return h('section', { class: 'rl-home-places', 'aria-label': 'Places of weight' },
    h('h4', {}, 'Places of weight'),
    h('ul', { role: 'list' }, places.map((p) => h('li', { class: `rl-home-place${p.threatened ? ' threatened' : ''}`, 'data-area': p.key },
      h('strong', {}, p.name), ' ',
      h('span', { class: 'rl-home-holder' }, holderWords(p.holder)),
      p.threatened ? [' ', h('span', { class: 'rl-home-threat' }, 'Threatened')] : null))));
}

/** A last move as an arrow and its words: "↑ Up 5 on 2 April 1900: a battle won". */
function moveLine(moved) {
  if (!moved) return h('p', { class: 'rl-home-moved' }, 'Not moved yet');
  return h('p', { class: `rl-home-moved ${moved.change < 0 ? 'down' : 'up'}` },
    h('span', { class: 'rl-home-arrow', 'aria-hidden': 'true' }, moved.change < 0 ? '↓' : '↑'), ' ',
    moveWords(moved));
}

function groupToken(home, g) {
  const themes = themesFor(home, g.key);
  const bloc = seatsOf(home, g.key);
  return h('li', { class: 'rl-home-group', 'data-group': g.key },
    h('div', { class: 'rl-home-grouphead' },
      h('strong', {}, g.name), ' ', h('span', { class: 'rl-home-kind muted' }, g.kind)),
    supportBar(g),
    moveLine(g.last_moved),
    h('p', { class: 'rl-home-themes' }, themes.length ? `Moved by: ${themes.join(', ')}` : 'No theme moves it'),
    bloc ? h('p', { class: 'rl-home-seats' }, `${bloc.seats} seats in ${chamberName(bloc.chamber)}`) : null);
}

/** A bar's segment width on the 100-wide box: `n` of `total`, nothing below nought. */
const share = (n, total) => (total > 0 ? Math.max(0, Math.min(100, (100 * Number(n)) / total)) : 0);

/** A segment narrower than this share of its bar has no room for its number: it carries it in its name only. */
export const NARROW = 8;

/** The line that carries a vote, drawn on a bar of `total` seats; absent when the server sent no count. */
const carryLine = (carries, total) => (Number.isFinite(carries)
  ? svg('line', { class: 'rl-home-carry', x1: share(carries, total), x2: share(carries, total), y1: 0, y2: 10 }) : null);

/** The count that carries a chamber's open vote: the first measure's first vote, as the server sent it; null with none. */
function chamberCarries(chamber) {
  const vote = (chamber.measures ?? []).flatMap((m) => m.votes ?? []).find((v) => Number.isFinite(v.carries));
  return vote ? vote.carries : null;
}

/** A group's card, opened from its segment: the group's own token, in the chamber it sits in. */
const blocCard = (home, key) => {
  const g = (home.groups ?? []).find((x) => x.key === key);
  return g ? groupToken(home, g) : null;
};

/** A count's yeas, seats not yet counted and nays as segments on a bar of `total` seats. */
const countSegs = (yeas, nays, total) => {
  const open = Math.max(0, total - yeas - nays);
  return [['yeas', yeas, 0], ['open', open, yeas], ['nays', nays, yeas + open]]
    .map(([kind, n, from]) => svg('rect', { class: `rl-home-vseg ${kind}`, 'data-kind': kind, x: share(from, total), y: 0, width: share(n, total), height: 10 }));
};

/**
 * A vote's count at the seat's last wake beside its count now, as a bar and in words, with the
 * blocs whose count moved since; null when the server sent no count then.
 */
function thenBlock(v, names, total) {
  if (!Array.isArray(v.then)) return null;
  const [yeas, nays] = v.then;
  const moved = (v.blocs ?? []).filter((b) => b.moved && Array.isArray(b.then));
  return h('div', { class: 'rl-home-then' },
    svg('svg', {
      class: 'rl-home-bar-box rl-home-thenbar', viewBox: '0 0 100 10', preserveAspectRatio: 'none', role: 'img', focusable: 'false',
      'aria-label': `At your last wake: ${yeas} yea, ${nays} nay`,
    }, countSegs(yeas, nays, total), carryLine(v.carries, total)),
    h('p', { class: 'rl-home-thenline' }, `At your last wake: ${yeas} yea, ${nays} nay. Now: ${v.yeas} yea, ${v.nays} nay.`),
    moved.length
      ? h('p', { class: 'rl-home-thenmoved' }, `Moved since: ${moved.map((b) => `${names.get(b.group) ?? b.group}, ${b.then[0]} yea and ${b.then[1]} nay then`).join('; ')}`)
      : null);
}

/** One vote on a measure: the yeas, the seats not yet counted and the nays as a bar with the line that carries it; a tap shows each bloc's count. */
function voteBlock(m, v, names, total) {
  const uncounted = Math.max(0, total - v.yeas - v.nays);
  const hasLine = Number.isFinite(v.carries);
  const short = hasLine ? v.carries - v.yeas : null;
  const label = `${v.yeas} yea, ${uncounted} not yet counted, ${v.nays} nay${hasLine ? `; ${v.carries} yeas carry it` : ''}. Show each bloc's count`;
  const tokens = h('ul', { class: 'rl-home-tokens', hidden: true }, v.blocs.map((b) => h('li', { class: `rl-home-token${b.moved ? ' moved' : ''}`, 'data-group': b.group },
    h('strong', {}, names.get(b.group) ?? b.group), ` ${b.yeas} yea, ${b.nays} nay`,
    b.moved && b.then ? h('span', { class: 'rl-home-was' }, `; ${b.then[0]} yea, ${b.then[1]} nay at your last wake`) : null)));
  const bar = h('button', {
    type: 'button', class: 'rl-home-votebar', 'aria-expanded': 'false', 'aria-label': label,
    onclick: () => {
      const show = bar.getAttribute('aria-expanded') !== 'true';
      bar.setAttribute('aria-expanded', String(show));
      tokens.toggleAttribute('hidden', !show);
    },
  }, svg('svg', { class: 'rl-home-bar-box', viewBox: '0 0 100 10', preserveAspectRatio: 'none', 'aria-hidden': 'true', focusable: 'false' },
    countSegs(v.yeas, v.nays, total),
    carryLine(v.carries, total)));
  return h('div', { class: 'rl-home-vote', 'data-vote': v.vote },
    m.votes.length > 1 ? h('p', { class: 'rl-home-votename' }, `The ${v.vote} vote`) : null,
    bar,
    tokens,
    thenBlock(v, names, total),
    h('p', { class: 'rl-home-line' },
      hasLine ? `${v.carries} yeas carry it. ` : '', `Counted today: ${v.yeas} yea, ${v.nays} nay`,
      hasLine ? [': ', h('strong', {}, short > 0 ? `short by ${short}` : 'it carries')] : null));
}

/** A chamber's seats as one bar split by bloc, each segment a button for its bloc's card, with the line that carries its open vote. */
function seatBar(home, chamber, total) {
  const card = h('div', { class: 'rl-home-bloccard', hidden: true });
  let open = null;
  let at = 0;
  const segs = chamber.blocs.map((b, i) => {
    const w = share(b.seats, total);
    const x = at;
    at += w;
    const narrow = w < NARROW;
    const pick = () => {
      const same = open === b.group;
      open = same ? null : b.group;
      card.replaceChildren(...(same ? [] : [blocCard(home, b.group)].filter(Boolean)));
      card.toggleAttribute('hidden', same || !card.firstChild);
      for (const r of segEls) r.setAttribute('aria-pressed', String(r.getAttribute('data-group') === open));
    };
    return svg('rect', {
      class: `rl-home-seg b${i % 7}`, 'data-group': b.group, 'data-narrow': narrow ? 'true' : null, x, y: 0, width: w, height: 10,
      role: 'button', tabindex: '0', 'aria-pressed': 'false', 'aria-label': `${b.name}, ${b.seats} seats. Open its card`,
      onclick: pick, onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } },
    });
  });
  const segEls = segs;
  const carries = chamberCarries(chamber);
  const box = svg('svg', { class: 'rl-home-bar-box rl-home-seatbox', viewBox: '0 0 100 10', preserveAspectRatio: 'none', focusable: 'false' },
    segs, carryLine(carries, total));
  const legend = chamber.blocs.map((b) => (share(b.seats, total) < NARROW ? b.name : `${b.name} ${b.seats}`)).join(' · ');
  return h('div', { class: 'rl-home-seatbar', 'data-total': String(total) },
    box,
    h('p', { class: 'rl-home-seatnote' }, legend, carries === null ? null : ` · ${carries} carry the vote`),
    card);
}

/** One chamber of the floor: its seats as a bar split by bloc, then each open measure as a bar. */
function chamberBlock(home, chamber) {
  const name = chamberName(chamber.key);
  const names = new Map(chamber.blocs.map((b) => [b.group, b.name]));
  const total = chamber.blocs.reduce((n, b) => n + b.seats, 0);
  return h('section', { class: 'rl-home-chamber', 'data-chamber': chamber.key, 'aria-label': capital(name) },
    h('h4', {}, capital(name)),
    seatBar(home, chamber, total),
    chamber.measures.length
      ? chamber.measures.map((m) => h('section', { class: 'rl-home-measure', 'data-order': m.order_id, 'aria-label': m.title },
        h('h5', {}, m.title), m.votes.map((v) => voteBlock(m, v, names, total))))
      : h('p', { class: 'rl-home-nomeasure muted' }, `No measure of yours is before ${name}.`));
}

/** ISO day `iso` less `days`, as ISO. */
function daysBefore(iso, days) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

/**
 * The groups the last close moved: each whose last move falls in the `days` the close walked,
 * up to the block's day. Empty without `days`.
 */
export function movedAtClose(home, days) {
  if (!Number.isInteger(days) || days <= 0 || !home?.day) return [];
  const from = daysBefore(home.day, days);
  return (home.groups ?? []).filter((g) => g.last_moved && g.last_moved.on > from && g.last_moved.on <= home.day);
}

/**
 * The home sheet for the seat's `home` block: its standing, what the last close moved (`days`:
 * how many days it walked), each group, the floor (when the nation has a chamber) and "Speak
 * to the nation" (`onSpeak`).
 */
export function homeSheet(home, { onSpeak, days = null } = {}) {
  const chambers = home.chambers ?? [];
  const own = (home.standings ?? []).find((s) => s.nation.relation === 'own');
  const moved = movedAtClose(home, days);
  return h('section', { class: 'rl-home-sheet', 'aria-label': `${home.nation.name} at home`, 'data-nation': home.nation.key },
    h('h3', {}, `${home.nation.name} at home`),
    h('p', { class: 'muted' }, `Counted for ${worldDate(home.day)}.`),
    sinceSection(home),
    home.standing === null || home.standing === undefined ? null
      : h('p', { class: 'rl-home-standing' }, `Standing at home ${home.standing}${own?.band ? `: ${own.band}` : ''}`),
    h('button', { type: 'button', class: 'rl-btn rl-home-speak-btn', onclick: () => onSpeak?.() }, 'Speak to the nation'),
    days ? h('section', { class: 'rl-home-close', 'aria-label': 'Moved at the last close' },
      h('h4', {}, 'Moved at the last close'),
      moved.length
        ? h('ul', {}, moved.map((g) => h('li', { 'data-group': g.key }, h('strong', {}, g.name), ' ', moveLine(g.last_moved))))
        : h('p', { class: 'muted' }, 'Nothing moved at the last close.')) : null,
    placesSection(home),
    h('h4', {}, 'Groups'),
    h('ul', { class: 'rl-home-groups' }, (home.groups ?? []).map((g) => groupToken(home, g))),
    chambers.length
      ? h('section', { class: 'rl-home-floor', 'aria-label': 'The floor' }, h('h4', {}, 'The floor'), chambers.map((c) => chamberBlock(home, c)))
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
      ? [h('p', {}, 'A statement that takes up one of these themes speaks to the groups it names:'),
        h('ul', {}, themes.map((t) => h('li', { class: 'rl-home-theme', 'data-key': t.key }, `${t.name}: ${movesWords(home, t)}`)))]
      : h('p', {}, 'Your nation has no themes listed.'),
    h('p', { class: 'rl-home-cap' },
      `However much you write, your words move each group at most ${DAY_CAP} points a day, and at most ${WEEK_CAP} in any seven days.`));
}

/** Text as the groups rule reads it for a theme: lower case, words split on anything else. */
const plain = (text) => ` ${String(text ?? '').toLowerCase().replace(/[^0-9a-z]+/g, ' ').trim()} `;

/**
 * The theme a read order names: the first of the nation's themes, in the world's order, whose
 * name or key its words or the aide's reading name as whole words (as core/realism/groups.py
 * `named_theme` reads writing). Null when it names none.
 */
export function namedTheme(home, proposal) {
  const said = plain([proposal?.text, ...(proposal?.parts ?? [])].join(' '));
  return (home?.themes ?? []).find((t) => [t.name, t.key].some((p) => plain(p).trim() && said.includes(plain(p)))) ?? null;
}

/**
 * After the reading and before signing: which groups the theme the order names speaks to, as
 * the staff's read and not a promise. Null without a home block or a named theme.
 */
export function themeRead(home, proposal) {
  const theme = namedTheme(home, proposal);
  if (!theme) return null;
  return h('section', { class: 'rl-home-read', 'aria-label': 'Your staff\'s read', 'data-key': theme.key },
    h('p', { class: 'rl-home-read-head' }, h('strong', {}, 'Your staff\'s read'), `: this speaks to ${theme.name}, which reaches ${movesWords(home, theme)}.`),
    h('p', { class: 'rl-home-read-note muted' },
      `A read, not a promise: what your words move is settled at the close, at most ${DAY_CAP} points a group a day.`));
}

/**
 * What needs you: each of the seat's measures on its floor, with its count against what it
 * needs in each vote: `{ key, what, chamber }` per measure.
 */
export function floorMeasures(home) {
  const out = [];
  for (const c of home?.chambers ?? []) {
    for (const m of c.measures ?? []) {
      const counts = m.votes.map((v) => `${v.yeas} yea${Number.isFinite(v.carries) ? ` of the ${v.carries} needed` : ''} in ${m.votes.length > 1 ? `the ${v.vote} vote of ` : ''}${chamberName(c.key)}`);
      out.push({ key: `${c.key}:${m.order_id}`, what: `${m.title}: ${counts.join('; ')}`, chamber: c.key });
    }
  }
  return out;
}

/** The standings of an offer that make it a promise the seat has made: taken, then due, then judged. */
const PROMISED = new Set(['taken', 'due', 'kept', 'broken']);

/** The promises the seat's nation has made, as its own home block sends them; none for any other nation's block. */
export function promisesMade(home) {
  if (home?.nation?.relation !== 'own') return [];
  return (home.promises ?? []).filter((p) => PROMISED.has(p.standing));
}

/** Where promise `p` stands, in words `[proposed]`. */
export function promiseWords(p) {
  if (p.standing === 'kept') return `Kept${p.due ? `, due ${worldDate(p.due)}` : ''}`;
  if (p.standing === 'broken') return `Broken${p.due ? `, due ${worldDate(p.due)}` : ''}`;
  if (p.standing === 'due') return p.due ? `Due ${worldDate(p.due)}` : 'Due';
  return 'Taken: owed once it passes';
}

/** A nation's band from the home block's standings, by its key; undefined when the block has none for it. */
export function bandOf(standings, key) {
  return (standings ?? []).find((s) => s.nation.key === key)?.band;
}
